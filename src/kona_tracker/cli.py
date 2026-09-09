"""`kona` command line. Slice 1 ships only `kona probe`."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from kona_tracker.fi.client import FiClient, FiError
from kona_tracker.probe.run import run_probe

app = typer.Typer(help="kona-tracker tools.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """kona-tracker tools. Typer collapses a single command into the root command;
    this callback keeps `kona probe` as a real subcommand so more can follow."""


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser: no dotenv dependency for two variables.
    Ignores blank lines and '#' comments; strips one layer of matching quotes."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


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


def main() -> None:  # pragma: no cover - console entry
    sys.exit(app())
