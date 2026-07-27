import os
import sys

# Đảm bảo đường dẫn import hoạt động đúng
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)
sys.path.insert(0, current_dir)

if parent_dir not in sys.path:
    sys.path.append(parent_dir)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from pydantic import BaseModel
from dashboard import dashboard, logs, history, reset_dashboard, add_log, load_accounts, save_accounts, save_config
from dom import bot_instance
from session_manager import manager as session_manager
import wifi_adb

app = FastAPI(
    title="GoLike Automation Control Center",
    description="FastAPI Web Interface & Realtime API for GoLike TikTok Bot",
    version="2.0.0"
)

class AccountModel(BaseModel):
    tk: str
    mk: str

class SelectAccountModel(BaseModel):
    account_id: str

class TikTokAccountModel(BaseModel):
    tiktok_account: str

@app.post("/api/tiktok_account/select")
def set_selected_tiktok_account(data: TikTokAccountModel):
    """Cấu hình tên tài khoản TikTok muốn ưu tiên chọn (lưu để dùng lần tiếp theo)"""
    target = data.tiktok_account.strip()
    dashboard["selected_tiktok_account"] = target
    if target:
        add_log(f"Đã thiết lập ưu tiên chọn acc TikTok: {target}", "INFO")
    else:
        add_log("Bot sẽ tự động chọn acc TikTok đầu tiên quét được", "INFO")
    return {"status": "ok", "selected_tiktok_account": target}

@app.post("/api/tiktok_account/choose")
def choose_tiktok_account(data: TikTokAccountModel):
    """Xác nhận lựa chọn acc TikTok từ popup - giải phóng bot đang chờ"""
    choice = data.tiktok_account.strip()
    if not choice:
        raise HTTPException(status_code=400, detail="Vui lòng chọn tài khoản TikTok!")
    dashboard["selected_tiktok_account"] = choice
    dashboard["pending_tiktok_choice"] = False
    add_log(f"✅ Đã xác nhận chọn acc TikTok: {choice}", "SUCCESS")
    return {"status": "ok", "selected": choice}

class DelayConfigModel(BaseModel):
    delay_job_min: int
    delay_job_max: int
    delay_action: int
    delay_complete: int
    delay_like: int
    delay_follow: int

class StartConfigModel(BaseModel):
    """Cấu hình cho 1 lần chạy acc (wizard/queue)"""
    account_id: str
    device_id: str = ""
    tiktok_account: str = ""
    fail_limit: int = 0
    rest_after_jobs: int = 0
    rest_duration_min: int = 5
    delay_job_min: Optional[int] = None
    delay_job_max: Optional[int] = None
    delay_action: Optional[int] = None
    delay_complete: Optional[int] = None
    delay_like: Optional[int] = None
    delay_follow: Optional[int] = None

class ReorderModel(BaseModel):
    from_index: int
    to_index: int

# ── WiFi ADB models ──────────────────────────────────────

class WiFiScanModel(BaseModel):
    timeout: float = 0.3

class WiFiConnectModel(BaseModel):
    ip: str
    port: int = 5555

class WiFiDisconnectModel(BaseModel):
    endpoint: str

class WiFiPairModel(BaseModel):
    ip: str
    port: int
    code: str

class WiFiDeviceModel(BaseModel):
    id: str
    name: str
    ip: str
    port: int = 5555

class WiFiSwitchTCPModel(BaseModel):
    device_serial: str = ""
    port: int = 5555

@app.post("/api/config/delay")
def save_delay_config(cfg: DelayConfigModel):
    """Lưu cấu hình delay vào dashboard (áp dụng ngay cho bot đang chạy)"""
    if cfg.delay_job_min < 1 or cfg.delay_job_max < cfg.delay_job_min:
        raise HTTPException(status_code=400, detail="Delay job không hợp lệ (min >= 1, max >= min)")
    if cfg.delay_action < 1:
        raise HTTPException(status_code=400, detail="Delay action phải >= 1 giây")
    if cfg.delay_complete < 1:
        raise HTTPException(status_code=400, detail="Delay sau click phải >= 1 giây")
    if cfg.delay_like < 1:
        raise HTTPException(status_code=400, detail="Delay like phải >= 1 giây")
    if cfg.delay_follow < 1:
        raise HTTPException(status_code=400, detail="Delay follow phải >= 1 giây")
    dashboard["delay_job_min"] = cfg.delay_job_min
    dashboard["delay_job_max"] = cfg.delay_job_max
    dashboard["delay_action"] = cfg.delay_action
    dashboard["delay_complete"] = cfg.delay_complete
    dashboard["delay_like"] = cfg.delay_like
    dashboard["delay_follow"] = cfg.delay_follow
    save_config()
    add_log(f"⚙️ Đã cập nhật delay config: Job {cfg.delay_job_min}-{cfg.delay_job_max}s | Action {cfg.delay_action}s | Sau click {cfg.delay_complete}s | Like {cfg.delay_like}s | Follow {cfg.delay_follow}s", "INFO")
    return {"status": "ok", "config": cfg.dict()}

# Mount thư mục tĩnh static
static_dir = os.path.join(current_dir, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def home():
    """Giao diện chính Web Dashboard"""
    template_path = os.path.join(current_dir, "templates", "index.html")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy file templates/index.html")
    return FileResponse(template_path)

@app.get("/api/dashboard")
def get_dashboard():
    """Lấy dữ liệu thống kê trạng thái hiện tại"""
    d = dict(dashboard)
    sessions = session_manager.get_sessions_list()
    d["sessions_list"] = sessions

    # ── Aggregate stats từ tất cả sessions ──
    total_job = sum(s.get("job_count", 0) for s in sessions)
    total_success = sum(s.get("success_count", 0) for s in sessions)
    total_failed = sum(s.get("fail_count", 0) for s in sessions)
    total_money = sum(s.get("total_money", 0) for s in sessions)

    # Gộp với legacy counter (dom.py) nếu có
    total_job += d.get("job", 0)
    total_success += d.get("success", 0)
    total_failed += d.get("failed", 0)
    total_money += d.get("money", 0)

    d["job"] = total_job
    d["success"] = total_success
    d["failed"] = total_failed
    d["money"] = total_money

    return d

@app.get("/api/logs")
def get_logs():
    """Lấy danh sách nhật ký realtime (tối đa 200 dòng)"""
    return list(logs)

@app.get("/api/history")
def get_history():
    """Lấy danh sách lịch sử công việc gần đây (tối đa 100 dòng)"""
    return list(history)

@app.get("/api/accounts")
def get_accounts():
    """Lấy danh sách tài khoản GoLike"""
    accs = load_accounts()
    return {
        "accounts": accs,
        "selected_id": str(dashboard.get("selected_account_id", "1"))
    }

@app.post("/api/accounts")
def add_account(acc: AccountModel):
    """Thêm hoặc cập nhật tài khoản GoLike"""
    if not acc.tk.strip() or not acc.mk.strip():
        raise HTTPException(status_code=400, detail="Tài khoản và mật khẩu không được để trống")
    
    accs = load_accounts()
    existing_ids = [int(k) for k in accs.keys() if k.isdigit()]
    new_id = str(max(existing_ids) + 1 if existing_ids else 1)
    
    for k, v in accs.items():
        if v.get("tk") == acc.tk.strip():
            new_id = k
            break
            
    accs[new_id] = {
        "tk": acc.tk.strip(),
        "mk": acc.mk.strip()
    }
    save_accounts(accs)
    add_log(f"Đã lưu tài khoản {acc.tk.strip()} vào datagolike.json", "SUCCESS")
    return {"status": "ok", "account_id": new_id, "accounts": accs}

@app.delete("/api/accounts/{acc_id}")
def delete_account(acc_id: str):
    """Xóa tài khoản theo ID"""
    accs = load_accounts()
    if acc_id in accs:
        deleted_tk = accs[acc_id].get("tk", "")
        del accs[acc_id]
        save_accounts(accs)
        add_log(f"Đã xóa tài khoản ID {acc_id} ({deleted_tk}) khỏi datagolike.json", "WARNING")
        return {"status": "ok", "accounts": accs}
    raise HTTPException(status_code=404, detail="Không tìm thấy ID tài khoản")

@app.post("/api/accounts/select")
def select_account(data: SelectAccountModel):
    """Chọn tài khoản active để chạy bot"""
    accs = load_accounts()
    if data.account_id in accs:
        dashboard["selected_account_id"] = str(data.account_id)
        selected_tk = accs[data.account_id].get("tk")
        dashboard["account"] = selected_tk
        add_log(f"Đã chọn tài khoản active: {selected_tk}", "INFO")
        return {"status": "ok", "selected_account_id": data.account_id, "account": selected_tk}
    raise HTTPException(status_code=404, detail="ID tài khoản không hợp lệ")

@app.post("/api/start")
def start_bot(cfg: StartConfigModel = None):
    """Khởi chạy bot. Có body → wizard mode (SessionManager process).
    Không body → legacy single mode (bot_instance)."""
    if cfg is None:
        success = bot_instance.start()
        return {"status": "ok" if success else "already_running", "bot_status": dashboard["status"]}

    # Wizard / direct start → use SessionManager for parallel process execution
    config = {k: v for k, v in cfg.dict().items() if v is not None}
    from session_manager import manager as sm
    sid = sm.start_session(config)
    if sid is None:
        return {"status": "device_busy", "message": "Thiết bị đang bận, đã chuyển vào queue"}
    return {"status": "ok", "session_id": sid, "bot_status": dashboard["status"]}

@app.post("/api/start-multi")
def start_multi_account_mode():
    """Kích hoạt chạy Bot ở chế độ nhiều tài khoản"""
    if bot_instance.running or len(session_manager.sessions) > 0:
        return {"status": "error", "detail": "Bot is already running"}
    dashboard["multi_account_mode"] = True
    dashboard["current_account_index"] = 0
    dashboard["total_accounts"] = 0
    dashboard["jobs_per_account"] = 0  # Optional: could be made configurable via request body
    success = bot_instance.start_multi_account_mode()
    return {"status": "ok" if success else "error", "bot_status": dashboard["status"]}

@app.post("/api/pause")
def pause_bot():
    """Tạm dừng hoặc tiếp tục Bot"""
    success = bot_instance.pause()
    return {"status": "ok" if success else "not_running", "bot_status": dashboard["status"]}

@app.post("/api/stop")
def stop_bot():
    """Dừng Bot hoàn toàn"""
    success = bot_instance.stop()
    return {"status": "ok" if success else "already_stopped", "bot_status": dashboard["status"]}

@app.post("/api/device/select")
def select_device(data: dict):
    """Chọn thiết bị ADB từ dashboard"""
    device_id = data.get("device_id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="Vui lòng chọn thiết bị!")

    # Update dashboard with selected device
    dashboard["selected_device_id"] = device_id
    dashboard["device"] = device_id
    dashboard["pending_device_choice"] = False

    add_log(f"Đã chọn thiết bị ADB: {device_id}", "INFO")
    return {"status": "ok", "selected_device": device_id}

@app.post("/api/reset")
def reset_stats():
    """Reset thống kê Dashboard"""
    reset_dashboard()
    return {"status": "ok", "message": "Đã reset toàn bộ chỉ số thống kê."}

@app.post("/api/refresh_devices")
def refresh_devices():
    """Làm mới danh sách thiết bị ADB + WiFi"""
    try:
        from wifi_adb import get_all_devices
        devices = get_all_devices()
        device_ids = [d["id"] for d in devices]

        dashboard["available_devices"] = device_ids
        dashboard["unified_devices"] = devices

        # Auto-select nếu chỉ có 1 thiết bị và không ở multi mode
        if len(devices) == 1 and not dashboard.get("multi_account_mode", False):
            target = devices[0]["id"]
            dashboard["selected_device_id"] = target
            dashboard["device"] = devices[0]["name"]

            return {
                "status": "ok",
                "devices": devices,
                "selected_device": target,
                "pending_choice": False,
                "message": f"Tìm thấy 1 thiết bị: {devices[0]['name']}. Đã tự động chọn."
            }
        elif len(devices) > 1:
            dashboard["pending_device_choice"] = True
            dashboard["selected_device_id"] = ""

            return {
                "status": "ok",
                "devices": devices,
                "selected_device": "",
                "pending_choice": True,
                "message": f"Tìm thấy {len(devices)} thiết bị (ADB + WiFi). Vui lòng chọn."
            }
        else:
            dashboard["available_devices"] = []
            dashboard["unified_devices"] = []
            dashboard["selected_device_id"] = ""
            dashboard["device"] = "Chưa kết nối"
            dashboard["pending_device_choice"] = False

            return {
                "status": "ok",
                "devices": [],
                "selected_device": "",
                "pending_choice": False,
                "message": "Không tìm thấy thiết bị nào."
            }
    except Exception as e:
        add_log(f"Lỗi làm mới danh sách thiết bị: {e}", "ERROR")
        raise HTTPException(status_code=500, detail=f"Lỗi làm mới thiết bị: {str(e)}")

# ── Batch Queue endpoints ────────────────────────────────────────────

@app.post("/api/queue/add")
def add_to_queue(cfg: StartConfigModel):
    """Thêm AccountRunConfig vào batch_queue"""
    queue = dashboard.get("batch_queue", [])
    run_config = {k: v for k, v in cfg.dict().items() if v is not None}
    # Enrich with username from accounts file
    accs = load_accounts()
    if run_config["account_id"] in accs:
        run_config["username"] = accs[run_config["account_id"]]["tk"]
    queue.append(run_config)
    dashboard["batch_queue"] = queue
    add_log(f"Đã thêm {run_config.get('username', run_config.get('account_id'))} vào queue (vị trí {len(queue)})", "INFO")
    return {"status": "ok", "queue_length": len(queue), "queue": queue}

@app.get("/api/queue")
def get_queue():
    """Lấy trạng thái batch queue hiện tại"""
    return {
        "current": dashboard.get("queue_current_config"),
        "queue": dashboard.get("batch_queue", [])
    }

@app.delete("/api/queue/{index}")
def remove_from_queue(index: int):
    """Xóa 1 item khỏi batch_queue"""
    queue = dashboard.get("batch_queue", [])
    if 0 <= index < len(queue):
        removed = queue.pop(index)
        dashboard["batch_queue"] = queue
        add_log(f"Đã xóa {removed.get('username', 'unknown')} khỏi queue vị trí {index}", "INFO")
        return {"status": "ok", "queue": queue}
    raise HTTPException(status_code=404, detail="Vị trí queue không hợp lệ")

@app.post("/api/queue/reorder")
def reorder_queue(data: ReorderModel):
    """Đổi thứ tự 2 item trong queue"""
    queue = dashboard.get("batch_queue", [])
    if 0 <= data.from_index < len(queue) and 0 <= data.to_index < len(queue):
        item = queue.pop(data.from_index)
        queue.insert(data.to_index, item)
        dashboard["batch_queue"] = queue
        return {"status": "ok", "queue": queue}
    raise HTTPException(status_code=400, detail="Vị trí không hợp lệ")

# ===================================================================== TikTok cache
# ── ── ── ── ── ── ── ── ── ── ── ──

@app.post("/api/accounts/{acc_id}/scan-tiktok")
def scan_tiktok_accounts(acc_id: str):
    """Login acc GoLike, vào TikTok section, quét danh sách acc TikTok, cache lại."""
    accs = load_accounts()
    if acc_id not in accs:
        raise HTTPException(status_code=404, detail="Không tìm thấy ID tài khoản")

    if bot_instance.running or len(session_manager.sessions) > 0:
        raise HTTPException(status_code=409, detail="Bot đang chạy, vui lòng dừng bot trước khi scan")

    result = bot_instance.scan_tiktok_for_account(
        username=accs[acc_id]["tk"],
        password=accs[acc_id]["mk"]
    )
    if result is None:
        raise HTTPException(status_code=500, detail="Quét TikTok thất bại")
    return {"status": "ok", "account_id": acc_id, "tiktok_accounts": result["accounts"], "scanned_at": result["scanned_at"]}

@app.get("/api/accounts/{acc_id}/tiktok-cache")
def get_tiktok_cache(acc_id: str):
    """Đọc cache TikTok của 1 acc GoLogin"""
    from dashboard import load_tiktok_cache
    cache = load_tiktok_cache()
    result = cache.get(acc_id)
    if result:
        return {"status": "ok", **result}
    return {"status": "ok", "accounts": [], "scanned_at": None}

@app.delete("/api/accounts/{acc_id}/tiktok-cache")
def clear_tiktok_cache(acc_id: str):
    """Xóa cache TikTok của 1 acc"""
    from dashboard import load_tiktok_cache, save_tiktok_cache
    cache = load_tiktok_cache()
    if cache.get(acc_id):
        del cache[acc_id]
        save_tiktok_cache(cache)
        add_log(f"Đã xóa TikTok cache cho acc ID {acc_id}", "INFO")
    return {"status": "ok"}

# ── Session Management endpoints ─────────────────────────────

@app.get("/api/sessions")
def get_sessions():
    """Lấy danh sách tất cả Chrome sessions đang chạy."""
    return {
        "sessions": session_manager.get_sessions_list(),
        "batch_queue": dashboard.get("batch_queue", [])
    }


@app.post("/api/sessions/{session_id}/stop")
def stop_session(session_id: str):
    """Dừng 1 session Chrome cụ thể."""
    session_manager.stop_session(session_id)
    return {"status": "ok", "stopped": session_id}


@app.post("/api/sessions/{session_id}/pause")
def pause_session(session_id: str):
    """Tạm dừng / tiếp tục 1 session."""
    session_manager.pause_session(session_id)
    return {"status": "ok", "toggled": session_id}


@app.post("/api/stop-all")
def stop_all_sessions():
    """Dừng tất cả Chrome sessions + clear queue."""
    session_manager.stop_all()
    return {"status": "ok", "stopped_all": True}

# =====================================================================

# ════════════════════════════════════════════════════════════
# WiFi ADB Endpoints
# ════════════════════════════════════════════════════════════

@app.post("/api/wifi/scan")
def wifi_scan(data: WiFiScanModel = None):
    """Quét mạng LAN tìm thiết bị ADB WiFi."""
    if data is None:
        data = WiFiScanModel()
    if dashboard.get("wifi_scan_in_progress", False):
        return {"status": "ok", "skipped": True, "message": "Scan already in progress"}

    dashboard["wifi_scan_in_progress"] = True
    dashboard["wifi_scan_progress"] = 0

    def _do_scan():
        try:
            import time
            # Progress simulation: 0 -> 30% setup
            dashboard["wifi_scan_progress"] = 10
            results = wifi_adb.scan_network(timeout=data.timeout)
            dashboard["wifi_scan_progress"] = 80
            dashboard["wifi_scan_results"] = results

            # Auto-add discovered devices to saved list
            saved = wifi_adb.load_wifi_devices()
            existing_ips = {d["ip"] for d in saved.get("devices", [])}
            for r in results:
                if r.get("success") and r["ip"] not in existing_ips:
                    name = r.get("model") or f"Device {r['ip']}"
                    saved["devices"].append({
                        "id": str(__import__("uuid").uuid4())[:8],
                        "name": name,
                        "ip": r["ip"],
                        "port": r.get("port", 5555),
                        "serial": r.get("serial", f"{r['ip']}:{r.get('port', 5555)}"),
                        "connected": True,
                        "last_seen": __import__("datetime").datetime.now().isoformat(),
                        "properties": {
                            "model": r.get("model", ""),
                            "manufacturer": r.get("manufacturer", ""),
                            "android": r.get("android", ""),
                        }
                    })
                    existing_ips.add(r["ip"])
            wifi_adb.save_wifi_devices(saved)

            dashboard["wifi_scan_progress"] = 100
            dashboard["wifi_scan_in_progress"] = False
            add_log(f"Quét WiFi hoàn tất: tìm thấy {len(results)} thiết bị", "INFO")
        except Exception as e:
            dashboard["wifi_scan_in_progress"] = False
            dashboard["wifi_scan_progress"] = 0
            add_log(f"Lỗi quét WiFi: {e}", "ERROR")

    import threading
    t = threading.Thread(target=_do_scan, daemon=True)
    t.start()
    add_log("Bắt đầu quét mạng WiFi...", "INFO")
    return {"status": "ok", "message": "Scan started in background"}


@app.get("/api/wifi/devices")
def wifi_get_devices():
    """Lấy danh sách thiết bị WiFi đã lưu + trạng thái online."""
    devices_data = wifi_adb.load_wifi_devices()
    devices = devices_data.get("devices", [])

    # Update online status per device
    for d in devices:
        d["online"] = wifi_adb.is_device_online(d["ip"], d.get("port", 5555), timeout=0.5)
        if not d.get("serial"):
            d["serial"] = f"{d['ip']}:{d.get('port', 5555)}"

    return {"status": "ok", "devices": devices}


@app.post("/api/wifi/connect")
def wifi_connect(data: WiFiConnectModel):
    """Kết nối đến thiết bị WiFi qua ADB."""
    if not data.ip.strip():
        raise HTTPException(status_code=400, detail="IP is required")
    result = wifi_adb.adb_connect(data.ip, data.port)
    if result.get("ok") and not result.get("already_connected"):
        props = wifi_adb.get_device_properties(result.get("serial", f"{data.ip}:{data.port}"))
        result["properties"] = props
        add_log(f"WiFi ADB: {result['message']}", "SUCCESS")
    elif result.get("ok"):
        add_log(f"WiFi ADB: {result['message']}", "INFO")
    else:
        add_log(f"Kết nối WiFi thất bại: {result.get('error', 'Không rõ')}", "ERROR")
    return result


@app.post("/api/wifi/connect-usb")
def wifi_connect_usb(data: WiFiSwitchTCPModel = None):
    """Chuyển thiết bị USB hiện tại sang chế độ TCP/IP."""
    if data is None:
        data = WiFiSwitchTCPModel()
    serial = data.device_serial.strip() if data.device_serial else None
    result = wifi_adb.adb_tcpip(data.port, device_serial=serial)
    if result["ok"]:
        add_log(f"USB device switched to TCP/IP: {result['message']}", "SUCCESS")
    else:
        add_log(f"TCP/IP switch failed: {result.get('error', '')}", "ERROR")
    return result


@app.post("/api/wifi/disconnect")
def wifi_disconnect(data: WiFiDisconnectModel):
    """Ngắt kết nối WiFi ADB."""
    if not data.endpoint.strip():
        raise HTTPException(status_code=400, detail="Endpoint is required")
    result = wifi_adb.adb_disconnect(data.endpoint.strip())
    if result["ok"]:
        add_log(f"WiFi ADB: {result['message']}", "INFO")
    else:
        add_log(f"Ngắt kết nối WiFi thất bại: {result.get('error', '')}", "ERROR")
    return result


@app.post("/api/wifi/pair")
def wifi_pair(data: WiFiPairModel):
    """Ghép nối thiết bị Android 11+ qua WiFi pairing."""
    if not data.ip.strip() or not data.code.strip():
        raise HTTPException(status_code=400, detail="IP and pairing code are required")
    result = wifi_adb.adb_pair(data.ip, data.port, data.code)
    if result["ok"]:
        add_log(f"Ghép nối WiFi: {result['message']}", "SUCCESS")
    else:
        add_log(f"Ghép nối WiFi thất bại: {result.get('error', '')}", "ERROR")
    return result


@app.post("/api/wifi/devices/add")
def wifi_add_device(data: WiFiDeviceModel):
    """Thêm thiết bị WiFi mới vào danh sách lưu."""
    if not data.name.strip() or not data.ip.strip():
        raise HTTPException(status_code=400, detail="Name and IP are required")
    device_id = wifi_adb.add_device(data.name.strip(), data.ip.strip(), data.port)
    add_log(f"Đã lưu thiết bị WiFi: {data.name} ({data.ip}:{data.port})", "SUCCESS")
    return {"status": "ok", "device_id": device_id}


@app.put("/api/wifi/devices/{device_id}")
def wifi_update_device(device_id: str, data: WiFiDeviceModel):
    """Cập nhật thông tin thiết bị WiFi đã lưu."""
    ok = wifi_adb.update_device(
        device_id,
        name=data.name.strip() if data.name else None,
        ip=data.ip.strip() if data.ip else None,
        port=data.port,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found")
    add_log(f"Đã cập nhật thiết bị WiFi: {data.name or device_id}", "INFO")
    return {"status": "ok"}


@app.delete("/api/wifi/devices/{device_id}")
def wifi_delete_device(device_id: str):
    """Xóa thiết bị WiFi khỏi danh sách lưu."""
    device = wifi_adb.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    wifi_adb.delete_device(device_id)
    add_log(f"Đã xóa thiết bị WiFi: {device.get('name', device_id)}", "WARNING")
    return {"status": "ok"}


@app.post("/api/wifi/devices/{device_id}/reconnect")
def wifi_reconnect_device(device_id: str):
    """Kết nối lại thiết bị WiFi đã lưu."""
    device = wifi_adb.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Disconnect old then reconnect
    wifi_adb.adb_disconnect(device.get("serial", f"{device['ip']}:{device.get('port', 5555)}"))
    result = wifi_adb.adb_connect(device["ip"], device.get("port", 5555))
    if result["ok"]:
        add_log(f"Đã kết nối lại WiFi: {device.get('name', device_id)}", "SUCCESS")
    else:
        add_log(f"Kết nối lại WiFi thất bại: {result.get('error', '')}", "ERROR")
    return result


@app.post("/api/wifi/refresh-status")
def wifi_refresh_status():
    """Làm mới trạng thái online/offline của tất cả thiết bị WiFi."""
    devices = wifi_adb.refresh_all_status()
    online_count = sum(1 for d in devices if d.get("connected"))
    add_log(f"Đã làm mới trạng thái WiFi: {online_count}/{len(devices)} thiết bị online", "INFO")
    return {"status": "ok", "devices": devices, "online": online_count, "total": len(devices)}


# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    add_log("Đang khởi động Uvicorn Web Server tại http://127.0.0.1:8000 ...", "SYSTEM")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)