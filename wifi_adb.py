"""
WiFi ADB Operations Module.
Pure utility functions for managing ADB over WiFi connections.
"""

import os
import subprocess
import socket
import uuid
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
ADB_PATH = r"E:\pythonadb\ADB\adb.exe"
parent_dir = os.path.dirname(current_dir)
WIFI_DEVICES_FILE = os.path.join(current_dir, "devices_wifi.json")
PARENT_WIFI_DEVICES_FILE = os.path.join(parent_dir, "devices_wifi.json")


def resolve_adb_path() -> str:
    return ADB_PATH if os.path.exists(ADB_PATH) else "adb"


def _run_adb(cmd: list, timeout: int = 15, adb_path: str | None = None) -> subprocess.CompletedProcess:
    path = adb_path or resolve_adb_path()
    full_cmd = [path] + cmd
    return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence — devices_wifi.json
# ═══════════════════════════════════════════════════════════════════════════════

def load_wifi_devices() -> dict:
    if os.path.exists(WIFI_DEVICES_FILE) and os.path.getsize(WIFI_DEVICES_FILE) > 0:
        try:
            with open(WIFI_DEVICES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"devices": []}
    return {"devices": []}


def save_wifi_devices(data: dict) -> None:
    with open(WIFI_DEVICES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    try:
        with open(PARENT_WIFI_DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Core ADB Commands
# ═══════════════════════════════════════════════════════════════════════════════

def adb_tcpip(port=5555, device_serial=None, adb_path=None) -> dict:
    cmd_list = []
    if device_serial:
        cmd_list.extend(["-s", device_serial])
    cmd_list.extend(["tcpip", str(port)])

    try:
        result = _run_adb(cmd_list, timeout=15, adb_path=adb_path)
        output = result.stdout.strip() + result.stderr.strip()
        if result.returncode == 0 or "restarting" in output.lower():
            return {"ok": True, "message": f"TCP/IP mode enabled on port {port}. Restarting ADB in TCP/IP mode."}
        return {"ok": False, "error": output or f"Unknown error (code {result.returncode})"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out after 15 seconds"}
    except FileNotFoundError:
        return {"ok": False, "error": f"ADB binary not found: {adb_path or resolve_adb_path()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def adb_connect(ip, port=5555, adb_path=None) -> dict:
    endpoint = f"{ip}:{port}"
    try:
        result = _run_adb(["connect", endpoint], timeout=10, adb_path=adb_path)
        output = (result.stdout + result.stderr).strip().lower()

        if "connected to" in output:
            return {"ok": True, "message": f"Connected to {endpoint}", "serial": endpoint, "already_connected": False}
        elif "already connected" in output:
            return {"ok": True, "message": f"Already connected to {endpoint}", "serial": endpoint, "already_connected": True}
        elif "failed" in output or "unable" in output:
            return {"ok": False, "error": f"Connection failed: {output}"}
        else:
            return {"ok": False, "error": f"Unexpected response: {output}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Connection timed out after 10 seconds"}
    except FileNotFoundError:
        return {"ok": False, "error": f"ADB binary not found: {adb_path or resolve_adb_path()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def adb_disconnect(endpoint, adb_path=None) -> dict:
    try:
        result = _run_adb(["disconnect", endpoint], timeout=10, adb_path=adb_path)
        output = (result.stdout + result.stderr).strip()

        if "disconnected" in output.lower() or result.returncode == 0:
            return {"ok": True, "message": f"Disconnected from {endpoint}"}
        elif "no such device" in output.lower() or "error" in output.lower():
            return {"ok": False, "error": f"Device not found: {endpoint}"}
        else:
            return {"ok": True, "message": output or f"Disconnected from {endpoint}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Disconnect timed out"}
    except FileNotFoundError:
        return {"ok": False, "error": f"ADB binary not found: {adb_path or resolve_adb_path()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def adb_pair(ip, port, code, adb_path=None) -> dict:
    endpoint = f"{ip}:{port}"
    try:
        result = _run_adb(["pair", endpoint, code], timeout=15, adb_path=adb_path)
        output = (result.stdout + result.stderr).strip()

        if result.returncode == 0 and "successfully" in output.lower():
            return {"ok": True, "message": f"Successfully paired with {endpoint}"}
        elif "failed to parse" in output.lower():
            return {"ok": False, "error": "Invalid pairing code format"}
        else:
            return {"ok": False, "error": output or "Pairing failed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Pairing timed out after 15 seconds"}
    except FileNotFoundError:
        return {"ok": False, "error": f"ADB binary not found: {adb_path or resolve_adb_path()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Device Discovery & Status
# ═══════════════════════════════════════════════════════════════════════════════

def get_adb_wifi_devices(adb_path=None) -> list[str]:
    devices = []
    try:
        result = _run_adb(["devices"], timeout=10, adb_path=adb_path)
        lines = result.stdout.strip().split("\n")
        for line in lines[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1] == "device":
                serial = parts[0]
                if ":" in serial:  # WiFi device serial format: ip:port
                    devices.append(serial)
    except Exception:
        pass
    return devices


def get_all_adb_devices(adb_path=None) -> list[str]:
    devices = []
    try:
        result = _run_adb(["devices"], timeout=10, adb_path=adb_path)
        lines = result.stdout.strip().split("\n")
        for line in lines[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1] == "device":
                devices.append(parts[0])
    except Exception:
        pass
    return devices


def get_all_devices(adb_path=None) -> list[dict]:
    """Trả về danh sách thiết bị hợp nhất: ADB USB + WiFi đã lưu.
    Mỗi device là dict: {id, name, type, status, serial, ip, port}"""
    devices = []

    # USB ADB devices
    try:
        result = _run_adb(["devices"], timeout=10, adb_path=adb_path)
        lines = result.stdout.strip().split("\n")
        for line in lines[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1] == "device":
                serial = parts[0]
                # Only USB devices (no colon in serial)
                if ":" not in serial:
                    props = get_device_properties(serial, adb_path=adb_path)
                    name = props.get("model", "") or serial
                    devices.append({
                        "id": serial,
                        "name": name,
                        "type": "adb",
                        "level": "online",
                        "status": "online",
                        "serial": serial,
                        "ip": "",
                        "port": 0,
                    })
    except Exception:
        pass

    # WiFi saved devices
    wifi_data = load_wifi_devices()
    for w in wifi_data.get("devices", []):
        serial = w.get("serial", f"{w.get('ip', '')}:{w.get('port', 5555)}")
        online = is_device_online(w.get("ip", ""), w.get("port", 5555), timeout=0.5)
        devices.append({
            "id": serial,
            "device_id": w.get("id", serial),
            "name": w.get("name", w.get("ip", "")),
            "type": "wifi",
            "level": "online" if online else "offline",
            "serial": serial,
            "ip": w.get("ip", ""),
            "port": w.get("port", 5555),
        })

    return devices


def is_device_online(ip, port=5555, timeout=1.0) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def get_device_properties(serial, adb_path=None) -> dict:
    props = {"model": "", "manufacturer": "", "android": ""}

    props_map = {
        "ro.product.model": "model",
        "ro.product.manufacturer": "manufacturer",
        "ro.build.version.release": "android",
    }

    for prop_key, prop_name in props_map.items():
        try:
            result = _run_adb(["-s", serial, "shell", "getprop", prop_key], timeout=5, adb_path=adb_path)
            value = result.stdout.strip()
            if value and "error" not in value.lower():
                props[prop_name] = value
        except Exception:
            pass

    return props


def scan_network(timeout=0.3, adb_path=None) -> list[dict]:
    results = []

    # Get local subnet
    local_ip = _get_local_ip()
    if not local_ip:
        return results

    subnets = _derive_subnets(local_ip)

    all_ips = []
    for subnet_base in subnets:
        all_ips.extend([f"{subnet_base}.{i}" for i in range(1, 255)])

    # Scan in parallel
    reachable = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(_check_port, ip, 5555, timeout): ip for ip in all_ips}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                if future.result():
                    reachable.append(ip)
            except Exception:
                pass

    # Try ADB connect to each reachable IP
    for ip in reachable:
        result = adb_connect(ip, 5555, adb_path=adb_path)
        entry = {
            "ip": ip,
            "port": 5555,
            "serial": f"{ip}:5555",
            "model": "",
            "success": result.get("ok", False),
        }
        if result.get("ok"):
            props = get_device_properties(f"{ip}:5555", adb_path=adb_path)
            entry["model"] = props.get("model", "")
            entry["manufacturer"] = props.get("manufacturer", "")
            entry["android"] = props.get("android", "")
        results.append(entry)

    return results


def _get_local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 53))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ""


def _derive_subnets(local_ip: str) -> list[str]:
    try:
        parts = local_ip.rsplit(".", 1)
        base = parts[0]
        return [base]
    except Exception:
        return ["192.168.1", "192.168.0"]


def _is_device(ip: str, port: int, timeout: float) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Device CRUD Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def add_device(name, ip, port=5555, adb_path=None) -> str:
    import uuid
    data = load_wifi_devices()
    device_id = str(uuid.uuid4())[:8]

    serial = f"{ip}:{port}"
    online = is_device_online(ip, port)

    device = {
        "id": device_id,
        "name": name,
        "ip": ip,
        "port": port,
        "serial": serial,
        "connected": online,
        "last_seen": datetime.now().isoformat(),
        "properties": get_device_properties(serial, adb_path=adb_path) if online else {},
    }

    data["devices"].append(device)
    save_wifi_devices(data)
    return device_id


def update_device(device_id, name=None, ip=None, port=None, adb_path=None) -> bool:
    data = load_wifi_devices()
    for device in data.get("devices", []):
        if device["id"] == device_id:
            if name is not None:
                device["name"] = name
            if ip is not None:
                device["ip"] = ip
                device["serial"] = f"{ip}:{device.get('port', 5555)}"
            if port is not None:
                device["port"] = port
                device["serial"] = f"{device.get('ip', '')}:{port}"
            device["last_seen"] = datetime.now().isoformat()
            online = is_device_online(device["ip"], device.get("port", 5555))
            device["connected"] = online
            if online:
                device["properties"] = get_device_properties(device["serial"], adb_path=adb_path)
            save_wifi_devices(data)
            return True
    return False


def delete_device(device_id) -> bool:
    data = load_wifi_devices()
    devices = data.get("devices", [])
    for i, device in enumerate(devices):
        if device["id"] == device_id:
            # Disconnect before deleting
            adb_disconnect(device.get("serial", f"{device['ip']}:{device.get('port', 5555)}"))
            devices.pop(i)
            save_wifi_devices(data)
            return True
    return False


def get_device(device_id) -> dict | None:
    data = load_wifi_devices()
    for device in data.get("devices", []):
        if device["id"] == device_id:
            return device
    return None


def refresh_all_status(adb_path=None) -> list[dict]:
    data = load_wifi_devices()
    for device in data.get("devices", []):
        online = is_device_online(device["ip"], device.get("port", 5555))
        device["connected"] = online
        device["last_seen"] = datetime.now().isoformat()
        if online and not device.get("properties"):
            device["properties"] = get_device_properties(device["serial"], adb_path=adb_path)
    save_wifi_devices(data)
    return data["devices"]


def is_online(ip: str, port=5555, timeout=1.0) -> bool:
    return is_device_online(ip, port, timeout)