"""
Tests for app/main.py – FastAPI endpoints using TestClient.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _patch_captures_dir(tmp_path: Path, monkeypatch):
    """Redirect ASTROCAM_CAPTURES to a temp dir for all tests."""
    monkeypatch.setenv("ASTROCAM_CAPTURES", str(tmp_path / "captures"))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    """Return a TestClient with a MockCamera."""
    monkeypatch.setenv("ASTROCAM_CAPTURES", str(tmp_path / "captures"))

    # Re-import main so the patched env var takes effect
    import importlib
    import app.main as main_mod
    importlib.reload(main_mod)

    with TestClient(main_mod.app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# /api/settings
# ---------------------------------------------------------------------------
class TestSettings:
    def test_get_settings_returns_expected_keys(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "settings" in data
        assert "meta" in data
        assert "presets" in data
        assert "is_recording" in data

    def test_post_settings_updates_exposure(self, client):
        resp = client.post("/api/settings", json={"settings": {"ExposureTime": 2_000_000}})
        assert resp.status_code == 200
        assert resp.json()["settings"]["ExposureTime"] == 2_000_000

    def test_post_settings_ignores_unknown_key(self, client):
        original = client.get("/api/settings").json()["settings"]
        client.post("/api/settings", json={"settings": {"UnknownKey": 99}})
        updated = client.get("/api/settings").json()["settings"]
        assert updated == original


# ---------------------------------------------------------------------------
# /api/preset
# ---------------------------------------------------------------------------
class TestPreset:
    def test_apply_valid_preset(self, client):
        resp = client.post("/api/preset", json={"preset": "deep_sky"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["preset"] == "deep_sky"
        assert "settings" in data

    def test_apply_invalid_preset_returns_400(self, client):
        resp = client.post("/api/preset", json={"preset": "nonexistent"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/capture
# ---------------------------------------------------------------------------
class TestCapture:
    def test_capture_photo(self, client, tmp_path):
        resp = client.post("/api/capture", json={"raw": False})
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data

    def test_capture_photo_with_raw(self, client):
        resp = client.post("/api/capture", json={"raw": True})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/video
# ---------------------------------------------------------------------------
class TestVideo:
    def test_start_stop_video(self, client):
        resp = client.post("/api/video/start", json={"fps": 25})
        assert resp.status_code == 200
        data = resp.json()
        assert data["recording"] is True
        assert "file" in data

        resp2 = client.post("/api/video/stop")
        assert resp2.status_code == 200
        assert resp2.json()["recording"] is False

    def test_stop_video_not_recording_returns_400(self, client):
        resp = client.post("/api/video/stop")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/files
# ---------------------------------------------------------------------------
class TestFiles:
    def test_list_files_empty(self, client):
        resp = client.get("/api/files")
        assert resp.status_code == 200
        assert resp.json()["files"] == []

    def test_list_files_with_file(self, client, tmp_path):
        import app.main as main_mod
        caps_dir = main_mod.CAPTURES_DIR
        caps_dir.mkdir(parents=True, exist_ok=True)
        (caps_dir / "test.jpg").write_bytes(b"fake-jpeg")

        resp = client.get("/api/files")
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(f["name"] == "test.jpg" for f in files)

    def test_download_file(self, client, tmp_path):
        import app.main as main_mod
        caps_dir = main_mod.CAPTURES_DIR
        caps_dir.mkdir(parents=True, exist_ok=True)
        (caps_dir / "photo.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        resp = client.get("/api/files/photo.jpg")
        assert resp.status_code == 200

    def test_download_nonexistent_returns_404(self, client):
        resp = client.get("/api/files/nosuchfile.jpg")
        assert resp.status_code == 404

    def test_download_path_traversal_returns_403(self, client):
        resp = client.get("/api/files/../etc/passwd")
        assert resp.status_code in (403, 404)

    def test_delete_file(self, client, tmp_path):
        import app.main as main_mod
        caps_dir = main_mod.CAPTURES_DIR
        caps_dir.mkdir(parents=True, exist_ok=True)
        (caps_dir / "delete_me.jpg").write_bytes(b"data")

        resp = client.delete("/api/files/delete_me.jpg")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "delete_me.jpg"
        assert not (caps_dir / "delete_me.jpg").exists()

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/files/nosuchfile.jpg")
        assert resp.status_code == 404

    def test_delete_path_traversal_returns_403(self, client):
        resp = client.delete("/api/files/../etc/passwd")
        assert resp.status_code in (403, 404)


# ---------------------------------------------------------------------------
# /api/system
# ---------------------------------------------------------------------------
class TestSystem:
    def test_system_info(self, client):
        resp = client.get("/api/system")
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu_temp" in data
        assert "disk" in data
        assert "captures_dir" in data


# ---------------------------------------------------------------------------
# /api/network  (mocked – no nmcli on CI)
# ---------------------------------------------------------------------------
class TestNetwork:
    def test_network_status(self, client):
        with patch("app.network._run", return_value=(1, "", "nmcli not found")):
            resp = client.get("/api/network/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data

    def test_network_scan(self, client):
        with patch("app.network._run", return_value=(1, "", "nmcli not found")):
            resp = client.get("/api/network/scan")
        assert resp.status_code == 200
        assert "networks" in resp.json()
