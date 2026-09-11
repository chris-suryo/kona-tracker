"""`kona` command line: `probe` (Fi API discovery), `serve` (web app), `cameras`."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from kona_tracker.cli_env import read_env_file
from kona_tracker.fi.client import FiClient, FiError
from kona_tracker.probe.run import run_probe

app = typer.Typer(help="kona-tracker tools.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """kona-tracker tools. Typer collapses a single command into the root command;
    this callback keeps `kona probe` as a real subcommand so more can follow."""


def load_credentials(env_file: Path) -> tuple[str, str]:
    """Environment wins over the file, so a one-off override needs no edit."""
    from_file = read_env_file(env_file)
    email = os.environ.get("FI_EMAIL") or from_file.get("FI_EMAIL", "")
    password = os.environ.get("FI_PASSWORD") or from_file.get("FI_PASSWORD", "")
    return email, password


@app.command()
def probe(
    env_file: Annotated[
        Path, typer.Option(help="KEY=VALUE file with FI_EMAIL/FI_PASSWORD.")
    ] = Path(".env"),
    out: Annotated[Path, typer.Option(help="Directory for redacted dumps.")] = Path("probe-out"),
) -> None:
    """Log into Fi once and dump every field the API exposes (redacted)."""
    email, password = load_credentials(env_file)
    if not email or not password:
        typer.echo(
            f"FI_EMAIL / FI_PASSWORD not set. Put them in {env_file} (see .env.example) "
            "or set them in the environment.",
            err=True,
        )
        raise typer.Exit(code=2)

    with FiClient() as client:
        try:
            client.login(email, password)
        except FiError as e:
            typer.echo(f"Login failed: {e}", err=True)
            raise typer.Exit(code=1) from None
        typer.echo("Logged in.")
        report = run_probe(client, out)

    typer.echo(f"Pets: {', '.join(p['name'] for p in report.pets) or 'none found'}")
    typer.echo(f"Introspection: {'ok' if report.introspection_ok else 'unavailable'}")
    for step, msg in report.errors.items():
        typer.echo(f"  ! {step}: {msg}")
    typer.echo(f"Wrote {len(report.files)} file(s) to {out}/ -- open summary.md first.")


@app.command()
def serve(
    host: Annotated[
        str, typer.Option(help="Bind address; 0.0.0.0 = reachable on Wi-Fi.")
    ] = "0.0.0.0",
    port: Annotated[int, typer.Option()] = 8000,
    env_file: Annotated[Path, typer.Option(help="KEY=VALUE file with KONA_* settings.")] = Path(
        ".env"
    ),
    fake_camera: Annotated[bool, typer.Option(help="Test pattern instead of a webcam.")] = False,
) -> None:
    """Run the web app (passcode gate + live camera) on the local network."""
    import uvicorn

    from kona_tracker.web.app import create_app
    from kona_tracker.web.settings import SettingsError, load_settings

    try:
        settings = load_settings(env_file, fake_camera=fake_camera)
    except SettingsError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from None
    typer.echo(f"kona-tracker on http://{host}:{port}  (camera: {settings.camera_label()})")
    # proxy_headers=False: uvicorn would otherwise rewrite the client address
    # from X-Forwarded-For whenever the peer is 127.0.0.1 -- which is every
    # request through a local tunnel. The lockout must key on exactly the
    # header KONA_TRUSTED_PROXY_HEADER names, and on nothing when it is unset.
    # MJPEG responses are endless. Bound the response drain so lifespan
    # cleanup (which stops the camera) is reached even with a phone connected.
    uvicorn.run(
        create_app(settings),
        host=host,
        port=port,
        log_level="info",
        proxy_headers=False,
        timeout_graceful_shutdown=5,
    )


@app.command()
def cameras() -> None:
    """List camera indexes that open (so KONA_CAMERA_INDEX is not a guess)."""
    from kona_tracker.camera.source import probe_camera_indexes

    found = probe_camera_indexes()
    if not found:
        typer.echo("No camera opened at indexes 0-4. Is it plugged in / not in use by another app?")
        raise typer.Exit(code=1)
    typer.echo("Cameras that open: " + ", ".join(str(i) for i in found))
    typer.echo(f"Set KONA_CAMERA_INDEX={found[0]} in .env (or another index from the list).")


@app.command("camera-test")
def camera_test(
    env_file: Annotated[Path, typer.Option(help="KEY=VALUE file with KONA_* settings.")] = Path(
        ".env"
    ),
    frames: Annotated[int, typer.Option(help="Frames to read before reporting.")] = 10,
) -> None:
    """Open the configured camera once and report size, fps, bytes per frame.

    The first thing to run with real hardware. Prints the redacted URL and the
    exact open/read error; never the password.
    """
    import time

    from kona_tracker.camera.redact import redact_url
    from kona_tracker.camera.source import CameraFrameError
    from kona_tracker.web.app import default_source_factory
    from kona_tracker.web.settings import SettingsError, load_settings

    try:
        settings = load_settings(env_file)
    except SettingsError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from None
    typer.echo(f"Opening {settings.camera_label()} ...")
    started = time.monotonic()
    try:
        source = default_source_factory(settings)()
    except Exception as e:
        typer.echo(f"Open failed: {redact_url(f'{type(e).__name__}: {e}')}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Opened in {time.monotonic() - started:.1f}s")
    sizes: list[int] = []
    t0 = time.monotonic()
    try:
        while len(sizes) < frames and time.monotonic() - t0 < 30:
            jpeg = source.read_jpeg()
            if jpeg:
                sizes.append(len(jpeg))
    except CameraFrameError as e:
        typer.echo(f"Read failed: {e}. Check the lens cover and room light.", err=True)
        raise typer.Exit(code=1) from None
    finally:
        source.close()
    elapsed = time.monotonic() - t0
    if not sizes:
        typer.echo("Opened, but no frames arrived in 30 s.", err=True)
        raise typer.Exit(code=1)
    w = getattr(source, "width", "?")
    h = getattr(source, "height", "?")
    typer.echo(
        f"{len(sizes)} frames in {elapsed:.1f}s ({len(sizes) / max(elapsed, 1e-6):.1f} fps), "
        f"{sum(sizes) // len(sizes)} bytes/frame avg, size {w}x{h}"
    )


@app.command("camera-doctor")
def camera_doctor(
    indexes: Annotated[int, typer.Option(help="How many indexes to try, from 0.")] = 5,
    frames: Annotated[int, typer.Option(help="Frames to sample per backend.")] = 5,
) -> None:
    """Why is the picture black? Try every index and backend, report the pixels.

    `camera-test` is a health check: it fails when the picture is unusable.
    That is right, and useless when the question is *why*. This never fails.
    It prints raw statistics so the answer is readable rather than guessed.

    The column that matters is **sd** (standard deviation). All-zero pixels
    with no variation mean a closed shutter or a driver returning an empty
    buffer. A genuinely dark room still has sensor noise, so its mean is low
    but its sd is not. Those two need opposite fixes.
    """
    from kona_tracker.camera.source import inspect_cameras

    typer.echo(f"Probing indexes 0-{indexes - 1}, {frames} frames each. Nothing else may be")
    typer.echo("using the camera: close Windows Settings > Camera, Teams, Zoom, video tabs.\n")
    try:
        reports = inspect_cameras(range(0, indexes), frames_per=frames)
    except Exception as e:
        typer.echo(f"Could not probe at all: {type(e).__name__}: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"{'idx':<4}{'backend':<13}{'size':<12}{'frames':<8}{'mean':<9}{'max':<8}{'sd':<9}verdict"
    )
    typer.echo("-" * 78)
    for r in reports:
        size = f"{r.width}x{r.height}" if r.opened else "-"
        mean = f"{r.stats.mean:.2f}" if r.stats else "-"
        mx = f"{r.stats.maximum:.0f}" if r.stats else "-"
        sd = f"{r.stats.stddev:.2f}" if r.stats else "-"
        typer.echo(
            f"{r.index:<4}{r.backend:<13}{size:<12}{r.frames:<8}{mean:<9}{mx:<8}{sd:<9}{r.verdict}"
        )

    typer.echo("")
    live = [r for r in reports if r.verdict == "usable"]
    if live:
        best = live[0]
        typer.echo(f"A usable picture came from index {best.index} via {best.backend}.")
        typer.echo(f"Set KONA_CAMERA_INDEX={best.index} in .env and run `uv run kona serve`.")
        raise typer.Exit(code=0)

    opened = [r for r in reports if r.opened and r.stats]
    if not opened:
        typer.echo("No camera delivered a frame on any index or backend.")
        typer.echo("Either nothing is plugged in, or another program owns it.")
        raise typer.Exit(code=1)
    worst = max(opened, key=lambda r: r.stats.stddev if r.stats else 0.0)
    typer.echo(f"The camera opens but the picture is not usable ({worst.verdict}):")
    typer.echo(f"  {worst.detail}")
    raise typer.Exit(code=1)


def main() -> None:  # pragma: no cover - console entry
    sys.exit(app())
