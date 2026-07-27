"""
SessionManager — Quản lý nhiều AccountRunner chạy song song (multiprocessing).
Monitor batch_queue, auto-launch khi slot free, stop individual/all sessions.
"""
import os
import sys
import threading
import multiprocessing
from time import sleep
from queue import Empty

# Ensure session_runner importable from worker
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dashboard import dashboard, add_log, add_history, load_accounts


def _process_target(session_id, config, log_queue, stop_event):
    """Entry point for multiprocessing.Process — import inside to avoid
    module-level circular imports in spawned subprocesses."""
    from session_runner import run_session_in_process
    run_session_in_process(session_id, config, log_queue, stop_event)


class SessionManager:
    """Singleton manager for parallel processes."""

    _instance = None

    def __init__(self):
        self.sessions: dict[str, dict] = {}  # sid → {process, config, ...}
        self._lock = threading.Lock()
        self._counter = 0
        self._log_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._monitor_thread = None
        self._monitor_running = False

        dashboard["active_sessions"] = []
        dashboard["sessions"] = {}
        dashboard["max_concurrent"] = 0

        self._start_monitor()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = SessionManager()
        return cls._instance

    def _next_id(self) -> str:
        with self._lock:
            self._counter += 1
            return str(self._counter)

    # ── Monitor Thread ──────────────────────────────────────

    def _start_monitor(self):
        if self._monitor_running:
            return
        self._monitor_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self):
        while self._monitor_running:
            # Drain log queue
            try:
                while True:
                    msg = self._log_queue.get_nowait()
                    msg_type = msg.get("type", "")
                    if msg_type == "log":
                        add_log(msg["message"], msg.get("level", "INFO"))
                    elif msg_type == "history":
                        add_history(
                            job_type=msg.get("job_type", ""),
                            job_id=msg.get("job_id", ""),
                            status=msg.get("status", ""),
                            reward=msg.get("reward", 0),
                            account_id=msg.get("account_id", ""),
                            username=msg.get("username", ""),
                        )
                    elif msg_type == "state":
                        sid = msg.get("session_id", "")
                        with self._lock:
                            if sid in self.sessions:
                                self.sessions[sid].update(msg)
                        dashboard["sessions"][sid] = {
                            "session_id": sid,
                            "account_id": msg.get("account_id", "?"),
                            "username": msg.get("username", "?"),
                            "device_id": msg.get("device_id", "--"),
                            "tiktok_account": msg.get("tiktok_account", "--"),
                            "status": msg.get("status", "RUNNING"),
                            "job_count": msg.get("job_count", 0),
                            "success_count": msg.get("success_count", 0),
                            "fail_count": msg.get("fail_count", 0),
                            "total_money": msg.get("total_money", 0),
                            "running": msg.get("running", True),
                            "current_action": msg.get("current_action", ""),
                        }
            except Exception:
                pass

            # Check for dead processes
            with self._lock:
                dead = []
                for sid, entry in list(self.sessions.items()):
                    p = entry.get("process")
                    if p and not p.is_alive() and not entry.get("stopping_by_user"):
                        dead.append(sid)
                for sid in dead:
                    add_log(f"Session {sid} process exited.", "INFO")
                    self._cleanup_session(sid)

            if not self.sessions and not dashboard.get("batch_queue", []):
                dashboard["status"] = "STOPPED"
                dashboard["current_action"] = "Chờ lệnh"

        sleep(0.5)

    # ── Start ───────────────────────────────────────────────

    def start_session(self, config: dict) -> str | None:
        """Start 1 process. Returns session_id or None if device busy."""
        device_id = config.get("device_id", "")

        # Device conflict check
        if device_id:
            with self._lock:
                for sid, s in self.sessions.items():
                    if s.get("device_id") == device_id:
                        add_log(
                            f"Thiết bị {device_id} đang bận (session {sid}). Đưa lại vào queue.",
                            "WARNING",
                        )
                        dashboard["batch_queue"].insert(0, config)
                        return None

        session_id = self._next_id()
        stop_event = multiprocessing.Event()
        p = multiprocessing.Process(
            target=_process_target,
            args=(session_id, config, self._log_queue, stop_event),
            daemon=True,
        )
        p.start()

        with self._lock:
            self.sessions[session_id] = {
                "process": p,
                "device_id": device_id,
                "config": config,
                "account_id": config.get("account_id", "?"),
                "username": config.get("username", "?"),
                "stop_event": stop_event,
                "stopping_by_user": False,
            }
            dashboard["active_sessions"] = list(self.sessions.keys())

        add_log(
            f"Session {session_id} started (PID {p.pid}) — acc #{config.get('account_id', '?')}",
            "SUCCESS",
        )
        # Trigger queue feeding if nothing else running
        self._feed_queue()
        return session_id

    # ── Done / Feed ─────────────────────────────────────────

    def _cleanup_session(self, session_id: str):
        """Remove finished session and feed queue."""
        with self._lock:
            self.sessions.pop(session_id, None)
            dashboard["sessions"].pop(session_id, None)
            dashboard["active_sessions"] = list(self.sessions.keys())

        add_log(f"Session {session_id} finished. Còn lại: {len(self.sessions)}", "INFO")
        self._feed_queue()

        if not self.sessions and len(dashboard.get("batch_queue", [])) == 0:
            dashboard["status"] = "STOPPED"
            dashboard["current_action"] = "Chờ lệnh"
            add_log("Tất cả sessions hoàn tất.", "SYSTEM")

    def _feed_queue(self):
        while dashboard.get("batch_queue", []):
            config = dashboard["batch_queue"].pop(0)
            sid = self.start_session(config)
            if sid is None:
                break

    # ── Stop ────────────────────────────────────────────────

    def stop_session(self, session_id: str):
        with self._lock:
            entry = self.sessions.get(session_id)
        if not entry:
            return
        # Mark early to prevent monitor duplicate log
        entry["stopping_by_user"] = True
        stop_event = entry.get("stop_event")
        p = entry.get("process")

        # Signal worker to gracefully close Chrome
        if stop_event:
            stop_event.set()
        if p and p.is_alive():
            p.join(timeout=3)
            if p.is_alive():
                p.terminate()
                p.join(timeout=2)
                if p.is_alive():
                    p.kill()
        add_log(f"Session {session_id} stopped by user.", "WARNING")
        self._cleanup_session(session_id)

    def stop_all(self):
        dashboard["batch_queue"] = []
        dashboard["queue_current_config"] = None
        with self._lock:
            sids = list(self.sessions.keys())
        for sid in sids:
            self.stop_session(sid)
        dashboard["status"] = "STOPPED"
        dashboard["current_action"] = "Chờ lệnh"
        add_log("All sessions stopped. Queue cleared.", "WARNING")

    # ── Pause ───────────────────────────────────────────────

    def pause_session(self, session_id: str):
        # Pause toggle via log queue message
        try:
            self._log_queue.put_nowait({
                "type": "pause",
                "session_id": session_id,
            })
            add_log(f"Sent pause toggle to session {session_id}.", "MATH")
        except Exception:
            pass

    # ── State for UI ────────────────────────────────────────

    def get_sessions_list(self) -> list:
        result = []
        with self._lock:
            for sid in list(self.sessions.keys()):
                state = dashboard["sessions"].get(sid, {})
                if state:
                    result.append(state)
        result.sort(key=lambda x: int(x.get("session_id", "0")) if x.get("session_id", "0").isdigit() else 0)
        return result


# Singleton instance
manager = SessionManager.get_instance()