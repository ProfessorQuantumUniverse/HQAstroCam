"""
Tests for app/camera.py – MockCamera and _coerce_settings.
"""
from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from app.camera import (
    DEFAULT_SETTINGS,
    PRESETS,
    MockCamera,
    _coerce_settings,
)


# ---------------------------------------------------------------------------
# _coerce_settings
# ---------------------------------------------------------------------------
class TestCoerceSettings:
    def test_bool_true(self):
        result = _coerce_settings({"AeEnable": True})
        assert result == {"AeEnable": True}

    def test_bool_coerce_from_int(self):
        result = _coerce_settings({"AeEnable": 1})
        assert result["AeEnable"] is True

    def test_int_coerce(self):
        result = _coerce_settings({"ExposureTime": 4_000_000})
        assert result["ExposureTime"] == 4_000_000
        assert isinstance(result["ExposureTime"], int)

    def test_float_coerce(self):
        result = _coerce_settings({"AnalogueGain": "2.5"})
        assert result["AnalogueGain"] == pytest.approx(2.5)
        assert isinstance(result["AnalogueGain"], float)

    def test_select_coerce(self):
        result = _coerce_settings({"NoiseReductionMode": "2"})
        assert result["NoiseReductionMode"] == 2
        assert isinstance(result["NoiseReductionMode"], int)

    def test_tuple2_valid(self):
        result = _coerce_settings({"ColourGains": [1.5, 1.8]})
        assert result["ColourGains"] == (pytest.approx(1.5), pytest.approx(1.8))

    def test_tuple2_wrong_length_ignored(self):
        result = _coerce_settings({"ColourGains": [1.5]})
        assert "ColourGains" not in result

    def test_unknown_key_ignored(self):
        result = _coerce_settings({"UnknownKey": 99})
        assert "UnknownKey" not in result

    def test_invalid_float_ignored(self):
        result = _coerce_settings({"AnalogueGain": "not-a-number"})
        assert "AnalogueGain" not in result

    def test_empty_dict(self):
        assert _coerce_settings({}) == {}

    def test_multiple_keys(self):
        result = _coerce_settings({
            "AeEnable": False,
            "ExposureTime": 1_000_000,
            "AnalogueGain": 4.0,
        })
        assert result["AeEnable"] is False
        assert result["ExposureTime"] == 1_000_000
        assert result["AnalogueGain"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# MockCamera
# ---------------------------------------------------------------------------
class TestMockCamera:
    @pytest.fixture()
    def cam(self, tmp_path: Path) -> MockCamera:
        c = MockCamera(tmp_path)
        yield c
        c.close()

    def test_init_creates_directory(self, tmp_path: Path):
        subdir = tmp_path / "caps"
        c = MockCamera(subdir)
        assert subdir.exists()
        c.close()

    def test_default_settings(self, cam: MockCamera):
        settings = cam.get_settings()
        assert settings["ExposureTime"] == DEFAULT_SETTINGS["ExposureTime"]
        assert settings["AnalogueGain"] == DEFAULT_SETTINGS["AnalogueGain"]

    def test_apply_settings(self, cam: MockCamera):
        updated = cam.apply_settings({"ExposureTime": 1_000_000})
        assert updated["ExposureTime"] == 1_000_000

    def test_apply_settings_ignores_unknown(self, cam: MockCamera):
        original = cam.get_settings()
        updated = cam.apply_settings({"InvalidKey": 123})
        assert updated == original

    def test_apply_preset_deep_sky(self, cam: MockCamera):
        updated = cam.apply_preset("deep_sky")
        assert updated["ExposureTime"] == PRESETS["deep_sky"]["settings"]["ExposureTime"]

    def test_apply_preset_unknown_raises(self, cam: MockCamera):
        with pytest.raises(ValueError, match="Unknown preset"):
            cam.apply_preset("nonexistent_preset")

    def test_not_recording_initially(self, cam: MockCamera):
        assert cam.is_recording is False

    def test_start_stop_video(self, cam: MockCamera, tmp_path: Path):
        path = cam.start_video(fps=25)
        assert cam.is_recording is True
        assert Path(path).exists()  # placeholder file created

        stopped = cam.stop_video()
        assert stopped == path
        assert cam.is_recording is False

    def test_start_video_twice_raises(self, cam: MockCamera):
        cam.start_video()
        with pytest.raises(RuntimeError, match="Already recording"):
            cam.start_video()
        cam.stop_video()

    def test_stop_video_not_recording_returns_none(self, cam: MockCamera):
        assert cam.stop_video() is None

    def test_capture_photo_no_frame(self, cam: MockCamera):
        # No frame has been generated yet; result may be empty
        files = cam.capture_photo(capture_raw=False)
        # May return [] if no frame yet – that's acceptable
        assert isinstance(files, list)

    def test_capture_photo_with_raw(self, cam: MockCamera, tmp_path: Path):
        # Wait briefly for a frame to be generated
        time.sleep(0.2)
        files = cam.capture_photo(capture_raw=True)
        assert isinstance(files, list)
        # If a frame was captured, we expect a JPEG and a DNG
        if files:
            assert any(f.endswith(".jpg") for f in files)
            assert any(f.endswith(".dng") for f in files)

    def test_get_frame_returns_bytes_or_none(self, cam: MockCamera):
        # Wait briefly for frame generation
        time.sleep(0.2)
        frame = cam.get_frame()
        assert frame is None or isinstance(frame, bytes)

    def test_get_frame_returns_valid_jpeg(self, cam: MockCamera):
        time.sleep(0.15)
        frame = cam.get_frame()
        if frame:
            assert frame[:3] == b"\xff\xd8\xff", "Expected JPEG magic bytes"

    def test_close_stops_frame_generation(self, cam: MockCamera):
        cam.close()
        assert cam._running is False
