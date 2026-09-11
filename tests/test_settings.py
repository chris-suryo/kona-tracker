from datetime import date

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


def test_rtsp_settings_split_embedded_credentials_and_mask_repr(tmp_path, monkeypatch):
    for k in (
        "KONA_PASSCODE",
        "KONA_SECRET",
        "KONA_RTSP_URL",
        "KONA_RTSP_USER",
        "KONA_RTSP_PASSWORD",
    ):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env").write_text(
        "KONA_PASSCODE=1234\nKONA_SECRET=x\nKONA_CAMERA_SOURCE=rtsp\n"
        "KONA_RTSP_URL=rtsp://kona:hunter2@10.0.0.9:554/stream1\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / ".env")
    assert s.camera_source == "rtsp"
    assert s.rtsp_url == "rtsp://10.0.0.9:554/stream1"
    assert (s.rtsp_user, s.rtsp_password) == ("kona", "hunter2")
    assert (
        "hunter2" not in repr(s)
        and "1234" not in repr(s)
        and "x" not in repr(s).split("secret")[1][:5]
    )
    assert s.camera_label() == "rtsp rtsp://10.0.0.9:554/stream1"


def test_rtsp_requires_url_and_source_is_validated(tmp_path, monkeypatch):
    monkeypatch.delenv("KONA_RTSP_URL", raising=False)
    monkeypatch.setenv("KONA_PASSCODE", "1")
    monkeypatch.setenv("KONA_SECRET", "s")
    monkeypatch.setenv("KONA_CAMERA_SOURCE", "rtsp")
    with pytest.raises(SettingsError, match="KONA_RTSP_URL"):
        load_settings(tmp_path / "none.env")
    monkeypatch.setenv("KONA_CAMERA_SOURCE", "webcam")
    with pytest.raises(SettingsError, match="KONA_CAMERA_SOURCE"):
        load_settings(tmp_path / "none.env")
    assert load_settings(tmp_path / "none.env", fake_camera=True).fake_camera


def test_scheme_less_rtsp_url_is_refused_before_it_can_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("KONA_PASSCODE", "1")
    monkeypatch.setenv("KONA_SECRET", "s")
    monkeypatch.setenv("KONA_CAMERA_SOURCE", "rtsp")
    monkeypatch.setenv("KONA_RTSP_URL", "192.168.1.10:554/stream1")
    with pytest.raises(SettingsError, match="scheme"):
        load_settings(tmp_path / "none.env")


def test_fi_data_start_is_an_iso_date(tmp_path, monkeypatch):
    monkeypatch.setenv("KONA_PASSCODE", "123456")
    monkeypatch.setenv("KONA_SECRET", "s")
    monkeypatch.setenv("KONA_CAMERA_SOURCE", "usb")
    monkeypatch.setenv("KONA_FI_DATA_START", "2026-09-10")
    assert load_settings(tmp_path / "none.env").fi_data_start == date(2026, 9, 10)
    monkeypatch.setenv("KONA_FI_DATA_START", "09/10/2026")
    with pytest.raises(SettingsError, match="YYYY-MM-DD"):
        load_settings(tmp_path / "none.env")


def test_tunnel_settings_are_off_by_default_and_parsed_strictly(tmp_path, monkeypatch, capsys):
    for k in ("KONA_TRUSTED_PROXY_HEADER", "KONA_SECURE_COOKIES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KONA_PASSCODE", "123456")
    monkeypatch.setenv("KONA_SECRET", "s")
    s = load_settings(tmp_path / "none.env", fake_camera=True)
    assert s.trusted_proxy_header == "" and s.secure_cookies is False

    monkeypatch.setenv("KONA_TRUSTED_PROXY_HEADER", "CF-Connecting-IP")
    s = load_settings(tmp_path / "none.env", fake_camera=True)
    assert s.trusted_proxy_header == "CF-Connecting-IP"
    # A tunnel is HTTPS; say so when the cookie is still allowed over http.
    assert "KONA_SECURE_COOKIES" in capsys.readouterr().err

    monkeypatch.setenv("KONA_SECURE_COOKIES", "true")
    s = load_settings(tmp_path / "none.env", fake_camera=True)
    assert s.secure_cookies is True
    assert "KONA_SECURE_COOKIES" not in capsys.readouterr().err

    # A typo in a security switch must not silently mean "off".
    monkeypatch.setenv("KONA_SECURE_COOKIES", "yes please")
    with pytest.raises(SettingsError, match="KONA_SECURE_COOKIES"):
        load_settings(tmp_path / "none.env", fake_camera=True)


def test_log_dir_is_optional(tmp_path, monkeypatch):
    monkeypatch.delenv("KONA_LOG_DIR", raising=False)
    monkeypatch.setenv("KONA_PASSCODE", "123456")
    monkeypatch.setenv("KONA_SECRET", "s")
    assert load_settings(tmp_path / "none.env", fake_camera=True).log_dir == ""
    monkeypatch.setenv("KONA_LOG_DIR", str(tmp_path / "logs"))
    assert load_settings(tmp_path / "none.env", fake_camera=True).log_dir == str(tmp_path / "logs")
