"""
HQAstroCam – FastAPI main application
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

import aiofiles
from fastapi import FastAPI, HTTPException
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.camera import CONTROL_META, PRESETS, create_camera
import app.network as net

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
CAPTURES_DIR = Path(os.environ.get("ASTROCAM_CAPTURES", "/var/lib/astrocam/captures"))

# ---------------------------------------------------------------------------
# App & camera
# ---------------------------------------------------------------------------
camera = create_camera(CAPTURES_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("HQAstroCam started. Captures → %s", CAPTURES_DIR)
    yield
    camera.close()
    logger.info("HQAstroCam stopped")


app = FastAPI(title="HQAstroCam", version="1.0.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Mount static files
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = STATIC_DIR / "index.html"
    async with aiofiles.open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=await f.read())


# ---------------------------------------------------------------------------
# Live preview MJPEG stream
# ---------------------------------------------------------------------------
async def _mjpeg_generator() -> AsyncGenerator[bytes, None]:
    boundary = b"--frame"
    # get_running_loop() is safe here: an async generator runs in exactly one
    # event loop for its entire lifetime and cannot be resumed from another loop.
    loop = asyncio.get_running_loop()
    while True:
        frame = await loop.run_in_executor(None, camera.get_frame)
        if frame:
            yield (
                boundary
                + b"\r\nContent-Type: image/jpeg\r\n"
                + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                + frame
                + b"\r\n"
            )
        else:
            await asyncio.sleep(0.04)


@app.get("/stream")
async def stream() -> StreamingResponse:
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# Camera settings
# ---------------------------------------------------------------------------
@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    return JSONResponse({
        "settings":    camera.get_settings(),
        "meta":        CONTROL_META,
        "presets":     {k: {"label": v["label"]} for k, v in PRESETS.items()},
        "is_recording": camera.is_recording,
    })


class SettingsPayload(BaseModel):
    settings: dict[str, Any]


@app.post("/api/settings")
async def update_settings(payload: SettingsPayload) -> JSONResponse:
    updated = camera.apply_settings(payload.settings)
    return JSONResponse({"settings": updated})


class PresetPayload(BaseModel):
    preset: str


@app.post("/api/preset")
async def apply_preset(payload: PresetPayload) -> JSONResponse:
    try:
        updated = camera.apply_preset(payload.preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse({"settings": updated, "preset": payload.preset})


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
class CapturePayload(BaseModel):
    raw: bool = False


@app.post("/api/capture")
async def capture_photo(payload: CapturePayload) -> JSONResponse:
    try:
        files = await asyncio.get_running_loop().run_in_executor(
            None, camera.capture_photo, payload.raw
        )
    except Exception as exc:
        logger.exception("Capture failed")
        raise HTTPException(status_code=500, detail=str(exc))

    return JSONResponse({"files": [Path(f).name for f in files]})


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------
class VideoStartPayload(BaseModel):
    fps: int = 25


@app.post("/api/video/start")
async def start_video(payload: VideoStartPayload) -> JSONResponse:
    try:
        path = await asyncio.get_running_loop().run_in_executor(
            None, camera.start_video, payload.fps
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse({"file": Path(path).name, "recording": True})


@app.post("/api/video/stop")
async def stop_video() -> JSONResponse:
    try:
        path = await asyncio.get_running_loop().run_in_executor(
            None, camera.stop_video
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if path is None:
        raise HTTPException(status_code=400, detail="Not recording")
    return JSONResponse({"file": Path(path).name, "recording": False})


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------
def _file_info(p: Path) -> dict:
    stat = p.stat()
    return {
        "name":     p.name,
        "size":     stat.st_size,
        "mtime":    stat.st_mtime,
        "type":     mimetypes.guess_type(p.name)[0] or "application/octet-stream",
    }


@app.get("/api/files")
async def list_files() -> JSONResponse:
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [_file_info(f) for f in CAPTURES_DIR.iterdir() if f.is_file()],
        key=lambda x: x["mtime"],
        reverse=True,
    )
    return JSONResponse({"files": files})


@app.get("/api/files/{filename}")
async def download_file(filename: str) -> FileResponse:
    path = CAPTURES_DIR / filename
    # Prevent path traversal before any filesystem access
    try:
        path.resolve().relative_to(CAPTURES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )


@app.delete("/api/files/{filename}")
async def delete_file(filename: str) -> JSONResponse:
    path = CAPTURES_DIR / filename
    # Prevent path traversal before any filesystem access
    try:
        path.resolve().relative_to(CAPTURES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    path.unlink()
    return JSONResponse({"deleted": filename})


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
@app.get("/api/network/status")
async def network_status() -> JSONResponse:
    status = await asyncio.get_running_loop().run_in_executor(None, net.get_status)
    return JSONResponse(status)


@app.get("/api/network/scan")
async def network_scan() -> JSONResponse:
    networks = await asyncio.get_running_loop().run_in_executor(None, net.scan_wifi)
    return JSONResponse({"networks": networks})


@app.post("/api/network/hotspot")
async def network_hotspot() -> JSONResponse:
    result = await asyncio.get_running_loop().run_in_executor(None, net.enable_hotspot)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    return JSONResponse(result)


class WifiPayload(BaseModel):
    ssid: str
    password: str


@app.post("/api/network/connect")
async def network_connect(payload: WifiPayload) -> JSONResponse:
    result = await asyncio.get_running_loop().run_in_executor(
        None, net.connect_wifi, payload.ssid, payload.password
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    return JSONResponse(result)


@app.post("/api/network/disconnect")
async def network_disconnect() -> JSONResponse:
    result = await asyncio.get_running_loop().run_in_executor(
        None, net.disconnect_wifi
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# System information
# ---------------------------------------------------------------------------
@app.get("/api/system")
async def system_info() -> JSONResponse:
    info: dict[str, Any] = {}

    # CPU temperature
    try:
        def _read_temp() -> str:
            result = subprocess.run(
                ["vcgencmd", "measure_temp"],
                capture_output=True, text=True,
            )
            return result.stdout.strip()

        info["cpu_temp"] = await asyncio.get_running_loop().run_in_executor(None, _read_temp)
    except Exception:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp_mc = int(f.read().strip())
                info["cpu_temp"] = f"temp={temp_mc / 1000:.1f}'C"
        except Exception:
            info["cpu_temp"] = "N/A"

    # Disk usage
    try:
        import shutil
        total, used, free = shutil.disk_usage(str(CAPTURES_DIR.parent))
        info["disk"] = {
            "total_gb": round(total / 1e9, 1),
            "used_gb":  round(used  / 1e9, 1),
            "free_gb":  round(free  / 1e9, 1),
        }
    except Exception:
        info["disk"] = {}

    info["captures_dir"] = str(CAPTURES_DIR)
    return JSONResponse(info)
