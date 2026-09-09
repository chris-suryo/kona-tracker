from pathlib import Path

from typer.testing import CliRunner

from kona_tracker.cli import app, read_env_file

runner = CliRunner()


def test_read_env_file_handles_comments_quotes_and_bom(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_bytes(b'\xef\xbb\xbf# comment\nFI_EMAIL="a@b.c"\nFI_PASSWORD=p=ss\n\nJUNK\n')
    assert read_env_file(p) == {"FI_EMAIL": "a@b.c", "FI_PASSWORD": "p=ss"}


def test_probe_without_credentials_exits_2(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FI_EMAIL", raising=False)
    monkeypatch.delenv("FI_PASSWORD", raising=False)
    result = runner.invoke(app, ["probe", "--env-file", str(tmp_path / "none.env")])
    assert result.exit_code == 2
    assert "FI_EMAIL" in result.output
