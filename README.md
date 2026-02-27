# HQAstroCam 🔭

A fully self-contained astrophotography web application for the **Raspberry Pi HQ Camera** (IMX477), running on **Debian 13 (Trixie)** with the new **libcamera / picamera2** camera stack.

Access the live preview, adjust all camera parameters, capture photos (RAW + JPEG), record video for Lucky Imaging, manage your files, and configure networking – all from a modern, dark-themed Web UI designed to preserve your night vision.

---

## Features

| Feature | Details |
|---------|---------|
| **Live MJPEG Preview** | Real-time stream from the HQ Camera for focus and framing |
| **Photo Capture** | JPEG + optional RAW (DNG) at full sensor resolution (4056 × 3040) |
| **Video Recording** | H.264 MP4 for Lucky Imaging (5–60 fps selectable) |
| **Camera Controls** | Gain, Exposure (100 µs – 200 s), White Balance, Noise Reduction, Focus, Brightness, Contrast, Saturation, Sharpness |
| **Astrophotography Presets** | Deep Sky, Planetary/Moon, Lucky Imaging, Milky Way / Wide Field |
| **File Browser** | Download or delete captured files from the browser |
| **Network Management** | Hotspot (default), WiFi station mode, automatic Ethernet |
| **Night Vision UI** | Deep-navy theme with red accents + one-click dim mode |
| **System Info** | CPU temperature, disk space in the toolbar |

---

## Requirements

- Raspberry Pi 4 or 5 (3B+ may work)
- Raspberry Pi HQ Camera (IMX477)
- Debian 13 (Trixie) or Raspberry Pi OS (Bookworm+)
- libcamera / picamera2 stack (included in Raspberry Pi OS since 2022-04)

---

## Quick Install

```bash
git clone https://github.com/ProfessorQuantumUniverse/HQAstroCam.git
cd HQAstroCam
sudo bash install.sh
# Reboot recommended after first install:
sudo reboot
```
**NOTE:** It is possible that the installscript at step 7/7 freezes. When that happens please wait 15 seconds and simply press strg+c to exit it (It be already finished at this point).

After reboot, the Pi creates a Wi-Fi hotspot automatically if no other network is available:

| Setting | Value |
|---------|-------|
| SSID    | `HQAstroCam` |
| Password | *(randomly generated – printed at install time and stored in `/etc/astrocam.conf`)* |
| Web UI URL | `http://10.42.0.1:8080` |

The credentials are stored in `/etc/astrocam.conf` (readable only by root). You can also set them before installing:
```bash
export ASTROCAM_SSID="MySkyPi"
export ASTROCAM_HOTSPOT_PW="my_secure_password"
sudo bash install.sh
```

---

## Camera Setup

The HQ Camera uses the **IMX477** sensor. Make sure:

1. The CSI ribbon cable is properly connected (camera connector, not display)
2. After `install.sh`, the following lines are in `/boot/firmware/config.txt`:
   ```
   camera_auto_detect=1
   dtoverlay=imx477
   ```
3. Verify the camera is detected: `libcamera-hello --list-cameras`

---

## Astrophotography Presets

| Preset | Exposure | Gain | Use Case |
|--------|----------|------|----------|
| **Deep Sky** | 30 s | 8× | Nebulae, galaxies |
| **Planetary / Moon** | 10 ms | 2× | High-detail planetary imaging |
| **Lucky Imaging** | 100 ms | 4× | Video stacking for planets |
| **Milky Way** | 15 s | 16× | Wide-field, star trails |

All presets disable Auto Exposure and Auto White Balance – essential for consistent astrophotography exposures.

---

## Manual Settings

In the Settings panel you can adjust:

- **Exposure Time** – 100 µs to 200 000 000 µs (200 s) – for long deep-sky exposures
- **Analogue Gain** – 1.0 to 22.26 (IMX477 native range, equivalent to ISO 100–2226)
- **Colour Gains (R, B)** – manual white balance for accurate star colours
- **Noise Reduction** – Off / Fast / High Quality (use Off for Lucky Imaging stacking)
- **Lens Position** – manual focus (0 = infinity; increase for closer objects)
- **Brightness / Contrast / Saturation / Sharpness** – fine-tuning

---

## Network Modes

| Mode | How |
|------|-----|
| **Hotspot (default)** | Click *📡 → Enable Hotspot* or automatic if no other network is found |
| **WiFi client** | Click *📡 → Scan Networks*, select SSID, enter password |
| **Ethernet** | Plug in the cable – detected automatically by NetworkManager |

---

## Directory Structure

```
/opt/astrocam/              # Application root
├── app/
│   ├── main.py             # FastAPI routes
│   ├── camera.py           # picamera2 wrapper + mock
│   ├── network.py          # nmcli network management
│   └── static/             # Web UI (HTML + CSS + JS)
├── astrocam.service         # Systemd unit
├── install.sh               # One-shot installer
└── requirements.txt

/var/lib/astrocam/captures/  # Saved photos and videos
```

---

## Service Management

```bash
# View logs
journalctl -u astrocam -f

# Restart
sudo systemctl restart astrocam

# Stop
sudo systemctl stop astrocam

# Status
sudo systemctl status astrocam
```

---

## Development / Demo Mode

When `picamera2` is not available (e.g., on a desktop PC), the application automatically falls back to **mock/demo mode**. A synthetic star-field preview is streamed, and "captures" write placeholder files. This lets you develop and test the UI without Raspberry Pi hardware.

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

---

## License

See [LICENSE](LICENSE).
