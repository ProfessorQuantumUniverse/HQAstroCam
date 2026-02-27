#!/usr/bin/env bats
# =============================================================================
# Tests for install.sh
#
# Requires: bats (https://github.com/bats-core/bats-core)
# Install:  npm install -g bats
# Run:      bats tests/test_install.sh
#
# Strategy
# --------
# Each test runs inside an isolated temp dir (FAKE_ROOT) that mimics the
# directory tree a real Debian/Pi system would have.  All external commands
# that require root or real hardware (apt-get, useradd, rsync, python3,
# systemctl, install, chown) are replaced by lightweight stub scripts placed
# at the front of $PATH.  Two env-var hooks added to install.sh enable this:
#
#   INSTALL_ROOT            – prefix prepended to every absolute path the
#                             script writes, keeping writes inside FAKE_ROOT.
#   INSTALL_SKIP_ROOT_CHECK – bypass the EUID guard (we are not root in CI).
# =============================================================================

INSTALL_SH="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/install.sh"

# ---------------------------------------------------------------------------
# setup / teardown
# ---------------------------------------------------------------------------
setup() {
  FAKE_ROOT="$(mktemp -d)"
  FAKE_BIN="$(mktemp -d)"

  # Pre-create the directories that exist on a real Debian / Pi OS system
  mkdir -p \
    "${FAKE_ROOT}/etc/sudoers.d" \
    "${FAKE_ROOT}/etc/NetworkManager/dispatcher.d" \
    "${FAKE_ROOT}/etc/systemd/system" \
    "${FAKE_ROOT}/opt/astrocam" \
    "${FAKE_ROOT}/var/lib/astrocam/captures"

  # ── apt-get stub ────────────────────────────────────────────────────────
  printf '#!/bin/bash\nexit 0\n' > "${FAKE_BIN}/apt-get"

  # ── useradd stub ────────────────────────────────────────────────────────
  printf '#!/bin/bash\nexit 0\n' > "${FAKE_BIN}/useradd"

  # ── id stub: simulates the astrocam user not yet existing ───────────────
  # The script does: id -u "$ASTROCAM_USER" &>/dev/null || useradd ...
  # Exiting 1 causes useradd to be called (normal first-time install path).
  printf '#!/bin/bash\nexit 1\n' > "${FAKE_BIN}/id"

  # ── rsync stub ──────────────────────────────────────────────────────────
  printf '#!/bin/bash\nexit 0\n' > "${FAKE_BIN}/rsync"

  # ── chown stub ──────────────────────────────────────────────────────────
  printf '#!/bin/bash\nexit 0\n' > "${FAKE_BIN}/chown"

  # ── systemctl stub ──────────────────────────────────────────────────────
  printf '#!/bin/bash\nexit 0\n' > "${FAKE_BIN}/systemctl"

  # ── install stub ────────────────────────────────────────────────────────
  # Handles "install -d -o <user> -g <group> -m <mode> <dir>" by creating
  # the requested directories while ignoring ownership/permission flags that
  # would require root.
  cat > "${FAKE_BIN}/install" << 'STUB'
#!/bin/bash
dirs=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d)       shift ;;
    -o|-g|-m) shift; shift ;;
    *)        dirs+=("$1"); shift ;;
  esac
done
for dir in "${dirs[@]}"; do
  mkdir -p "$dir"
done
STUB

  # ── python3 stub ────────────────────────────────────────────────────────
  # Handles "python3 -m venv [--system-site-packages] <path>".
  # Creates a minimal fake venv so that subsequent pip calls succeed.
  cat > "${FAKE_BIN}/python3" << 'STUB'
#!/bin/bash
if [[ "$1" == "-m" && "$2" == "venv" ]]; then
  venv_path="${@: -1}"
  mkdir -p "${venv_path}/bin"
  printf '#!/bin/bash\nexit 0\n' > "${venv_path}/bin/pip"
  chmod +x "${venv_path}/bin/pip"
fi
exit 0
STUB

  chmod +x "${FAKE_BIN}"/*

  export PATH="${FAKE_BIN}:${PATH}"
  export INSTALL_ROOT="${FAKE_ROOT}"
  export INSTALL_SKIP_ROOT_CHECK=1
  unset ASTROCAM_HOTSPOT_PW ASTROCAM_SSID ASTROCAM_WIFI_IF
}

teardown() {
  rm -rf "${FAKE_ROOT}" "${FAKE_BIN}"
}

# ---------------------------------------------------------------------------
# Helper: run the full install script, capturing stdout+stderr
# ---------------------------------------------------------------------------
run_install() {
  # shellcheck disable=SC2030,SC2031
  run bash "${INSTALL_SH}" "$@"
}

# ===========================================================================
# 1. Root check
# ===========================================================================
@test "root check: exits 1 with error message when not root and check is active" {
  # Run without INSTALL_SKIP_ROOT_CHECK; since we are not root, the script
  # must exit 1 with an informative error message.
  run bash -c "
    unset INSTALL_SKIP_ROOT_CHECK
    export INSTALL_ROOT='${FAKE_ROOT}'
    bash '${INSTALL_SH}'
  "
  [ "$status" -eq 1 ]
  [[ "$output" == *"must be run as root"* ]]
}

# ===========================================================================
# 2. Hotspot password generation
# ===========================================================================
@test "password: generates a 16-character alphanumeric string when unset" {
  unset ASTROCAM_HOTSPOT_PW
  run_install
  [ "$status" -eq 0 ]

  # The password is written into /etc/astrocam.conf
  pw_line="$(grep '^ASTROCAM_HOTSPOT_PW=' "${FAKE_ROOT}/etc/astrocam.conf")"
  pw="${pw_line#ASTROCAM_HOTSPOT_PW=}"

  # Must be exactly 16 characters
  [ "${#pw}" -eq 16 ]

  # Must be alphanumeric only
  [[ "$pw" =~ ^[A-Za-z0-9]+$ ]]
}

@test "password: preserved when ASTROCAM_HOTSPOT_PW is already set" {
  export ASTROCAM_HOTSPOT_PW="MyFixedPass12345"
  run_install
  [ "$status" -eq 0 ]

  pw_line="$(grep '^ASTROCAM_HOTSPOT_PW=' "${FAKE_ROOT}/etc/astrocam.conf")"
  pw="${pw_line#ASTROCAM_HOTSPOT_PW=}"
  [ "$pw" = "MyFixedPass12345" ]
}

# ===========================================================================
# 3. /etc/astrocam.conf
# ===========================================================================
@test "astrocam.conf: contains the three expected keys" {
  run_install
  [ "$status" -eq 0 ]

  conf="${FAKE_ROOT}/etc/astrocam.conf"
  grep -q "^ASTROCAM_SSID="       "$conf"
  grep -q "^ASTROCAM_HOTSPOT_PW=" "$conf"
  grep -q "^ASTROCAM_WIFI_IF="    "$conf"
}

@test "astrocam.conf: default SSID is HQAstroCam" {
  unset ASTROCAM_SSID
  run_install
  [ "$status" -eq 0 ]

  grep -q "^ASTROCAM_SSID=HQAstroCam" "${FAKE_ROOT}/etc/astrocam.conf"
}

@test "astrocam.conf: custom SSID and WiFi interface are written" {
  export ASTROCAM_SSID="MyScope"
  export ASTROCAM_WIFI_IF="wlan1"
  run_install
  [ "$status" -eq 0 ]

  grep -q "^ASTROCAM_SSID=MyScope"   "${FAKE_ROOT}/etc/astrocam.conf"
  grep -q "^ASTROCAM_WIFI_IF=wlan1"  "${FAKE_ROOT}/etc/astrocam.conf"
}

@test "astrocam.conf: has mode 600 (owner-only read/write)" {
  run_install
  [ "$status" -eq 0 ]

  perms="$(stat -c '%a' "${FAKE_ROOT}/etc/astrocam.conf")"
  [ "$perms" = "600" ]
}

# ===========================================================================
# 4. Camera config.txt
# ===========================================================================
@test "camera config: overlay lines appended when config.txt is present and empty" {
  mkdir -p "${FAKE_ROOT}/boot/firmware"
  touch "${FAKE_ROOT}/boot/firmware/config.txt"

  run_install
  [ "$status" -eq 0 ]

  grep -q "^camera_auto_detect=1" "${FAKE_ROOT}/boot/firmware/config.txt"
  grep -q "^dtoverlay=imx477"     "${FAKE_ROOT}/boot/firmware/config.txt"
}

@test "camera config: config.txt not modified when entries are already present" {
  mkdir -p "${FAKE_ROOT}/boot/firmware"
  printf 'camera_auto_detect=1\ndtoverlay=imx477\n' \
    > "${FAKE_ROOT}/boot/firmware/config.txt"
  original="$(cat "${FAKE_ROOT}/boot/firmware/config.txt")"

  run_install
  [ "$status" -eq 0 ]

  current="$(cat "${FAKE_ROOT}/boot/firmware/config.txt")"
  [ "$current" = "$original" ]
}

@test "camera config: skipped gracefully when no config.txt exists" {
  # Neither /boot/firmware/config.txt nor /boot/config.txt exists
  run_install
  [ "$status" -eq 0 ]

  # No config.txt should have been created
  [ ! -f "${FAKE_ROOT}/boot/firmware/config.txt" ]
  [ ! -f "${FAKE_ROOT}/boot/config.txt" ]
}

@test "camera config: falls back to /boot/config.txt when firmware path missing" {
  mkdir -p "${FAKE_ROOT}/boot"
  touch "${FAKE_ROOT}/boot/config.txt"

  run_install
  [ "$status" -eq 0 ]

  grep -q "^camera_auto_detect=1" "${FAKE_ROOT}/boot/config.txt"
}

# ===========================================================================
# 5. Sudoers file
# ===========================================================================
@test "sudoers: file contains the nmcli NOPASSWD rule" {
  run_install
  [ "$status" -eq 0 ]

  grep -q "astrocam ALL=(root) NOPASSWD: /usr/bin/nmcli" \
    "${FAKE_ROOT}/etc/sudoers.d/astrocam-network"
}

@test "sudoers: file has mode 440 (read-only for owner and group)" {
  run_install
  [ "$status" -eq 0 ]

  perms="$(stat -c '%a' "${FAKE_ROOT}/etc/sudoers.d/astrocam-network")"
  [ "$perms" = "440" ]
}

# ===========================================================================
# 6. NetworkManager dispatcher script
# ===========================================================================
@test "dispatcher: script is created at the expected path" {
  run_install
  [ "$status" -eq 0 ]

  [ -f "${FAKE_ROOT}/etc/NetworkManager/dispatcher.d/90-astrocam-hotspot" ]
}

@test "dispatcher: script is executable" {
  run_install
  [ "$status" -eq 0 ]

  [ -x "${FAKE_ROOT}/etc/NetworkManager/dispatcher.d/90-astrocam-hotspot" ]
}

@test "dispatcher: script has bash shebang and expected logic" {
  run_install
  [ "$status" -eq 0 ]

  script="${FAKE_ROOT}/etc/NetworkManager/dispatcher.d/90-astrocam-hotspot"
  # Check shebang
  head -1 "$script" | grep -q "bash"
  # Check that the hotspot-enable nmcli call is present
  grep -Fq 'nmcli dev wifi hotspot' "$script"
  # Check that the script exits early when an interface comes UP (correct
  # guard: hotspot is only enabled when no connection is active on DOWN/offline)
  grep -Fq '[[ "$ACTION" == "up" ]] && exit 0' "$script"
}

# ===========================================================================
# 7. Systemd service file
# ===========================================================================
@test "service: astrocam.service is copied to SERVICE_FILE location" {
  run_install
  [ "$status" -eq 0 ]

  [ -f "${FAKE_ROOT}/etc/systemd/system/astrocam.service" ]
}

@test "service: copied file contains the uvicorn ExecStart line" {
  run_install
  [ "$status" -eq 0 ]

  grep -q "uvicorn" "${FAKE_ROOT}/etc/systemd/system/astrocam.service"
}

@test "service: listens on port 8080 (not 80)" {
  run_install
  [ "$status" -eq 0 ]

  # Ensure port 8080 is specified, not port 80
  grep -q -- "--port 8080" "${FAKE_ROOT}/etc/systemd/system/astrocam.service"
}

# ===========================================================================
# 8. Overall success
# ===========================================================================
@test "full run: exits 0 and prints success banner" {
  run_install
  [ "$status" -eq 0 ]
  [[ "$output" == *"installed successfully"* ]]
}
