"""
HQAstroCam – Network management module
Uses nmcli (NetworkManager) to manage WiFi, hotspot and Ethernet.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _load_config() -> dict[str, str]:
    """Load /etc/astrocam.conf if present (key=value format)."""
    cfg: dict[str, str] = {}
    try:
        with open("/etc/astrocam.conf") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    cfg[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return cfg


_cfg = _load_config()

HOTSPOT_SSID     = os.environ.get("ASTROCAM_SSID",       _cfg.get("ASTROCAM_SSID",       "HQAstroCam"))
HOTSPOT_PASSWORD = os.environ.get("ASTROCAM_HOTSPOT_PW", _cfg.get("ASTROCAM_HOTSPOT_PW", ""))
WIFI_INTERFACE   = os.environ.get("ASTROCAM_WIFI_IF",    _cfg.get("ASTROCAM_WIFI_IF",    "wlan0"))
ETH_INTERFACE    = os.environ.get("ASTROCAM_ETH_IF",     "eth0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", "Command timed out"
    except Exception as exc:
        return -3, "", str(exc)


def _nmcli(*args: str, timeout: int = 15) -> tuple[int, str, str]:
    return _run(["nmcli"] + list(args), timeout=timeout)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_status() -> dict[str, Any]:
    """Return current network status."""
    rc, out, _ = _nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev")
    interfaces: list[dict] = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4:
                interfaces.append({
                    "device":     parts[0],
                    "type":       parts[1],
                    "state":      parts[2],
                    "connection": parts[3],
                })

    # Determine current mode
    mode = "unknown"
    wifi_connected = False
    eth_connected  = False
    hotspot_active = False
    ip_address     = None

    for iface in interfaces:
        dev  = iface["device"]
        st   = iface["state"]
        conn = iface["connection"]
        if dev == WIFI_INTERFACE:
            if st == "connected":
                if "Hotspot" in conn or conn == HOTSPOT_SSID:
                    hotspot_active = True
                    mode = "hotspot"
                else:
                    wifi_connected = True
                    mode = "wifi"
        if dev == ETH_INTERFACE and st == "connected":
            eth_connected = True
            mode = "ethernet"

    if not hotspot_active and not wifi_connected and not eth_connected:
        mode = "offline"

    # Get IP address of the relevant interface
    ip_iface = ETH_INTERFACE if eth_connected else WIFI_INTERFACE
    rc2, ip_out, _ = _run(
        ["ip", "-4", "addr", "show", ip_iface],
    )
    if rc2 == 0:
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip_out)
        if m:
            ip_address = m.group(1)

    # Hostname
    rc3, hostname, _ = _run(["hostname"])
    hostname = hostname if rc3 == 0 else "hqastrocam"

    return {
        "mode":           mode,
        "interfaces":     interfaces,
        "wifi_connected": wifi_connected,
        "eth_connected":  eth_connected,
        "hotspot_active": hotspot_active,
        "ip_address":     ip_address,
        "hostname":       hostname,
        "hotspot_ssid":   HOTSPOT_SSID,
    }


def enable_hotspot() -> dict[str, Any]:
    """Enable WiFi hotspot using NetworkManager."""
    # Delete existing hotspot connection if present
    _nmcli("connection", "delete", "Hotspot", timeout=5)

    rc, out, err = _nmcli(
        "dev", "wifi", "hotspot",
        "ifname",   WIFI_INTERFACE,
        "ssid",     HOTSPOT_SSID,
        "password", HOTSPOT_PASSWORD,
        timeout=20,
    )
    if rc != 0:
        logger.error("Failed to create hotspot: %s", err)
        return {"success": False, "error": err}

    logger.info("Hotspot enabled: SSID=%s", HOTSPOT_SSID)
    return {
        "success":  True,
        "ssid":     HOTSPOT_SSID,
        "password": HOTSPOT_PASSWORD,
    }


def disable_hotspot() -> dict[str, Any]:
    """Disable the active hotspot."""
    rc, out, err = _nmcli("connection", "down", HOTSPOT_SSID)
    if rc != 0:
        rc, out, err = _nmcli("connection", "down", "Hotspot")
    if rc != 0:
        return {"success": False, "error": err}
    return {"success": True}


def scan_wifi() -> list[dict[str, Any]]:
    """Return list of visible WiFi networks."""
    # Trigger a fresh scan
    _nmcli("dev", "wifi", "rescan", "ifname", WIFI_INTERFACE, timeout=5)

    rc, out, _ = _nmcli(
        "-t", "-f",
        "SSID,SIGNAL,SECURITY,IN-USE",
        "dev", "wifi", "list",
        "ifname", WIFI_INTERFACE,
    )
    networks: list[dict] = []
    seen: set[str] = set()
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4:
                ssid = parts[0]
                if not ssid or ssid in seen:
                    continue
                seen.add(ssid)
                networks.append({
                    "ssid":     ssid,
                    "signal":   int(parts[1]) if parts[1].isdigit() else 0,
                    "security": parts[2],
                    "in_use":   parts[3] == "*",
                })
        networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def connect_wifi(ssid: str, password: str) -> dict[str, Any]:
    """Connect to a WiFi network."""
    rc, out, err = _nmcli(
        "dev", "wifi", "connect", ssid,
        "password", password,
        "ifname", WIFI_INTERFACE,
        timeout=30,
    )
    if rc != 0:
        logger.error("WiFi connect failed: %s", err)
        return {"success": False, "error": err}
    logger.info("Connected to WiFi: %s", ssid)
    return {"success": True, "ssid": ssid}


def disconnect_wifi() -> dict[str, Any]:
    """Disconnect from the current WiFi network."""
    rc, out, err = _nmcli("dev", "disconnect", WIFI_INTERFACE)
    if rc != 0:
        return {"success": False, "error": err}
    return {"success": True}
