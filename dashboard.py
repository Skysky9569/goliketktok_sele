import os
import json
import threading
from collections import deque
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
DATA_FILE = os.path.join(current_dir, "datagolike.json")
PARENT_DATA_FILE = os.path.join(parent_dir, "datagolike.json")
TIKTOK_CACHE_FILE = os.path.join(current_dir, "tiktok_cache.json")
CONFIG_FILE = os.path.join(current_dir, "config.json")

# Default delay values — used as fallback when config.json is missing/corrupt
DEFAULT_DELAY_CONFIG = {
    "delay_job_min": 8,
    "delay_job_max": 14,
    "delay_action": 5,
    "delay_complete": 6,
    "delay_like": 2,
    "delay_follow": 3,
}

dashboard = {
    "status": "STOPPED",
    "current_action": "Chờ lệnh",
    "account": "Chưa chọn",
    "device": "Chưa kết nối",
    "job": 0,
    "success": 0,
    "failed": 0,
    "money": 0,
    "job_type": "None",
    "job_id": "--",
    "reward": 0,
    "runtime": "0s",
    "start_time": None,
    "selected_account_id": "1",
    "selected_tiktok_account": "",
    "tiktok_accounts": [],
    "pending_tiktok_choice": False,
    "delay_job_min": 8,
    "delay_job_max": 14,
    "delay_action": 5,
    "delay_complete": 6,
    "delay_like": 2,
    "delay_follow": 3,
    # Multi-account mode fields
    "multi_account_mode": False,
    "current_account_index": 0,
    "total_accounts": 0,
    "jobs_per_account": 0,
    # Device selection fields
    "available_devices": [],
    "selected_device_id": "",
    "pending_device_choice": False,
    # Per-run config (wizard)
    "fail_limit": 0,
    "rest_after_jobs": 0,
    "rest_duration_min": 5,
    "consecutive_failures": 0,
    # Batch queue
    "batch_queue": [],
    "queue_current_config": None,
    # TikTok cached account lists per GoLike account
    "tiktok_cache": {},
    # Parallel Chrome sessions
    "active_sessions": [],
    "sessions": {},
    "max_concurrent": 0,
    # WiFi ADB fields
    "wifi_scan_results": [],
    "wifi_scan_in_progress": False,
    "wifi_scan_progress": 0,
    # Unified devices (ADB + WiFi)
    "unified_devices": [],
}

logs = deque(maxlen=200)
history = deque(maxlen=100)

# Thread safety for dashboard writes
_session_lock = threading.Lock()

logs = deque(maxlen=200)
history = deque(maxlen=100)

def get_data_filepath():
    """Lấy đường dẫn file datagolike.json"""
    if os.path.exists(DATA_FILE):
        return DATA_FILE
    if os.path.exists(PARENT_DATA_FILE):
        return PARENT_DATA_FILE
    return DATA_FILE

def load_accounts():
    """Đọc danh sách tài khoản từ datagolike.json"""
    filepath = get_data_filepath()
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_accounts(data):
    """Lưu danh sách tài khoản vào datagolike.json"""
    filepath = get_data_filepath()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    # Lưu đồng bộ cả file ở parent nếu có
    try:
        with open(PARENT_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

def load_tiktok_cache():
    """Đọc cache danh sách TikTok account từ tiktok_cache.json"""
    if os.path.exists(TIKTOK_CACHE_FILE) and os.path.getsize(TIKTOK_CACHE_FILE) > 0:
        try:
            with open(TIKTOK_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_tiktok_cache(data):
    """Lưu cache TikTok account vào tiktok_cache.json"""
    with open(TIKTOK_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_config():
    """Đọc cấu hình từ config.json, ghi đè giá trị mặc định trong dashboard.
    Nếu file không tồn tại hoặc lỗi → giữ nguyên default."""
    try:
        if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in DEFAULT_DELAY_CONFIG:
                if key in data:
                    dashboard[key] = data[key]
            add_log("Đã tải cấu hình từ config.json", "SYSTEM")
    except (json.JSONDecodeError, IOError) as e:
        add_log(f"Không đọc được config.json, dùng mặc định: {e}", "WARNING")


def save_config():
    """Lưu cấu hình delay vào config.json."""
    data = {key: dashboard.get(key, DEFAULT_DELAY_CONFIG[key])
            for key in DEFAULT_DELAY_CONFIG}
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        add_log(f"Không ghi được config.json: {e}", "ERROR")


def add_log(message: str, level: str = "INFO"):
    """Thêm 1 log entry vào hàng đợi realtime log"""
    now_str = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        "time": now_str,
        "message": message,
        "level": level
    }
    logs.append(log_entry)

def add_history(job_type: str, job_id: str, status: str, reward: int,
                account_id: str = "", username: str = ""):
    """Thêm 1 bản ghi lịch sử công việc"""
    now_str = datetime.now().strftime("%H:%M:%S")
    history_entry = {
        "time": now_str,
        "job_type": job_type,
        "job_id": str(job_id),
        "status": status,
        "reward": reward,
        "account_id": str(account_id) if account_id else "",
        "username": username or "",
    }
    history.appendleft(history_entry)

def reset_dashboard():
    """Reset trạng thái thống kê về mặc định"""
    dashboard["job"] = 0
    dashboard["success"] = 0
    dashboard["failed"] = 0
    dashboard["money"] = 0
    dashboard["job_type"] = "None"
    dashboard["job_id"] = "--"
    dashboard["reward"] = 0
    dashboard["runtime"] = "0s"
    dashboard["start_time"] = None
    dashboard["selected_account_id"] = "1"
    dashboard["selected_tiktok_account"] = ""
    dashboard["tiktok_accounts"] = []
    dashboard["pending_tiktok_choice"] = False
    dashboard["delay_job_min"] = 8
    dashboard["delay_job_max"] = 14
    dashboard["delay_action"] = 5
    dashboard["delay_complete"] = 6
    dashboard["delay_like"] = 2
    dashboard["delay_follow"] = 3
    # Multi-account mode fields
    dashboard["multi_account_mode"] = False
    dashboard["current_account_index"] = 0
    dashboard["total_accounts"] = 0
    dashboard["jobs_per_account"] = 0
    # Device selection fields
    dashboard["available_devices"] = []
    dashboard["selected_device_id"] = ""
    dashboard["pending_device_choice"] = False
    # Per-run config (wizard)
    dashboard["fail_limit"] = 0
    dashboard["rest_after_jobs"] = 0
    dashboard["rest_duration_min"] = 5
    dashboard["consecutive_failures"] = 0
    # Batch queue
    dashboard["batch_queue"] = []
    dashboard["queue_current_config"] = None
    # TikTok cache
    dashboard["tiktok_cache"] = {}
    # Parallel Chrome sessions
    dashboard["active_sessions"] = []
    dashboard["sessions"] = {}
    dashboard["max_concurrent"] = 0
    # WiFi ADB fields
    dashboard["wifi_scan_results"] = []
    dashboard["wifi_scan_in_progress"] = False
    dashboard["wifi_scan_progress"] = 0
    dashboard["unified_devices"] = []
    logs.clear()
    history.clear()
    add_log("Đã reset thống kê Dashboard", "SYSTEM")

# Khởi tạo log ban đầu
load_config()
add_log("Hệ thống Dashboard GoLike khởi tạo thành công.", "SYSTEM")


def with_session_lock():
    """Trả về context manager cho dashboard session operations."""
    return _session_lock