"""`kona` command line: `probe` (Fi API discovery), `serve` (web app), `cameras`."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from kona_tracker.cli_env import read_env_file
from kona_tracker.fi.client import FiClient, FiLoginError
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
        except FiLoginError as e:
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
    cam = "fake" if fake_camera else f"index {settings.camera_index}"
    typer.echo(f"kona-tracker on http://{host}:{port}  (camera: {cam})")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")


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


def main() -> None:  # pragma: no cover - console entry
    sys.exit(app())
