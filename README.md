<div align="center">

# 🔭 HQAstroCam

**A fully self-contained, night-vision-friendly astrophotography web application for the Raspberry Pi HQ Camera.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.9+-yellow.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-red.svg)](https://www.raspberrypi.org/)
[![OS](https://img.shields.io/badge/OS-Debian%2013%20(Trixie)-purple.svg)](https://www.debian.org/)

</div>

---

Turn your Raspberry Pi into a powerful, standalone astrophotography rig! **HQAstroCam** is built around the modern `libcamera` and `picamera2` stack. It provides a sleek, dark-themed Web UI that protects your night vision while giving you full manual control over your camera sensor—perfect for capturing the cosmos, no matter where you are.

## Why HQAstroCam?

- **Night-Vision Preserving UI**: A deep-navy theme with red accents and a one-click dim mode ensures your eyes stay dark-adapted while observing.
- **Completely Self-Contained**: No external router needed! It automatically creates a Wi-Fi hotspot out in the field if no known network is found.
- **Raw Power**: Capture uncompressed RAW (DNG) alongside JPEG photos at full IMX477 sensor resolution (4056 × 3040).
- **Lucky Imaging**: Record high-framerate H.264 MP4 videos (5–60 fps) to stack the clearest frames of planets and the moon.
- **Full Manual Control**: Adjust Gain, Exposure (from 100 µs up to 200s!), White Balance, Focus, and more—all in real-time.
- **Astro-Presets**: 1-click tailored presets for Deep Sky, Moon/Planetary, Milky Way, and Lucky Imaging.
- **Built-in File Browser**: View, download, and delete your cosmic masterpieces directly from your web browser.

---

## Requirements

- **Hardware**: Raspberry Pi 4 or 5 *(3B+ may work but is not primarily targeted)*.
- **Camera**:[Raspberry Pi HQ Camera (IMX477)](https://www.raspberrypi.com/products/raspberry-pi-high-quality-camera/).
- **OS**: Debian 13 (Trixie) or Raspberry Pi OS (Bookworm or newer).
- **Camera Stack**: `libcamera` / `picamera2` *(included by default in Raspberry Pi OS since 2022-04)*.

---

## Quick Install

Get your rig up and running in minutes. SSH into your Raspberry Pi and run:

```bash
git clone https://github.com/ProfessorQuantumUniverse/HQAstroCam.git
cd HQAstroCam
sudo bash install.sh
```

> **⚠️ Important Note:** Sometimes the installation script may appear to freeze at step `7/7`. If this happens, wait about 15 seconds and simply press `Ctrl + C` to exit. The installation is already finished successfully at this point!

After the installation, reboot your Pi:
```bash
sudo reboot
```

---

## Connection & Network Modes

By default, if HQAstroCam cannot find a known Wi-Fi network, it will **automatically broadcast its own hotspot**. Perfect for remote dark sky locations!

| Setting | Value |
|---------|-------|
| **SSID** | `HQAstroCam` |
| **Password** | *(Randomly generated during install – securely stored in `/etc/astrocam.conf`)* |
| **Web UI URL** | `http://10.42.0.1:8080` |

### Customizing Hotspot Credentials
Want to set your own network name and password *before* installing? Just export these variables before running the install script:
```bash
export ASTROCAM_SSID="MySkyPi"
export ASTROCAM_HOTSPOT_PW="my_secure_password"
sudo bash install.sh
```

### Other Network Modes
- **WiFi Client**: Connect to your home router. Click *📡 → Scan Networks* in the Web UI, select your SSID, and enter the password.
- **Ethernet**: Simply plug in a cable. It will be detected automatically by NetworkManager.

---

## 📷 Camera Setup (IMX477)

To ensure your Pi recognizes the HQ Camera properly:
1. Ensure the CSI ribbon cable is firmly connected to the **camera port** (not the display port).
2. Check your `/boot/firmware/config.txt`. The installer should have ensured the following lines are present:
   ```ini
   camera_auto_detect=1
   dtoverlay=imx477
   ```
3. Verify detection by running: `libcamera-hello --list-cameras`

---

## Astrophotography Presets

Forget about messing with tricky settings in the dark. Use our built-in starting points! *(Note: Auto Exposure and Auto White Balance are deliberately disabled for these presets to ensure consistent astrophotography results).*

| Preset | Exposure | Gain | Perfect For... |
|--------|----------|------|----------------|
| **Deep Sky** | 30 s | 8× | Nebulae, faint galaxies, star clusters |
| **Planetary / Moon** | 10 ms | 2× | High-detail craters, Jupiter, Saturn |
| **Lucky Imaging** | 100 ms | 4× | Video stacking to beat atmospheric turbulence |
| **Milky Way** | 15 s | 16× | Wide-field nightscapes, star trails |

### Manual Overrides
Need fine-tuning? The **Settings Panel** lets you manually tweak:
- **Exposure Time**: 100 µs up to a massive 200,000,000 µs (200 seconds)
- **Analogue Gain**: 1.0 to 22.26 (Native IMX477 range, ISO 100–2226 equivalent)
- **Color Gains (R, B)**: Absolute control over white balance to get accurate star colors
- **Noise Reduction**: Off / Fast / High Quality *(Pro-tip: Turn OFF for Lucky Imaging stacking)*
- **Lens Position**: Manual focus fine-tuning (0 = infinity)
- **Image Adjustments**: Brightness, Contrast, Saturation, Sharpness

---

## Development & Demo Mode

No Raspberry Pi at hand? No problem! HQAstroCam comes with a built-in **Demo Mode**. 

If `picamera2` is unavailable (e.g., when running on a standard Windows/Mac/Linux desktop PC), the app automatically falls back to a mock mode. It streams a synthetic star-field and writes placeholder files for captures, allowing you to develop or test the UI without hardware!

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### Directory Structure
```text
/opt/astrocam/                # Application root
├── app/
│   ├── main.py               # FastAPI backend routes
│   ├── camera.py             # picamera2 wrapper & demo mock fallback
│   ├── network.py            # nmcli network management
│   └── static/               # Beautiful Web UI (HTML, CSS, JS)
├── astrocam.service          # Systemd unit file
├── install.sh                # One-shot installer script
└── requirements.txt

/var/lib/astrocam/captures/   # Where your cosmic masterpieces are saved
```

---

## Service Management

The app runs in the background as a systemd service (`astrocam.service`). You can manage it easily via the command line:

```bash
# View live logs
journalctl -u astrocam -f

# Restart the service
sudo systemctl restart astrocam

# Stop the service
sudo systemctl stop astrocam

# Check status
sudo systemctl status astrocam
```

---

## 📜 License

This project is open-source and licensed under the[GPL-3.0 License](LICENSE).
