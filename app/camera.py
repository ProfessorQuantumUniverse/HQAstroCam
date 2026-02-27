"""
HQAstroCam – Camera management module
Uses picamera2 (new libcamera-based stack) for Raspberry Pi HQ Camera.
Falls back to a mock implementation when running without hardware.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import picamera2; fall back to mock on non-Pi hardware
# ---------------------------------------------------------------------------
try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder, MJPEGEncoder
    from picamera2.outputs import FileOutput, FfmpegOutput
    PICAMERA2_AVAILABLE = True
    logger.info("picamera2 loaded successfully")
except ImportError:
    PICAMERA2_AVAILABLE = False
    logger.warning("picamera2 not available – running in mock/demo mode")


# ---------------------------------------------------------------------------
# Streaming output helper (thread-safe frame buffer)
# ---------------------------------------------------------------------------
class StreamingOutput(io.BufferedIOBase):
    """Thread-safe buffer used by MJPEGEncoder to deliver preview frames."""

    def __init__(self) -> None:
        self.frame: bytes | None = None
        self._condition = threading.Condition()

    def write(self, buf: bytes) -> int:  # type: ignore[override]
        with self._condition:
            self.frame = bytes(buf)
            self._condition.notify_all()
        return len(buf)

    def wait_for_frame(self, timeout: float = 2.0) -> bytes | None:
        with self._condition:
            self._condition.wait(timeout)
            return self.frame


# ---------------------------------------------------------------------------
# Default astrophotography camera settings
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, Any] = {
    "AeEnable": False,          # Manual exposure
    "AwbEnable": False,         # Manual white balance
    "ExposureTime": 4_000_000,  # 4 seconds (µs)
    "AnalogueGain": 4.0,        # ~ISO 400 equivalent
    "ColourGains": (1.5, 1.5),  # Neutral colour balance
    "Brightness": 0.0,
    "Contrast": 1.0,
    "Saturation": 1.0,
    "Sharpness": 1.0,
    "NoiseReductionMode": 2,    # High-quality noise reduction
}

# Human-readable metadata about each control for the UI
CONTROL_META: dict[str, dict] = {
    "AeEnable":          {"label": "Auto Exposure",        "type": "bool"},
    "AwbEnable":         {"label": "Auto White Balance",   "type": "bool"},
    "ExposureTime":      {"label": "Exposure Time (µs)",   "type": "int",
                          "min": 100, "max": 200_000_000, "step": 100,
                          "hint": "100 µs – 200 s"},
    "AnalogueGain":      {"label": "Analogue Gain",        "type": "float",
                          "min": 1.0, "max": 22.26,        "step": 0.1},
    "ColourGains":       {"label": "Colour Gains (R, B)",  "type": "tuple2",
                          "min": 0.0, "max": 32.0,         "step": 0.1},
    "Brightness":        {"label": "Brightness",           "type": "float",
                          "min": -1.0, "max": 1.0,         "step": 0.05},
    "Contrast":          {"label": "Contrast",             "type": "float",
                          "min": 0.0, "max": 32.0,         "step": 0.1},
    "Saturation":        {"label": "Saturation",           "type": "float",
                          "min": 0.0, "max": 32.0,         "step": 0.1},
    "Sharpness":         {"label": "Sharpness",            "type": "float",
                          "min": 0.0, "max": 16.0,         "step": 0.1},
    "NoiseReductionMode": {"label": "Noise Reduction",     "type": "select",
                           "options": {0: "Off", 1: "Fast", 2: "High Quality",
                                       3: "Minimal", 4: "ZSL"}},
    "AfMode":            {"label": "AF Mode",              "type": "select",
                          "options": {0: "Manual", 1: "Auto", 2: "Continuous"}},
    "LensPosition":      {"label": "Lens Position (focus)", "type": "float",
                          "min": 0.0, "max": 32.0,          "step": 0.1,
                          "hint": "0 = infinity, higher = closer"},
}

# Astrophotography presets
PRESETS: dict[str, dict] = {
    "deep_sky": {
        "label": "Deep Sky (Long Exposure)",
        "settings": {
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": 30_000_000,   # 30 s
            "AnalogueGain": 8.0,
            "ColourGains": (1.5, 1.5),
            "NoiseReductionMode": 2,
            "Contrast": 1.0,
            "Saturation": 1.2,
        },
    },
    "planetary": {
        "label": "Planetary / Moon (Short Exposure)",
        "settings": {
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": 10_000,        # 10 ms
            "AnalogueGain": 2.0,
            "ColourGains": (1.5, 1.5),
            "NoiseReductionMode": 1,
            "Contrast": 1.2,
            "Saturation": 1.0,
        },
    },
    "lucky_imaging": {
        "label": "Lucky Imaging (Video Burst)",
        "settings": {
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": 100_000,       # 100 ms
            "AnalogueGain": 4.0,
            "ColourGains": (1.5, 1.5),
            "NoiseReductionMode": 0,       # Off – keep raw signal
            "Contrast": 1.0,
            "Saturation": 0.8,
        },
    },
    "milky_way": {
        "label": "Milky Way / Wide Field",
        "settings": {
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": 15_000_000,    # 15 s
            "AnalogueGain": 16.0,
            "ColourGains": (1.8, 1.4),
            "NoiseReductionMode": 2,
            "Contrast": 1.1,
            "Saturation": 1.3,
        },
    },
}


# ---------------------------------------------------------------------------
# Real camera implementation
# ---------------------------------------------------------------------------
class RealCamera:
    """Wraps picamera2 for astrophotography use."""

    PREVIEW_SIZE = (1280, 720)
    CAPTURE_SIZE = (4056, 3040)   # HQ Camera full resolution
    VIDEO_SIZE   = (1920, 1080)

    def __init__(self, capture_dir: Path) -> None:
        self.capture_dir = capture_dir
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._streaming_output: StreamingOutput | None = None
        self._recording = False
        self._recording_path: str | None = None
        self._settings: dict[str, Any] = dict(DEFAULT_SETTINGS)

        self._cam = Picamera2()
        self._configure_preview()
        self._cam.start()
        logger.info("Camera started (real mode)")

    def _configure_preview(self) -> None:
        cfg = self._cam.create_video_configuration(
            main={"size": self.PREVIEW_SIZE, "format": "RGB888"},
            lores={"size": (640, 360),      "format": "YUV420"},
            controls=self._settings,
        )
        self._cam.configure(cfg)
        self._streaming_output = StreamingOutput()
        self._mjpeg_encoder = MJPEGEncoder()
        self._cam.start_recording(
            self._mjpeg_encoder,
            FileOutput(self._streaming_output),
            name="lores",
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------
    def get_frame(self) -> bytes | None:
        if self._streaming_output:
            return self._streaming_output.wait_for_frame()
        return None

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        return dict(self._settings)

    def apply_settings(self, new: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            # Validate and coerce types
            coerced = _coerce_settings(new)
            self._settings.update(coerced)
            self._cam.set_controls(coerced)
        return dict(self._settings)

    def apply_preset(self, preset_name: str) -> dict[str, Any]:
        if preset_name not in PRESETS:
            raise ValueError(f"Unknown preset: {preset_name}")
        return self.apply_settings(PRESETS[preset_name]["settings"])

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------
    def capture_photo(self, capture_raw: bool = False) -> list[str]:
        """Capture JPEG (and optionally DNG raw). Returns list of file paths."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        files: list[str] = []

        with self._lock:
            # Merken, ob ein H264-Video lief, um es später neu zu starten
            was_recording = self._recording
            
            # WICHTIG: *Immer* stop_recording() aufrufen, um den MJPEG-Preview-Encoder 
            # und ggf. laufende Videos zu stoppen! Sonst hängt switch_mode()!
            self._cam.stop_recording()

            still_cfg = self._cam.create_still_configuration(
                main={"size": self.CAPTURE_SIZE},
                raw={"size": self._cam.sensor_resolution} if capture_raw else None,
            )
            self._cam.switch_mode(still_cfg)
            
            # WICHTIG: Nach einem switch_mode muss die Kamera-Pipeline gestartet werden,
            # sonst wartet capture_file() ewig auf einen Frame und wirft einen Fehler.
            self._cam.start()

            jpeg_path = str(self.capture_dir / f"photo_{timestamp}.jpg")
            if capture_raw:
                raw_path = str(self.capture_dir / f"photo_{timestamp}.dng")
                self._cam.capture_file(jpeg_path, raw=raw_path)
                files.append(raw_path)
            else:
                self._cam.capture_file(jpeg_path)

            files.insert(0, jpeg_path)

            # Switch back to preview mode
            self._configure_preview()
            # Nach configure_preview() sicherstellen, dass die Kamera wieder läuft
            self._cam.start()
            
            if was_recording:
                self._start_recording_internal()

        return files
    # ------------------------------------------------------------------
    # Video
    # ------------------------------------------------------------------
    def start_video(self, fps: int = 25) -> str:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = str(self.capture_dir / f"video_{timestamp}.mp4")
        with self._lock:
            if self._recording:
                raise RuntimeError("Already recording")
            self._recording_path = path
            self._start_recording_internal()
        return path

    def _start_recording_internal(self) -> None:
        vid_cfg = self._cam.create_video_configuration(
            main={"size": self.VIDEO_SIZE},
        )
        self._cam.configure(vid_cfg)
        encoder = H264Encoder(bitrate=10_000_000)
        self._cam.start_recording(encoder, FfmpegOutput(self._recording_path))
        self._recording = True

    def stop_video(self) -> str | None:
        with self._lock:
            if not self._recording:
                return None
            self._cam.stop_recording()
            self._recording = False
            path = self._recording_path
            self._recording_path = None
            # Restore preview
            self._configure_preview()
        return path

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._cam.stop_recording()
        except Exception:
            pass
        try:
            self._cam.stop()
        except Exception:
            pass
        logger.info("Camera closed")


# ---------------------------------------------------------------------------
# Mock camera implementation (for development / CI)
# ---------------------------------------------------------------------------
class MockCamera:
    """Simulates the camera when picamera2 is not available."""

    def __init__(self, capture_dir: Path) -> None:
        self.capture_dir = capture_dir
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._recording = False
        self._recording_path: str | None = None
        self._frame_thread: threading.Thread | None = None
        self._running = True
        self._current_frame: bytes | None = None
        self._frame_lock = threading.Condition()
        self._frame_thread = threading.Thread(
            target=self._generate_frames, daemon=True
        )
        self._frame_thread.start()
        logger.info("Camera started (mock/demo mode)")

    def _generate_frames(self) -> None:
        """Generate synthetic preview frames for demo mode."""
        try:
            from PIL import Image, ImageDraw
            import math
            import random
            rng = random.Random(42)
            frame_num = 0
            while self._running:
                width, height = 1280, 720
                # Draw a star-field-like frame
                img = Image.new("RGB", (width, height), (2, 2, 12))
                draw = ImageDraw.Draw(img)

                # Simulated stars
                for _ in range(300):
                    x = rng.randint(0, width - 1)
                    y = rng.randint(0, height - 1)
                    brightness = rng.randint(100, 255)
                    size = rng.choice([1, 1, 1, 2, 2, 3])
                    draw.ellipse(
                        [x - size, y - size, x + size, y + size],
                        fill=(brightness, brightness, brightness),
                    )

                # Twinkling star
                t = frame_num / 25.0
                cx, cy = 640, 360
                glow = int(128 + 127 * math.sin(t * 2))
                for r in range(12, 0, -3):
                    alpha = max(0, min(255, glow - r * 15))
                    draw.ellipse(
                        [cx - r, cy - r, cx + r, cy + r],
                        fill=(alpha, alpha // 2, 0),
                    )

                # Overlay text
                draw.text(
                    (10, 10),
                    f"HQAstroCam – DEMO MODE  |  "
                    f"Exp: {self._settings.get('ExposureTime', 0) / 1e6:.3f}s  "
                    f"Gain: {self._settings.get('AnalogueGain', 0):.1f}",
                    fill=(200, 50, 50),
                )
                draw.text(
                    (10, 30),
                    "Connect Raspberry Pi HQ Camera to activate",
                    fill=(150, 50, 50),
                )

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                frame = buf.getvalue()

                with self._frame_lock:
                    self._current_frame = frame
                    self._frame_lock.notify_all()

                frame_num += 1
                time.sleep(0.04)  # ~25 fps
        except Exception as exc:
            logger.error("Mock frame generation error: %s", exc)

    def get_frame(self) -> bytes | None:
        with self._frame_lock:
            self._frame_lock.wait(2.0)
            return self._current_frame

    def get_settings(self) -> dict[str, Any]:
        return dict(self._settings)

    def apply_settings(self, new: dict[str, Any]) -> dict[str, Any]:
        self._settings.update(_coerce_settings(new))
        return dict(self._settings)

    def apply_preset(self, preset_name: str) -> dict[str, Any]:
        if preset_name not in PRESETS:
            raise ValueError(f"Unknown preset: {preset_name}")
        return self.apply_settings(PRESETS[preset_name]["settings"])

    def capture_photo(self, capture_raw: bool = False) -> list[str]:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        files: list[str] = []
        frame = self._current_frame
        if frame:
            jpeg_path = str(self.capture_dir / f"photo_{timestamp}.jpg")
            with open(jpeg_path, "wb") as f:
                f.write(frame)
            files.append(jpeg_path)
        if capture_raw:
            # Write a placeholder DNG (real DNG requires picamera2)
            raw_path = str(self.capture_dir / f"photo_{timestamp}.dng")
            with open(raw_path, "wb") as f:
                f.write(b"DNG_PLACEHOLDER_DEMO")
            files.append(raw_path)
        return files

    def start_video(self, fps: int = 25) -> str:
        if self._recording:
            raise RuntimeError("Already recording")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = str(self.capture_dir / f"video_{timestamp}.mp4")
        self._recording = True
        self._recording_path = path
        # Create an empty placeholder file
        Path(path).touch()
        return path

    def stop_video(self) -> str | None:
        if not self._recording:
            return None
        self._recording = False
        path = self._recording_path
        self._recording_path = None
        return path

    @property
    def is_recording(self) -> bool:
        return self._recording

    def close(self) -> None:
        self._running = False
        logger.info("Mock camera closed")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_camera(capture_dir: Path) -> RealCamera | MockCamera:
    if PICAMERA2_AVAILABLE:
        try:
            return RealCamera(capture_dir)
        except Exception as exc:
            logger.warning(
                "Failed to open real camera (%s) – falling back to mock", exc
            )
    return MockCamera(capture_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce_settings(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce incoming JSON types to the types picamera2 expects."""
    out: dict[str, Any] = {}
    for key, val in raw.items():
        meta = CONTROL_META.get(key)
        if meta is None:
            continue  # ignore unknown keys
        t = meta["type"]
        try:
            if t == "bool":
                out[key] = bool(val)
            elif t == "int":
                out[key] = int(val)
            elif t == "float":
                out[key] = float(val)
            elif t == "select":
                out[key] = int(val)
            elif t == "tuple2":
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    out[key] = (float(val[0]), float(val[1]))
        except (ValueError, TypeError) as exc:
            logger.warning("Could not coerce setting %s=%r: %s", key, val, exc)
    return out
