"""Capabilities are data, so the wrong data means dead buttons on a real
camera. These pin the per-model answers and the cautious fallback."""

import pytest

from kona_tracker.camera.capabilities import (
    FAKE,
    TAPO_FIXED,
    TAPO_PAN_TILT,
    USB,
    Capabilities,
    for_model,
)
from kona_tracker.camera.control import ControlUnsupported, FakeControl, NoControl


def test_the_c120_is_fixed_and_the_pan_tilt_models_are_not():
    assert TAPO_FIXED.ptz is False and TAPO_FIXED.presets is False
    assert TAPO_FIXED.night_vision and TAPO_FIXED.privacy and TAPO_FIXED.alarm
    assert TAPO_PAN_TILT.ptz and TAPO_PAN_TILT.presets
    for model in ("c120", "C120", " c120 "):
        assert for_model(model, "rtsp") is TAPO_FIXED
    for model in ("c210", "c220", "c225"):
        assert for_model(model, "rtsp") is TAPO_PAN_TILT


def test_two_way_talk_is_off_everywhere():
    """Tapo is ONVIF Profile S; the audio backchannel is Profile T. If this
    ever flips, it must be because someone proved it on real hardware."""
    for caps in (TAPO_FIXED, TAPO_PAN_TILT, USB, FAKE, Capabilities()):
        assert caps.talk is False


def test_unknown_models_fall_back_to_the_cautious_reading():
    assert for_model("", "rtsp") is USB
    assert for_model("some-new-camera", "rtsp") is USB
    assert for_model("", "fake") is FAKE
    assert for_model("", "usb") is USB


def test_no_control_refuses_loudly_rather_than_no_opping():
    c = NoControl(TAPO_FIXED)
    assert c.position() == (0.0, 0.0)
    with pytest.raises(ControlUnsupported, match="pan or tilt"):
        c.move(pan=0.5)
    with pytest.raises(ControlUnsupported, match="presets"):
        c.goto_preset(1)


def test_fake_control_moves_clamps_and_jumps_to_presets():
    c = FakeControl()
    assert c.move(pan=0.3, tilt=-0.2) == (0.3, -0.2)
    assert c.move(pan=9, tilt=9) == (1.0, 1.0)  # clamped, not wrapped
    assert c.move(pan=-9, tilt=-9) == (-1.0, -1.0)
    assert c.goto_preset(3) == FakeControl.PRESETS[3]
    with pytest.raises(ControlUnsupported, match="no preset"):
        c.goto_preset(99)


def test_a_fake_control_without_ptz_still_refuses():
    c = FakeControl(Capabilities())
    with pytest.raises(ControlUnsupported):
        c.move(pan=0.1)
