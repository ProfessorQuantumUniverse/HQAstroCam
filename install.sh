#!/usr/bin/env bash
# =============================================================================
# HQAstroCam – Installation Script
# Tested on Debian 13 (Trixie) / Raspberry Pi OS (Bookworm/Trixie) with
# the new libcamera-based camera stack (picamera2).
# Run as root: sudo bash install.sh
# =============================================================================
set -euo pipefail

# INSTALL_ROOT: prefix for all absolute paths.
# Leave empty for a real installation; set to a temp dir for testing.
INSTALL_ROOT="${INSTALL_ROOT:-}"

APP_DIR=${INSTALL_ROOT}/opt/astrocam
DATA_DIR=${INSTALL_ROOT}/var/lib/astrocam/captures
SERVICE_FILE=${INSTALL_ROOT}/etc/systemd/system/astrocam.service
ASTROCAM_USER=astrocam
PORT=8080

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Generate a random hotspot password if not already set via environment
if [[ -z "${ASTROCAM_HOTSPOT_PW:-}" ]]; then
  # set +o pipefail inside the subshell so that tr's SIGPIPE (exit 141) –
  # caused by head closing the read end of the pipe after 16 bytes – is
  # treated as expected EOF rather than a script-aborting error.
  ASTROCAM_HOTSPOT_PW="$(set +o pipefail; tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16)"
fi
export ASTROCAM_HOTSPOT_PW

echo "============================================"
echo " HQAstroCam Installation"
echo "============================================"

# ── Root check ────────────────────────────────────────────────────────────────
# Set INSTALL_SKIP_ROOT_CHECK=1 to bypass this check (for automated testing).
if [[ $EUID -ne 0 ]] && [[ -z "${INSTALL_SKIP_ROOT_CHECK:-}" ]]; then
  echo "ERROR: This script must be run as root (sudo bash install.sh)"
  exit 1
fi

# ── System packages ───────────────────────────────────────────────────────────
echo "[1/7] Installing system packages…"
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv \
  python3-picamera2 \
  libcamera-tools libcamera-apps-lite \
  ffmpeg \
  network-manager \
  iproute2 \
  curl \
  rsync \
  libjpeg-dev \
  zlib1g-dev \
  libfreetype6-dev \
  liblcms2-dev \
  libwebp-dev \
  libharfbuzz-dev \
  libfribidi-dev \
  tcl-dev \
  tk-dev

# ── User & directories ────────────────────────────────────────────────────────
echo "[2/7] Creating user and directories…"
id -u "$ASTROCAM_USER" &>/dev/null || useradd -r -s /bin/false -G video,dialout "$ASTROCAM_USER"
# Allow astrocam to manage network via nmcli (sudoers)
cat > "${INSTALL_ROOT}/etc/sudoers.d/astrocam-network" << 'EOF'
astrocam ALL=(root) NOPASSWD: /usr/bin/nmcli
EOF
chmod 440 "${INSTALL_ROOT}/etc/sudoers.d/astrocam-network"

install -d -o "$ASTROCAM_USER" -g "$ASTROCAM_USER" -m 755 "$APP_DIR"
install -d -o "$ASTROCAM_USER" -g "$ASTROCAM_USER" -m 755 "$DATA_DIR"

# ── Copy application ──────────────────────────────────────────────────────────
echo "[3/7] Copying application files…"
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'venv' \
  "$SCRIPT_DIR/" "$APP_DIR/"
chown -R "$ASTROCAM_USER:$ASTROCAM_USER" "$APP_DIR"

# ── Python virtual environment ────────────────────────────────────────────────
echo "[4/7] Setting up Python virtual environment…"
python3 -m venv --system-site-packages "$APP_DIR/venv"
# system-site-packages lets us use apt-installed picamera2 + libcamera bindings
"$APP_DIR/venv/bin/pip" install --upgrade pip || {
  echo "ERROR: Failed to upgrade pip"
  exit 1
}
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" || {
  echo "ERROR: Failed to install Python dependencies"
  echo "Ensure build dependencies are installed:"
  echo "  sudo apt-get install -y libjpeg-dev zlib1g-dev libfreetype6-dev \\"
  echo "    liblcms2-dev libwebp-dev libharfbuzz-dev libfribidi-dev tcl-dev tk-dev"
  exit 1
}
chown -R "$ASTROCAM_USER:$ASTROCAM_USER" "$APP_DIR/venv"

# ── Enable camera in config.txt ───────────────────────────────────────────────
echo "[5/7] Enabling camera interface…"
CONFIG_FILE="${INSTALL_ROOT}/boot/firmware/config.txt"
[[ -f $CONFIG_FILE ]] || CONFIG_FILE="${INSTALL_ROOT}/boot/config.txt"
if [[ -f $CONFIG_FILE ]]; then
  if ! grep -q "^camera_auto_detect=1" "$CONFIG_FILE" && \
     ! grep -q "^dtoverlay=imx477" "$CONFIG_FILE"; then
    {
      echo ""
      echo "# HQAstroCam – Raspberry Pi HQ Camera (IMX477)"
      echo "camera_auto_detect=1"
      echo "dtoverlay=imx477"
    } >> "$CONFIG_FILE"
    echo "  ✓ Added camera overlay to $CONFIG_FILE"
  else
    echo "  ✓ Camera already configured in $CONFIG_FILE"
  fi
fi

# ── Enable NetworkManager ─────────────────────────────────────────────────────
# ── Store configuration ───────────────────────────────────────────────────────
echo "[6/7] Configuring NetworkManager…"
# Write config file with the generated/provided credentials
cat > "${INSTALL_ROOT}/etc/astrocam.conf" << CONF
ASTROCAM_SSID=${ASTROCAM_SSID:-HQAstroCam}
ASTROCAM_HOTSPOT_PW=${ASTROCAM_HOTSPOT_PW}
ASTROCAM_WIFI_IF=${ASTROCAM_WIFI_IF:-wlan0}
CONF
chmod 600 "${INSTALL_ROOT}/etc/astrocam.conf"

systemctl enable NetworkManager 2>/dev/null || true
systemctl start  NetworkManager 2>/dev/null || true

# ── Default hotspot on first boot ─────────────────────────────────────────────
# Create a NetworkManager dispatcher script that enables the hotspot
# if no other connection is active at boot
cat > "${INSTALL_ROOT}/etc/NetworkManager/dispatcher.d/90-astrocam-hotspot" << 'DISPATCHER'
#!/bin/bash
# Enable HQAstroCam hotspot when no WiFi/Ethernet connection is available
IFACE="$1"
ACTION="$2"

[[ "$ACTION" == "up" ]] && exit 0

# Load configuration
[[ -f /etc/astrocam.conf ]] && source /etc/astrocam.conf
SSID="${ASTROCAM_SSID:-HQAstroCam}"
PW="${ASTROCAM_HOTSPOT_PW:-}"
WIFI="${ASTROCAM_WIFI_IF:-wlan0}"

if [[ -z "$PW" ]]; then
    exit 0
fi

# Check if any connection is active
ACTIVE=$(nmcli -t -f TYPE,STATE dev | grep -c ':connected$' || true)
if [[ $ACTIVE -eq 0 ]]; then
    sleep 10
    ACTIVE2=$(nmcli -t -f TYPE,STATE dev | grep -c ':connected$' || true)
    if [[ $ACTIVE2 -eq 0 ]]; then
        nmcli dev wifi hotspot ifname "$WIFI" ssid "$SSID" password "$PW" 2>/dev/null || true
    fi
fi
DISPATCHER
chmod +x "${INSTALL_ROOT}/etc/NetworkManager/dispatcher.d/90-astrocam-hotspot"

# ── Systemd service ───────────────────────────────────────────────────────────
echo "[7/7] Installing and enabling systemd service…"
cp "$SCRIPT_DIR/astrocam.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable astrocam.service
systemctl restart astrocam.service

echo ""
echo "============================================"
echo " HQAstroCam installed successfully! 🔭"
echo "============================================"
echo ""
echo " Service status : systemctl status astrocam"
echo " Logs           : journalctl -u astrocam -f"
echo " Web UI         : http://<raspberry-pi-ip>:${PORT}"
echo ""
echo " Hotspot credentials (saved in /etc/astrocam.conf):"
echo "   SSID     : ${ASTROCAM_SSID:-HQAstroCam}"
echo "   Password : ${ASTROCAM_HOTSPOT_PW}"
echo "   URL      : http://10.42.0.1:${PORT}"
echo ""
echo " NOTE: A reboot is recommended to fully activate the camera."
echo "       sudo reboot"
echo ""
