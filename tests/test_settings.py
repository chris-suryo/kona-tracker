import pytest

from kona_tracker.web.settings import SettingsError, load_settings


def test_missing_passcode_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("KONA_PASSCODE", raising=False)
    with pytest.raises(SettingsError, match="KONA_PASSCODE"):
        load_settings(tmp_path / "none.env")


def test_env_file_values_and_generated_secret_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KONA_PASSCODE", raising=False)
    monkeypatch.delenv("KONA_SECRET", raising=False)
    (tmp_path / ".env").write_text("KONA_PASSCODE=1234\nKONA_CAMERA_INDEX=2\n", encoding="utf-8")
    s = load_settings(tmp_path / ".env", fake_camera=True)
    assert s.passcode == "1234" and s.camera_index == 2 and s.fake_camera
    assert len(s.secret) > 20
    assert "KONA_SECRET not set" in capsys.readouterr().err
