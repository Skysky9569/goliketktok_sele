"""
AccountRunner — One parallel Chrome session.
Mỗi instance = 1 process + 1 Chrome window + 1 ADB device.
Chạy pipeline cho 1 account GoLike rồi tự cleanup.
Giao tiếp với main process qua multiprocessing.Queue.
"""
import sys
import os
import re
import random
import subprocess
import threading
from time import sleep, time

# Safe path setup
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir in sys.path:
    sys.path.remove(current_dir)
sys.path.insert(0, current_dir)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import uiautomator2 as u2

# Only import file I/O from dashboard — NOT the dict (not shared in subprocess)
from dashboard import load_accounts, load_tiktok_cache, save_tiktok_cache

ADB_PATH = r"E:\pythonadb\ADB\adb.exe"


def run_session_in_process(session_id: str, config: dict, log_queue, stop_event=None):
    """Entry point for multiprocessing.Process. Creates AccountRunner and runs pipeline."""
    runner = AccountRunner(session_id, config, log_queue, stop_event)
    runner.run()


class AccountRunner:
    """One parallel Chrome session = one thread + one Chrome window + one ADB device."""

    def __init__(self, session_id: str, config: dict, log_queue=None, stop_event=None, window_offset: int = 0):
        self.session_id = session_id
        self.config = config
        self.window_offset = window_offset
        self.log_queue = log_queue
        self._stop_event = stop_event

        self.driver = None
        self._chromedriver_pid = None
        self.u2_device = None
        self.device_id = None
        self.account_name = ""
        self.tiktok_account = ""
        self.running = False
        self.paused = False
        self.job_count = 0
        self.fail_count = 0
        self.success_count = 0
        self.total_money = 0
        self.current_action = "Chờ khởi tạo..."
        self.current_job_type = ""
        self.current_job_id = ""

    def _should_stop(self):
        """Check if main process signaled stop."""
        if self._stop_event and self._stop_event.is_set():
            self.running = False
            return True
        return False

    def _is_driver_alive(self, timeout: float = 3.0) -> bool:
        """Kiểm tra nhanh xem Chrome driver còn hoạt động không.
        Bounded timeout: nếu Chrome/ChromeDriver treo, return False thay vì chờ vô hạn.
        """
        if not self.driver:
            return False

        result_holder = {"ok": False, "exc": None}

        def _probe():
            try:
                self.driver.current_url
                result_holder["ok"] = True
            except Exception as e:
                result_holder["exc"] = e

        t = threading.Thread(target=_probe, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            # Probe hung → assume driver dead, kill thread-truthful state via daemon=True
            if self._chromedriver_pid:
                self._log("Chrome probe hung — driver dead, killing chromedriver tree.", "WARNING")
                self._force_kill_chrome_orphans(self._chromedriver_pid)
            return False
        return result_holder["ok"]

    def _safe_sleep(self, seconds: float, check_interval=0.5):
        """Sleep with stop-event check — exits early if shutdown signaled."""
        end = time() + seconds
        while time() < end:
            if self._should_stop():
                return False
            remaining = end - time()
            sleep(min(check_interval, max(0.1, remaining)))
        return True

    def _interaction_sleep(self):
        """Delay giữa các thao tác Chrome DOM để tránh thao tác quá nhanh gây lag máy."""
        base = float(self.config.get("delay_interaction", 1.5))
        jitter = float(self.config.get("delay_interaction_jitter", 0.5))
        delay = max(0.3, base + random.uniform(-jitter, jitter))
        # Sleep in small chunks with stop-event checking
        self._safe_sleep(delay, check_interval=0.5)

    @property
    def adb_path(self):
        return ADB_PATH if os.path.exists(ADB_PATH) else "adb"

    def _log(self, msg: str, level: str = "INFO"):
        """Send log message to main process via queue."""
        try:
            if self.log_queue:
                self.log_queue.put_nowait({
                    "type": "log",
                    "message": f"[S{self.session_id}] {msg}",
                    "level": level,
                })
        except Exception:
            pass  # Queue may be full or closed during shutdown

    def _send_history(self, job_type, job_id, status, reward):
        """Send history entry to main process via queue."""
        try:
            if self.log_queue:
                self.log_queue.put_nowait({
                    "type": "history",
                    "job_type": job_type,
                    "job_id": str(job_id) if job_id else "--",
                    "status": status,
                    "reward": reward,
                    "account_id": str(self.config.get("account_id", "")),
                    "username": self.tiktok_account or "",
                })
        except Exception:
            pass

    def _push_state(self):
        """Push current state to main process."""
        try:
            if self.log_queue:
                self.log_queue.put_nowait({
                    "type": "state",
                    "session_id": self.session_id,
                    "account_id": self.config.get("account_id", "?"),
                    "username": self.account_name or "?",
                    "device_id": self.device_id or "--",
                    "tiktok_account": self.tiktok_account or "--",
                    "status": "PAUSED" if self.paused else "RUNNING",
                    "job_count": self.job_count,
                    "success_count": self.success_count,
                    "fail_count": self.fail_count,
                    "total_money": self.total_money,
                    "running": self.running,
                    "current_action": self.current_action,
                })
        except Exception:
            pass

    # ── Chrome window management ────────────────────────────

    def close_driver(self, quit_timeout: float = 5.0):
        """Đóng Chrome của session này. Force kill orphans nếu driver.quit() hangs hoặc fails."""
        chromedriver_pid = getattr(self, "_chromedriver_pid", None)

        if self.driver:
            quit_holder = {"done": False, "exc": None}

            def _do_quit():
                try:
                    self.driver.quit()
                except Exception as e:
                    quit_holder["exc"] = e
                finally:
                    quit_holder["done"] = True

            t = threading.Thread(target=_do_quit, daemon=True)
            t.start()
            t.join(timeout=quit_timeout)

            if not quit_holder["done"]:
                # quit() hung beyond timeout — force kill chromedriver ngay
                self._log("driver.quit() hung — force killing chromedriver tree.", "WARNING")
                if chromedriver_pid:
                    self._force_kill_chrome_orphans(chromedriver_pid)
            elif quit_holder["exc"]:
                self._log(f"driver.quit() failed — force killing orphans: {quit_holder['exc']}", "WARNING")
                if chromedriver_pid:
                    self._force_kill_chrome_orphans(chromedriver_pid)
            else:
                self._log("Chrome window closed.", "INFO")

            self.driver = None

        # Belt-and-suspenders: always kill chromedriver PID + its Chrome child tree.
        # Covers clean exit (orphans may still exist), hung case, and exception case.
        if chromedriver_pid:
            self._force_kill_chrome_orphans(chromedriver_pid)

    @staticmethod
    def _force_kill_chrome_orphans(chromedriver_pid: int | None = None):
        """Kill orphaned chromedriver + Chrome processes spawned by this session.
        Uses taskkill /T (tree) to kill chromedriver and all its Chrome children."""
        import subprocess as _sp

        if chromedriver_pid:
            # Kill chromedriver + entire child process tree (includes spawned chrome.exe)
            try:
                _sp.run(
                    ["taskkill", "/F", "/T", "/PID", str(chromedriver_pid)],
                    capture_output=True, timeout=15,
                )
            except Exception:
                pass

    def get_adb_devices(self):
        """Lấy danh sách thiết bị ADB đang kết nối."""
        devices = []
        try:
            cmd = [self.adb_path, "devices"] if os.path.exists(self.adb_path) else ["adb", "devices"]
            output = subprocess.check_output(cmd).decode("utf-8")
            lines = output.strip().split("\n")
            for line in lines[1:]:
                parts = line.split()
                if len(parts) > 1 and parts[1] == "device":
                    devices.append(parts[0])
        except Exception as e:
            self._log(f"Lỗi đọc ADB devices: {e}", "WARNING")
        return devices

    def connect_device(self, device_id=None):
        """Kết nối tới thiết bị ADB."""
        import subprocess
        devices = self.get_adb_devices()
        if not devices:
            self._log("Không tìm thấy thiết bị ADB nào!", "ERROR")
            return False

        if device_id and device_id in devices:
            target = device_id
        else:
            target = devices[0]

        try:
            self.u2_device = u2.connect(target)
            self.device_id = target
            self._log(f"Kết nối ADB: {target}", "INFO")
            return True
        except Exception as e:
            self._log(f"Lỗi kết nối uiautomator2: {e}", "ERROR")
            return False

    # ── Chrome Selenium ─────────────────────────────────────

    def init_driver(self):
        """Khởi tạo Chrome Selenium với cascade window position."""
        try:
            options = Options()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--remote-debugging-port=0")  # OS picks free port — no conflicts
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.7871.127 Safari/537.36"
            )

            self.driver = webdriver.Chrome(options=options)
            # Stash chromedriver PID for forceful cleanup if it crashes
            if hasattr(self.driver, "service") and self.driver.service:
                try:
                    self._chromedriver_pid = self.driver.service.process.pid
                except Exception:
                    self._chromedriver_pid = None
            self.driver.set_window_size(400, 720)

            # Cascade position
            x = self.window_offset * 30
            y = self.window_offset * 40
            self.driver.set_window_position(x, y)

            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32'
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['vi-VN','vi','en-US']
});
Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.'
});
"""
                },
            )
            self._log(f"Chrome started at ({x}, {y})", "INFO")
            return True
        except Exception as e:
            self._log(f"Chrome init failed: {e}", "ERROR")
            self.close_driver()
            return False

    # ── GoLike Login ────────────────────────────────────────

    def login_golike(self, username=None, password=None):
        """Đăng nhập tài khoản GoLike."""
        if not username or not password:
            accs = load_accounts()
            if not accs:
                self._log("Không có thông tin đăng nhập!", "ERROR")
                self.close_driver()
                return False

            account_id = str(self.config.get("account_id", "1"))
            if account_id in accs:
                target_acc = accs[account_id]
            else:
                target_acc = next(iter(accs.values()))

            username = target_acc.get("tk")
            password = target_acc.get("mk")

        if not username or not password:
            self._log("Tài khoản hoặc mật khẩu trống!", "ERROR")
            self.close_driver()
            return False

        try:
            self._log(f"Login GoLike: {username}")
            self.driver.get("https://app.golike.net/login")
            wait = WebDriverWait(self.driver, 12)

            tk_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="text"].form-control')))
            tk_input.clear()
            tk_input.send_keys(username)

            mk_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="password"].form-control')))
            mk_input.clear()
            mk_input.send_keys(password)

            self.account_name = username

            # Captcha switch trick
            try:
                switch_btn = WebDriverWait(self.driver, 4).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.captcha-switch__link'))
                )
                switch_btn.click()
                self._interaction_sleep()
                switch_btn = WebDriverWait(self.driver, 4).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.captcha-switch__link'))
                )
                switch_btn.click()
                self._interaction_sleep()
                self._interaction_sleep()
            except Exception:
                pass

            dn_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]')))
            dn_btn.click()
            self._interaction_sleep()
            self._log(f"Logged in: {username}", "SUCCESS")
            return True
        except Exception as e:
            self._log(f"Lỗi đăng nhập: {e}", "ERROR")
            self.close_driver()
            return False

    # ── TikTok Section ──────────────────────────────────────

    def select_tiktok_section(self):
        """Vào TikTok section, chọn acc TikTok từ config (bypass popup)."""
        if not self.driver:
            self._log("Chrome driver not initialized.", "ERROR")
            return False
        try:
            wait = WebDriverWait(self.driver, 10)
            kiemxu = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[text()='Kiếm xu']")))
            kiemxu.click()
            self._interaction_sleep()

            tiktok = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[text()="Tiktok"]')))
            tiktok.click()
            self._interaction_sleep()

            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "tk-account-list")))
            taikhoan = self.driver.find_elements(By.CLASS_NAME, "tk-account-item")

            if not taikhoan:
                self._log("Không tìm thấy tài khoản TikTok nào!", "ERROR")
                return False

            list_acc = []
            for tk in taikhoan:
                try:
                    name_tk = tk.find_element(By.CLASS_NAME, "tk-account-item__name").get_attribute("textContent").strip()
                    if name_tk:
                        list_acc.append(name_tk)
                except Exception:
                    pass

            # Always use preselected tiktok_account from config
            tiktok_target = str(self.config.get("tiktok_account", "")).strip()
            target_index = 0

            if tiktok_target:
                if tiktok_target.isdigit():
                    num = int(tiktok_target)
                    if 1 <= num <= len(list_acc):
                        target_index = num - 1
                else:
                    for idx, acc_name in enumerate(list_acc):
                        clean_acc = acc_name.lower().replace("@", "")
                        clean_target = tiktok_target.lower().replace("@", "")
                        if clean_target == clean_acc or clean_target in clean_acc or clean_acc in clean_target:
                            target_index = idx
                            break

            chosen_name = list_acc[target_index] if target_index < len(list_acc) else list_acc[0]
            self.tiktok_account = chosen_name
            self._log(f"Chọn acc TikTok [{target_index + 1}]: {chosen_name}", "SUCCESS")

            try:
                self.driver.execute_script("arguments[0].click();", taikhoan[target_index])
            except Exception:
                taikhoan[target_index].click()
            self._interaction_sleep()
            return True
        except Exception as e:
            self._log(f"Lỗi chọn TikTok: {e}", "ERROR")
            return False

    def _dump_screen_elements(self, label: str = ""):
        """Dump UI hierarchy of current screen for debugging click failures.
        Quan trọng: chỉ gọi khi click fail — không gọi trong flow bình thường để tránh tốn CPU."""
        if not self.u2_device:
            return
        try:
            self._log(f"[DEBUG-DUMP-{label}] Đang dump UI elements trên màn hình TikTok...", "WARNING")
            # Hàm lấy UI hierarchy dạng XML/text rút gọn
            xml = self.u2_device.dump_hierarchy()
            # Extract key attrs from clickable elements
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            elemens = []
            for el in root.iter("node"):
                attrs = el.attrib
                if attrs.get("clickable") == "true" or attrs.get("checked") == "true":
                    elemens.append(
                        f"  resourceId={attrs.get('resource-id','')} "
                        f"class={attrs.get('class','')} "
                        f"text='{attrs.get('text','')}' "
                        f"contentDesc='{attrs.get('content-desc','')}'"
                    )
            if elemens:
                self._log(f"[DEBUG-DUMP-{label}] Clickable elements (top 20):", "WARNING")
                for e in elemens[:20]:
                    self._log(f"[DEBUG-DUMP-{label}] {e}", "WARNING")
            else:
                self._log(f"[DEBUG-DUMP-{label}] KHÔNG tìm thấy clickable elements nào!", "WARNING")
        except Exception as e:
            self._log(f"[DEBUG-DUMP-{label}] Lỗi dump: {e}", "WARNING")

    # ── Job Logic ───────────────────────────────────────────

    def _solve_golike_puzzle(self):
        """Phát hiện và giải captcha puzzle kéo-thả của GoLike.
        HTML: div.gk-puzzle-card chứa gk-puzzle-board với 3 phần tử:
          - gk-puzzle-token (khối vuông kéo)
          - gk-puzzle-waypoint (vòng nét đứt — kéo qua)
          - gk-puzzle-target (vòng đích — thả vào)
        Returns True nếu giải xong, False nếu không phát hiện puzzle hoặc fail.
        """
        try:
            # Check nhanh presence, nếu có → wait visibility
            card = self.driver.find_elements(By.CSS_SELECTOR, "div.gk-puzzle-card")
            if not card:
                return False  # không có captcha
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.gk-puzzle-card"))
                )
            except TimeoutException:
                self._log("Captcha puzzle không hiển thị sau 5s — bỏ qua.", "WARNING")
                return False

            self._log("Phát hiện captcha GoLike puzzle! Đang giải...", "WARNING")

            # Lấy tọa độ 3 phần tử — dùng .rect (dict: x, y, width, height)
            token = self.driver.find_element(By.CSS_SELECTOR, ".gk-puzzle-token")
            waypoint = self.driver.find_element(By.CSS_SELECTOR, ".gk-puzzle-waypoint")
            target = self.driver.find_element(By.CSS_SELECTOR, ".gk-puzzle-target")

            token_rect = token.rect
            waypoint_rect = waypoint.rect
            target_rect = target.rect

            # Tính tâm mỗi phần tử
            token_center = (
                token_rect["x"] + token_rect["width"] / 2,
                token_rect["y"] + token_rect["height"] / 2,
            )
            waypoint_center = (
                waypoint_rect["x"] + waypoint_rect["width"] / 2,
                waypoint_rect["y"] + waypoint_rect["height"] / 2,
            )
            target_center = (
                target_rect["x"] + target_rect["width"] / 2,
                target_rect["y"] + target_rect["height"] / 2,
            )

            self._log(
                f"Puzzle toạ độ: token=({token_center[0]:.0f},{token_center[1]:.0f}) "
                f"waypoint=({waypoint_center[0]:.0f},{waypoint_center[1]:.0f}) "
                f"target=({target_center[0]:.0f},{target_center[1]:.0f})"
            )

            delta_x1 = waypoint_center[0] - token_center[0]
            delta_y1 = waypoint_center[1] - token_center[1]
            delta_x2 = target_center[0] - waypoint_center[0]
            delta_y2 = target_center[1] - waypoint_center[1]

            steps_per_segment = 20  # ~1s mỗi đoạn với 50ms pause
            step_pause_ms = 50

            def _smooth_drag(actions, total_dx, total_dy, steps):
                """Kéo theo steps bước, dồn residual vào bước cuối để không mất pixel."""
                step_dx = total_dx // steps
                step_dy = total_dy // steps
                residual_x = total_dx - step_dx * steps
                residual_y = total_dy - step_dy * steps
                for i in range(steps):
                    dx = step_dx + (residual_x if i == steps - 1 else 0)
                    dy = step_dy + (residual_y if i == steps - 1 else 0)
                    actions.move_by_offset(dx, dy).pause(step_pause_ms / 1000.0)

            actions = ActionChains(self.driver)
            actions.click_and_hold(token)
            _smooth_drag(actions, delta_x1, delta_y1, steps_per_segment)
            _smooth_drag(actions, delta_x2, delta_y2, steps_per_segment)
            actions.release()
            actions.perform()

            # Đợi puzzle biến mất
            try:
                WebDriverWait(self.driver, 5).until_not(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.gk-puzzle-card"))
                )
            except TimeoutException:
                self._log("Puzzle vẫn hiển thị sau khi drag — thử retry.", "WARNING")
                return False

            self._interaction_sleep()
            self._log("Đã giải captcha GoLike puzzle thành công!", "SUCCESS")
            return True
        except Exception as e:
            self._log(f"Giải captcha puzzle thất bại: {e}", "ERROR")
            return False

    def get_job_tiktok(self):
        """Nhận job TikTok mới."""
        try:
            wait = WebDriverWait(self.driver, 8)
            nhan_job = self.driver.find_element(By.CLASS_NAME, "tk-hero__cta")
            nhan_job.click()
            self._interaction_sleep()

            if self.job_count == 0:
                try:
                    popup_dahieu = wait.until(EC.element_to_be_clickable((By.ID, "agree")))
                    popup_dahieu.click()
                    self._interaction_sleep()
                    popup_dongy = self.driver.find_element(By.CSS_SELECTOR, "button.btn.btn-primary")
                    popup_dongy.click()
                    self._interaction_sleep()
                except Exception:
                    pass

            # Phát hiện và giải captcha puzzle kéo-thả của GoLike
            for attempt in range(2):
                if self._solve_golike_puzzle():
                    self._log(f"Captcha solved on attempt {attempt + 1}.")
                    break
                if attempt == 0:
                    self._log("Retry giải captcha lần 2...", "WARNING")
                    self._interaction_sleep()

            tiktok_icon = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.bg-button-1')))
            link_tiktok = tiktok_icon.get_attribute("href")
            tiktok_icon.click()
            return link_tiktok
        except Exception as e:
            # SweetAlert2 popup xuất hiện khi không nhận được job.
            # Đọc nội dung để phân biệt: giới hạn ngày (150 jobs) vs tạm thời hết job.
            try:
                title_el = self.driver.find_element(By.ID, "swal2-title")
                content_el = self.driver.find_element(By.ID, "swal2-content")
                title = title_el.text.strip() if title_el else ""
                content = content_el.text.strip() if content_el else ""
                popup_msg = f"{title}: {content}" if title else content
                self._log(f"GoLike popup: {popup_msg}", "WARNING")

                # Dismiss popup
                confirm_btn = self.driver.find_element(By.CLASS_NAME, "swal2-confirm")
                confirm_btn.click()

                # Giới hạn jobs/ngày → signal dừng session ngay
                if "quá số jobs" in content or "(150)" in content:
                    return "__DAILY_LIMIT__"
            except Exception:
                self._log(f"Loi nhan job (khong tim thay Nhan job / link): {e}", "WARNING")
            return None

    def skip_job(self, link_tiktok="--"):
        """Báo lỗi skip job."""
        self.current_action = "Đang skip job..."
        self._push_state()
        try:
            skip_btn = self.driver.find_elements(By.XPATH, '//*[contains(text(), "Báo lỗi ")]')
            if skip_btn:
                skip_btn[0].click()
                self._interaction_sleep()
                gui_baocao = self.driver.find_element(By.XPATH, '//button[contains(normalize-space(), "Gửi báo cáo")]')
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", gui_baocao)
                gui_baocao.click()

                try:
                    ok = WebDriverWait(self.driver, 5).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, ".swal2-confirm.swal2-styled"))
                    )
                    ok.click()
                except Exception:
                    pass

                list_tab = self.driver.window_handles
                if len(list_tab) > 1:
                    self.driver.switch_to.window(list_tab[-1])
                    self.driver.close()
                    self.driver.switch_to.window(list_tab[0])

                self.fail_count += 1
                self._log(f"Skipped job: {link_tiktok}", "WARNING")
                loai_job = getattr(self, 'current_job_type', '') or "TikTok"
                job_id = getattr(self, 'current_job_id', '') or "--"
                self._send_history(loai_job, job_id, "FAILED", 0)
        except Exception as e:
            self._log(f"Lỗi skip job: {e}", "ERROR")

    def run_job_cycle(self):
        """Một chu kỳ job. Returns 'SUCCESS' / 'FAILED' / 'SKIPPED'."""
        import subprocess
        start_time = time()

        self.current_job_type = ""
        self.current_job_id = ""

        link_tiktok = self.get_job_tiktok()
        if link_tiktok == "__DAILY_LIMIT__":
            self._log("Đạt giới hạn 150 jobs/ngày từ GoLike. Dừng session.", "WARNING")
            return "LIMIT_REACHED"
        if not link_tiktok:
            self.skip_job()
            return "SKIPPED"

        # Close extra tabs
        list_tab = self.driver.window_handles
        if len(list_tab) > 1:
            self.driver.switch_to.window(list_tab[-1])
            self.driver.close()
            self.driver.switch_to.window(list_tab[0])

        # Job info
        try:
            loai_job_elem = self.driver.find_element(By.CSS_SELECTOR, ".ml-1.d400.font-weight-bold")
            loai_job = loai_job_elem.get_attribute("textContent").strip()
        except Exception:
            loai_job = "Follow"

        try:
            money_elem = self.driver.find_element(By.CLASS_NAME, "font-bold")
            money_str = money_elem.get_attribute("textContent")
            money_val = int(re.findall(r"\d+", money_str)[0])
        except Exception:
            money_val = 0

        try:
            job_id_elem = self.driver.find_element(By.CSS_SELECTOR, ".font-14.d400.col-12.text-center.py-2")
            job_id_str = job_id_elem.get_attribute("textContent")
            job_id = re.findall(r"\d+", job_id_str)[0]
        except Exception:
            job_id = f"ID_{int(time())}"

        self.job_count += 1
        self.current_job_type = loai_job
        self.current_job_id = job_id
        self._log(f"Job #{self.job_count} [{job_id}] - {self.tiktok_account} - {loai_job} ({money_val}đ)")

        # Open TikTok via ADB
        self.current_action = f"Đang mở link {loai_job}..."
        self._push_state()
        try:
            if self.device_id and link_tiktok:
                self._log(f"Mở link TikTok trên thiết bị {self.device_id}: {link_tiktok}", "INFO")
                cmd = [self.adb_path, "-s", self.device_id, "shell", "am", "start",
                       "-a", "android.intent.action.VIEW", "-d", link_tiktok]
                result = subprocess.run(cmd, check=False, capture_output=True, text=True)
                if result.returncode != 0:
                    self._log(f"Lệnh ADB lỗi (code {result.returncode}): {result.stderr.strip()}", "WARNING")
            else:
                self._log(f"Thiếu device_id hoặc link_tiktok để mở ADB", "WARNING")
        except Exception as e:
            self._log(f"Lỗi mở link ADB: {e}", "WARNING")

        # Chọn delay theo loại job
        if "follow" in loai_job.lower():
            delay_open = int(self.config.get("delay_follow", 5))
        elif "favorite" in loai_job.lower():
            delay_open = int(self.config.get("delay_like", 5))
        elif "like" in loai_job.lower():
            delay_open = int(self.config.get("delay_like", 5))
        else:
            delay_open = int(self.config.get("delay_action", 5))
        self._safe_sleep(delay_open)

        # Uiautomator2 click — phân biệt Follow / Like / Favorite
        self.current_action = f"Đang {loai_job.lower()}..."
        self._push_state()
        try:
            if self.u2_device:
                if "like" in loai_job.lower() and "favorite" not in loai_job.lower():
                    # ── Like job: click nút Thích ─────────────────
                    like_btn = self.u2_device(descriptionMatches=r"^Thích.*")
                    if not like_btn.wait(timeout=5):
                        like_btn = self.u2_device(resourceId="com.ss.android.ugc.trill:id/fx6",
                                                   descriptionMatches=r"^Thích.*")
                    if like_btn.exists:
                        like_btn.click()
                        self._log("Clicked Like button!", "SUCCESS")
                    else:
                        self._log("Không tìm thấy nút Like sau 5s — dump UI...", "WARNING")
                        self._dump_screen_elements("LIKE_FAIL")
                elif "favorite" in loai_job.lower():
                    # ── Favorite button: click nút Yêu thích ──────
                    fav_btn = self.u2_device(descriptionContains="Yêu thích")
                    if not fav_btn.wait(timeout=5):
                        fav_btn = self.u2_device(resourceId="com.ss.android.ugc.trill:id/hu9")
                    if fav_btn.wait(timeout=5):
                        fav_btn.click()
                        self._log("Clicked Favorite button!", "SUCCESS")
                    else:
                        self._log("Không tìm thấy nút Yêu thích sau 5s — dump UI...", "WARNING")
                        self._dump_screen_elements("FAV_FAIL")
                else:
                    # ── Follow button ────────────────────────────
                    # FIX: UiObject luôn truthy → or không hoạt động. Dùng .exists() thay
                    follow_btn = self.u2_device(text="Follow")
                    if not follow_btn.exists:
                        follow_btn = self.u2_device(text="Theo dõi")
                    if not follow_btn.wait(timeout=5):
                        follow_btn = self.u2_device(resourceId="com.ss.android.ugc.trill:id/fd7")
                    if follow_btn.wait(timeout=5):
                        follow_btn.click()
                        self._log("Clicked Follow button!", "SUCCESS")
                    else:
                        self._log("Không tìm thấy nút Follow sau 5s — dump UI...", "WARNING")
                        self._dump_screen_elements("FOLLOW_FAIL")
        except Exception as e:
            self._log(f"Lỗi uiautomator2: {e}", "WARNING")

        delay_complete = int(self.config.get("delay_complete", 6))
        self._safe_sleep(delay_complete)

        # Complete job on GoLike
        self.current_action = "Đang ấn Hoàn thành..."
        self._push_state()
        try:
            wait = WebDriverWait(self.driver, 10)
            hoanthanh_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[contains(text(), "Hoàn thành ")]')))
            hoanthanh_btn.click()

            hoanthanh_text_elem = wait.until(EC.visibility_of_element_located((By.ID, "swal2-content")))
            hoanthanh_text = hoanthanh_text_elem.get_attribute("textContent").strip()

            ok_btn = self.driver.find_element(By.CSS_SELECTOR, ".swal2-confirm.swal2-styled")
            ok_btn.click()

            if "thành công" in hoanthanh_text.lower():
                self.success_count += 1
                self.total_money += money_val
                self._log(f"✅ Hoàn thành job {job_id}! +{money_val}đ | Total: {self.total_money}đ", "SUCCESS")
                self._send_history(loai_job, job_id, "SUCCESS", money_val)
                return "SUCCESS"
            else:
                self._log(f"GoLike: {hoanthanh_text}", "WARNING")
                self.skip_job(link_tiktok)
                return "FAILED"
        except Exception as e:
            self._log(f"Lỗi hoàn thành: {e}", "ERROR")
            self.skip_job(link_tiktok)
            return "FAILED"

    # ── Full Account Pipeline ───────────────────────────────

    def _run_pipeline(self):
        """Full pipeline cho 1 config account."""
        config = self.config
        account_id = str(config.get("account_id", ""))
        fail_limit = int(config.get("fail_limit", 0))
        rest_after = int(config.get("rest_after_jobs", 0))
        rest_duration = int(config.get("rest_duration_min", 5))
        device_id = config.get("device_id", "")
        tiktok_target = config.get("tiktok_account", "")

        # Delay values are read from self.config at runtime — no shared dashboard needed

        # Credentials
        accs = load_accounts()
        if account_id not in accs:
            self._log(f"Account ID {account_id} không tồn tại!", "ERROR")
            return
        username = accs[account_id].get("tk", "")
        password = accs[account_id].get("mk", "")

        self.current_action = "Đang kết nối thiết bị..."
        self._push_state()
        if not self.connect_device(device_id=device_id if device_id else None):
            return
        self.current_action = "Đang khởi tạo Chrome..."
        self._push_state()
        if not self.init_driver():
            return
        self.current_action = "Đang đăng nhập GoLike..."
        self._push_state()
        if not self.login_golike(username, password):
            return

        self.current_action = "Đang chọn tài khoản TikTok..."
        self._push_state()
        if not self.select_tiktok_section():
            return

        # Job loop
        consecutive_fails = 0
        jobs_since_rest = 0

        while self.running:
            if self.paused:
                self.current_action = "Tạm dừng"
                self._push_state()
                while self.paused and self.running:
                    if self._should_stop():
                        break
                    self._safe_sleep(1)
                if not self.running:
                    break

            self.current_action = "Đang lấy job..."
            self._push_state()

            # Driver health check — nếu Chrome bị tắt từ ngoài, dừng ngay
            if not self._is_driver_alive():
                self._log("Chrome không phản hồi — dừng session.", "ERROR")
                self.running = False
                break

            try:
                result = self.run_job_cycle()
            except WebDriverException as e:
                self._log(f"Chrome driver mất kết nối — dừng session: {e}", "ERROR")
                self.running = False
                break
            except Exception as e:
                self._log(f"Lỗi job cycle: {e}", "ERROR")
                result = "FAILED"

            if result == "SUCCESS":
                consecutive_fails = 0
                jobs_since_rest += 1
                if rest_after > 0 and jobs_since_rest >= rest_after:
                    if not self._rest_for_duration(rest_duration):
                        break
                    jobs_since_rest = 0
            elif result == "LIMIT_REACHED":
                # GoLike báo giới hạn 150 jobs/ngày — dừng session ngay.
                self._log("Đạt giới hạn jobs/ngày. Dừng session.", "INFO")
                break
            elif result == "SKIPPED":
                # "SKIPPED" = hết job hoặc job không khả dụng — không phải lỗi thực sự.
                # Dùng fail_limit làm ngưỡng skip luôn (nếu có) hoặc default 4.
                skip_limit = max(fail_limit, 4) if fail_limit > 0 else 4
                consecutive_fails += 1
                if consecutive_fails >= skip_limit:
                    self._log(f"Hết job khả dụng ({consecutive_fails} lần skip liên tiếp). Dừng.", "INFO")
                    break
            elif result == "FAILED":
                consecutive_fails += 1
                if fail_limit > 0 and consecutive_fails >= fail_limit:
                    self._log(f"Đạt giới hạn {fail_limit} fail liên tiếp. Dừng.", "WARNING")
                    break

            # Delay between jobs
            delay_min = int(self.config.get("delay_job_min", 8))
            delay_max = int(self.config.get("delay_job_max", 14))
            delay_sec = random.randint(delay_min, delay_max)
            self.current_action = f"Chờ job tiếp... {delay_sec}s"
            self._push_state()
            if not self._safe_sleep(delay_sec):
                break

        # Cleanup
        self.current_action = "Đang cleanup..."
        self.close_driver()
        self.u2_device = None
        self.device_id = None
        self._log(f"Done: {self.account_name} — {self.success_count} success / {self.fail_count} fail / {self.total_money}đ", "INFO")

    def _rest_for_duration(self, minutes: int):
        """Nghỉ X phút. Returns True if rest completed, False if stopped."""
        self._log(f"Nghỉ {minutes} phút...", "INFO")
        self.current_action = f"Đang nghỉ {minutes}p..."
        self._push_state()
        seconds = minutes * 60
        if not self._safe_sleep(seconds):
            return False
        self._log("Hết thời gian nghỉ.", "INFO")
        self.current_action = "Đang lấy job..."
        self._push_state()
        return True

    # ── Main entry ──────────────────────────────────────────

    def run(self):
        """Entry point called in new process by SessionManager."""
        self.running = True
        self._log(f"Started (PID {os.getpid()}) — acc #{self.config.get('account_id', '?')}", "INFO")
        try:
            self._run_pipeline()
        except Exception as e:
            self._log(f"FATAL: {e}", "ERROR")
        finally:
            self.running = False
            self._push_state()
            self.close_driver()