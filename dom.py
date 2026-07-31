import sys
import os
import re
import json
import random
import subprocess
import threading
from time import sleep, time
from datetime import datetime
from datetime import datetime

# Safe sys.path insertion for golike_core imports
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

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import uiautomator2 as u2

from dashboard import dashboard, logs, history, add_log, add_history, load_accounts, load_tiktok_cache, save_tiktok_cache
from session_manager import manager as session_manager

class GoLikeBot:
    def __init__(self, adb_path: str = r"E:\pythonadb\ADB\adb.exe"):
        self.adb_path = adb_path
        self.driver = None
        self.u2_device = None
        self.device_id = None
        self.account_name = ""
        self.tiktok_account = ""
        self.running = False
        self.paused = False
        self.bot_thread = None
        self.stt_job = 0
        self.dem = 0
        self.tong_tien = 0

    def close_driver(self):
        """Đóng Chrome ngay lập tức khi phát sinh lỗi"""
        if self.driver:
            try:
                self.driver.quit()
                add_log("Đã tự động đóng Trình duyệt Chrome.", "INFO")
            except Exception:
                pass
            self.driver = None

    def _interaction_sleep(self):
        """Delay giữa các thao tác Chrome DOM để tránh thao tác quá nhanh gây lag máy."""
        base = float(dashboard.get("delay_interaction", 1.5))
        jitter = float(dashboard.get("delay_interaction_jitter", 0.5))
        delay = base + random.uniform(-jitter, jitter)
        delay = max(0.3, delay)  # tối thiểu 300ms
        sleep(delay)

    def get_adb_devices(self):
        """Lấy danh sách các thiết bị ADB đang kết nối"""
        devices = []
        try:
            if os.path.exists(self.adb_path):
                cmd = [self.adb_path, "devices"]
            else:
                cmd = ["adb", "devices"]
            output = subprocess.check_output(cmd).decode("utf-8")
            lines = output.strip().split("\n")
            for line in lines[1:]:
                parts = line.split()
                if len(parts) > 1 and parts[1] == "device":
                    devices.append(parts[0])
        except Exception as e:
            add_log(f"Lỗi đọc danh sách ADB devices: {e}", "WARNING")
        return devices

    def connect_device(self, device_id=None):
        """Kết nối tới thiết bị qua uiautomator2"""
        devices = self.get_adb_devices()
        if not devices:
            add_log("Không tìm thấy thiết bị ADB nào đang kết nối!", "ERROR")
            dashboard["device"] = "Không tìm thấy"
            dashboard["available_devices"] = []
            dashboard["selected_device_id"] = ""
            dashboard["pending_device_choice"] = False
            return False

        # Update dashboard with available devices
        dashboard["available_devices"] = devices

        # If device_id is specified and valid, use it
        if device_id and device_id in devices:
            target = device_id
            dashboard["selected_device_id"] = target
            dashboard["pending_device_choice"] = False
        # If we're in multi-account mode or no specific device requested, prompt for selection
        elif len(devices) > 1 and dashboard.get("multi_account_mode", False):
            # In multi-account mode, we'll let the user select via dashboard
            dashboard["selected_device_id"] = ""
            dashboard["pending_device_choice"] = True
            add_log(f"Tìm thấy {len(devices)} thiết bị ADB. Vui lòng chọn thiết bị trên Dashboard.", "INFO")
            return False  # Don't connect yet, wait for user selection
        else:
            # Single device or not in multi-account mode, use selected device if available, else first device
            selected = dashboard.get("selected_device_id", "").strip()
            if selected and selected in devices:
                target = selected
            else:
                target = devices[0]
            dashboard["selected_device_id"] = target
            dashboard["pending_device_choice"] = False

        try:
            self.u2_device = u2.connect(target)
            self.device_id = target
            dashboard["device"] = target
            add_log(f"Đã kết nối thành công ADB device: {target}", "INFO")
            return True
        except Exception as e:
            add_log(f"Lỗi kết nối uiautomator2 tới {target}: {e}", "ERROR")
            return False

    def init_driver(self):
        """Khởi tạo Chrome Selenium với các option chống phát hiện automation (AntiDetect & CDP overrides)"""
        try:
            options = Options()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.7871.127 Safari/537.36"
            )
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_window_size(400, 720)
            
            # Khởi chạy CDP Script overrides trước khi website load
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
            add_log("Khởi chạy Chrome AntiDetect (CDP inject navigator.webdriver = undefined) thành công.", "INFO")
            return True
        except Exception as e:
            add_log(f"Khởi chạy Trình duyệt thất bại: {e}", "ERROR")
            self.close_driver()
            return False

    def login_golike(self, username=None, password=None):
        """Đăng nhập tài khoản GoLike"""
        if not username or not password:
            accs = load_accounts()
            if not accs:
                add_log("Chưa có thông tin đăng nhập trong datagolike.json!", "ERROR")
                self.close_driver()
                return False

            selected_id = str(dashboard.get("selected_account_id", "1"))
            if selected_id in accs:
                target_acc = accs[selected_id]
            else:
                target_acc = next(iter(accs.values()))

            username = target_acc.get("tk")
            password = target_acc.get("mk")

        if not username or not password:
            add_log("Tài khoản hoặc mật khẩu trống trong datagolike.json!", "ERROR")
            self.close_driver()
            return False

        try:
            add_log(f"Đang mở trang đăng nhập GoLike cho tk: {username}...", "INFO")
            self.driver.get("https://app.golike.net/login")
            wait = WebDriverWait(self.driver, 12)
            
            tk_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="text"].form-control')))
            tk_input.clear()
            tk_input.send_keys(username)

            mk_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="password"].form-control')))
            mk_input.clear()
            mk_input.send_keys(password)
            
            self.account_name = username
            dashboard["account"] = username

            # Mẹo chuyển đổi Captcha
            try:
                add_log("Bắt đầu thực hiện auto-switch Captcha...", "INFO")
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
            except Exception as e:
                add_log(f"Bỏ qua mẹo captcha: {e}", "WARNING")

            # Click nút đăng nhập
            dn_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]')))
            dn_btn.click()
            self._interaction_sleep()
            add_log(f"Đã đăng nhập GoLike thành công: {username}", "SUCCESS")
            return True
        except Exception as e:
            add_log(f"Lỗi đăng nhập GoLike: {e}", "ERROR")
            self.close_driver()
            return False

    def select_tiktok_section(self, skip_choice=False):
        """Vào mục Kiếm Xu -> TikTok, quét danh sách acc rồi chờ user chọn qua Dashboard popup.
        Nếu skip_choice=True, chỉ quét danh sách — không chờ chọn (dùng cho scan standalone)."""
        if not self.driver:
            add_log("Chrome driver is not initialized. Cannot select TikTok section.", "ERROR")
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
                add_log("Không tìm thấy tài khoản TikTok nào trong danh sách!", "ERROR")
                return False

            list_acc = []
            for tk in taikhoan:
                try:
                    name_tk = tk.find_element(By.CLASS_NAME, "tk-account-item__name").get_attribute("textContent").strip()
                    if name_tk:
                        list_acc.append(name_tk)
                except Exception:
                    pass

            dashboard["tiktok_accounts"] = list_acc

            if skip_choice:
                add_log(f"Quét nhanh {len(list_acc)} acc TikTok — không chờ chọn.", "INFO")
                return True

            # Fast path: nếu đã có selected_tiktok_account được đặt trước (wizard/queue)
            # thì tìm match ngay, không cần popup
            pre_selected = str(dashboard.get("selected_tiktok_account", "")).strip()
            if pre_selected:
                add_log(f"Acc TikTok đã được chọn trước: {pre_selected}. Bỏ qua popup.", "INFO")
                dashboard["pending_tiktok_choice"] = False
                # Match logic replicated inline
                target_index = 0
                found = False
                if pre_selected.isdigit():
                    num = int(pre_selected)
                    if 1 <= num <= len(list_acc):
                        target_index = num - 1
                        found = True
                if not found:
                    for idx, acc_name in enumerate(list_acc):
                        clean_acc = acc_name.lower().replace("@", "")
                        clean_target = pre_selected.lower().replace("@", "")
                        if clean_target == clean_acc or clean_target in clean_acc or clean_acc in clean_target:
                            target_index = idx
                            found = True
                            break
                chosen_name = list_acc[target_index] if target_index < len(list_acc) else list_acc[0]
                add_log(f"✅ Đã chọn tài khoản TikTok [{target_index + 1}]: {chosen_name}", "SUCCESS")
            else:
                dashboard["pending_tiktok_choice"] = True   # Báo cho Dashboard hiện popup
                add_log(f"Quét thành công {len(list_acc)} tài khoản TikTok trên GoLike:", "INFO")
                for i, a_n in enumerate(list_acc, 1):
                    add_log(f"  [{i}] 🆔 : {a_n}", "INFO")
                add_log("⏳ Đang chờ bạn chọn tài khoản TikTok trên Dashboard...", "WARNING")

                # ── Chờ cho đến khi biến selected bên dashboard được thiết lập (tối đa 120 giây) ──────────────────
                timeout = 120
                wept = 0
                while wept < timeout:
                    if not self.running:
                        add_log("Bot bị dừng trong khi chờ chọn acc TikTok.", "WARNING")
                        dashboard["pending_tiktok_choice"] = False
                        return False

                    choice_raw = str(dashboard.get("selected_tiktok_account", "")).strip()
                    if choice_raw:
                        break
                    sleep(1)
                    wept += 1

                dashboard["pending_tiktok_choice"] = False

                if wept >= timeout:
                    add_log("⚠️ Hết thời gian chờ chọn acc TikTok! Tự động dùng acc đầu tiên.", "WARNING")
                    target_index = 0
                    chosen_name = list_acc[0] if list_acc else "Acc TikTok 1"
                else:
                    choice_raw = str(dashboard.get("selected_tiktok_account", "")).strip()
                    choice_lower = choice_raw.lower()
                    target_index = 0
                    found = False

                    # Khớp theo STT
                    if choice_lower.isdigit():
                        num = int(choice_lower)
                        if 1 <= num <= len(list_acc):
                            target_index = num - 1
                            found = True

                    # Khớp theo username
                    if not found:
                        for idx, acc_name in enumerate(list_acc):
                            clean_acc = acc_name.lower().replace("@", "")
                            clean_target = choice_lower.replace("@", "")
                            if clean_target == clean_acc or clean_target in clean_acc or clean_acc in clean_target:
                                target_index = idx
                                found = True
                                break

                    chosen_name = list_acc[target_index] if target_index < len(list_acc) else list_acc[0]
                    add_log(f"✅ Đã chọn tài khoản TikTok [{target_index + 1}]: {chosen_name}", "SUCCESS")

            self.tiktok_account = chosen_name
            dashboard["account"] = f"{self.account_name} ({chosen_name})"

            # Click chọn tài khoản trên GoLike web
            try:
                self.driver.execute_script("arguments[0].click();", taikhoan[target_index])
            except Exception:
                taikhoan[target_index].click()
            self._interaction_sleep()
            return True
        except Exception as e:
            add_log(f"Lỗi chọn mục TikTok: {e}", "ERROR")
            return False

    def get_job_tiktok(self):
        """Nhận job TikTok mới"""
        try:
            wait = WebDriverWait(self.driver, 8)
            nhan_job = self.driver.find_element(By.CLASS_NAME, "tk-hero__cta")
            nhan_job.click()
            self._interaction_sleep()

            if self.stt_job == 0:
                try:
                    popup_dahieu = wait.until(EC.element_to_be_clickable((By.ID, "agree")))
                    popup_dahieu.click()
                    self._interaction_sleep()
                    popup_dongy = self.driver.find_element(By.CSS_SELECTOR, "button.btn.btn-primary")
                    popup_dongy.click()
                    self._interaction_sleep()
                except Exception:
                    pass

            tiktok_icon = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.bg-button-1')))
            link_tiktok = tiktok_icon.get_attribute("href")
            tiktok_icon.click()
            
            dashboard["job"] += 1
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
                add_log(f"GoLike popup: {popup_msg}", "WARNING")

                # Dismiss popup
                confirm_btn = self.driver.find_element(By.CLASS_NAME, "swal2-confirm")
                confirm_btn.click()

                # Giới hạn jobs/ngày → signal dừng session ngay
                if "quá số jobs" in content or "(150)" in content:
                    return "__DAILY_LIMIT__"
            except Exception:
                pass
            return None

    def skip_job(self, link_tiktok="--"):
        """Báo lỗi skip job"""
        try:
            skip_job = self.driver.find_elements(By.XPATH, '//*[contains(text(), "Báo lỗi ")]')
            if skip_job:
                skip_job[0].click()
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
                    
                dashboard["failed"] += 1
                add_log(f"Đã báo lỗi skip job: {link_tiktok}", "WARNING")
                add_history("TikTok", "--", "FAILED", 0)
        except Exception as e:
            add_log(f"Lỗi thao tác skip job: {e}", "ERROR")

    def run_job_cycle(self):
        """Thực thi 1 chu kỳ làm job TikTok. Returns 'SUCCESS', 'FAILED', or 'SKIPPED'."""
        start_time = time()
        dashboard["current_action"] = "🟢 Đang lấy job mới..."
        link_tiktok = self.get_job_tiktok()

        if link_tiktok == "__DAILY_LIMIT__":
            add_log("Đạt giới hạn 150 jobs/ngày từ GoLike. Dừng session.", "WARNING")
            return "LIMIT_REACHED"

        if not link_tiktok:
            dashboard["current_action"] = "⚠️ Không có job - Đang bỏ qua..."
            add_log("Không lấy được job mới, đang thử skip...", "WARNING")
            self.skip_job()
            return "SKIPPED"

        # Chuyển tab nếu mở tab mới
        list_tab = self.driver.window_handles
        if len(list_tab) > 1:
            self.driver.switch_to.window(list_tab[-1])
            self.driver.close()
            self.driver.switch_to.window(list_tab[0])

        # Lấy thông tin job
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

        # Cập nhật dashboard thông tin job hiện tại
        dashboard["job_type"] = loai_job
        dashboard["job_id"] = str(job_id)
        dashboard["reward"] = money_val
        dashboard["status"] = "RUNNING"
        
        self.dem += 1
        add_log(f"Bắt đầu Job #{self.dem} [{job_id}] - {loai_job} ({money_val}đ)", "INFO")

        # Mở link TikTok qua ADB intent
        dashboard["current_action"] = f"📲 Đang mở TikTok ({loai_job})..."
        try:
            if self.device_id:
                cmd = [self.adb_path if os.path.exists(self.adb_path) else "adb",
                       "-s", self.device_id, "shell", "am", "start",
                       "-a", "android.intent.action.VIEW", "-d", link_tiktok]
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                add_log(f"Đã mở TikTok trên điện thoại ADB...", "INFO")
        except Exception as e:
            add_log(f"Lỗi mở link bằng ADB: {e}", "WARNING")

        # Chọn delay theo loại job
        if "follow" in loai_job.lower():
            delay_open = int(dashboard.get("delay_follow", 5))
        elif "favorite" in loai_job.lower():
            delay_open = int(dashboard.get("delay_like", 5))
        elif "like" in loai_job.lower():
            delay_open = int(dashboard.get("delay_like", 5))
        else:
            delay_open = int(dashboard.get("delay_action", 5))
        sleep(delay_open)

        # Thao tác uiautomator2 trên điện thoại — phân biệt Follow vs Like
        try:
            if self.u2_device:
                if "like" in loai_job.lower() and "favorite" not in loai_job.lower():
                    # ── Like job: click nút Thích ─────────────────
                    like_btn = self.u2_device(descriptionMatches=r"^Thích.*")
                    if not like_btn.exists:
                        like_btn = self.u2_device(resourceId="com.ss.android.ugc.trill:id/fx6",
                                                   descriptionMatches=r"^Thích.*")
                    if like_btn.exists:
                        like_btn.click()
                        add_log("Đã click nút Thích (Like) trên TikTok!", "SUCCESS")
                    else:
                        add_log("Không tìm thấy nút Like trên màn hình app", "WARNING")
                elif "favorite" in loai_job.lower():
                    # ── Favorite job: click nút Yêu thích ─────────
                    fav_btn = self.u2_device(descriptionContains="Yêu thích")
                    if not fav_btn.exists:
                        fav_btn = self.u2_device(resourceId="com.ss.android.ugc.trill:id/hu9")
                    if fav_btn.exists:
                        fav_btn.click()
                        add_log("Đã click nút Yêu thích (Favorite) trên TikTok!", "SUCCESS")
                    else:
                        add_log("Không tìm thấy nút Yêu thích trên màn hình app", "WARNING")
                else:
                    # ── Follow / job khác: click nút Follow ──────
                    # FIX: uiautomator2 UiObject luôn truthy → or không hoạt động
                    follow_btn = self.u2_device(text="Follow")
                    if not follow_btn.exists:
                        follow_btn = self.u2_device(text="Theo dõi")
                    if follow_btn.exists:
                        follow_btn.click()
                        add_log("Đã click nút Follow trên ứng dụng TikTok!", "SUCCESS")
                    else:
                        if self.u2_device(resourceId="com.ss.android.ugc.trill:id/fd7").exists:
                            self.u2_device(resourceId="com.ss.android.ugc.trill:id/fd7").click()
                            add_log("Đã click nút TikTok bằng resourceId", "SUCCESS")
                        else:
                            add_log("Không tìm thấy nút Follow trên màn hình app — có thể TikTok đã đổi UI", "WARNING")
        except Exception as e:
            add_log(f"Lỗi thao tác uiautomator2: {e}", "WARNING")

        # Chờ sau khi click
        delay_complete = int(dashboard.get("delay_complete", 6))
        dashboard["current_action"] = f"⏳ Chờ {delay_complete}s sau khi click..."
        sleep(delay_complete)

        # Hoàn thành job trên GoLike
        dashboard["current_action"] = "✅ Đang xác nhận hoàn thành job..."
        try:
            wait = WebDriverWait(self.driver, 10)
            hoanthanh_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[contains(text(), "Hoàn thành ")]')))
            hoanthanh_btn.click()

            hoanthanh_text_elem = wait.until(EC.visibility_of_element_located((By.ID, "swal2-content")))
            hoanthanh_text = hoanthanh_text_elem.get_attribute("textContent").strip()

            ok_btn = self.driver.find_element(By.CSS_SELECTOR, ".swal2-confirm.swal2-styled")
            ok_btn.click()

            if "thành công" in hoanthanh_text.lower():
                dashboard["success"] += 1
                dashboard["money"] += money_val
                self.tong_tien += money_val
                self.stt_job += 1
                dashboard["current_action"] = f"💰 Hoàn thành! +{money_val}đ | Tổng: {self.tong_tien}đ"
                add_log(f"✅ Hoàn thành xuất sắc job {job_id}! +{money_val}đ", "SUCCESS")
                add_history(loai_job, job_id, "SUCCESS", money_val)
                return "SUCCESS"
            else:
                dashboard["current_action"] = "❌ Job thất bại - Đang skip..."
                add_log(f"Thông báo GoLike: {hoanthanh_text}", "WARNING")
                self.skip_job(link_tiktok)
                return "FAILED"
        except Exception as e:
            dashboard["current_action"] = "❌ Lỗi hoàn thành - Đang skip..."
            add_log(f"Không tìm thấy hoặc không click được nút Hoàn Thành: {e}", "ERROR")
            self.skip_job(link_tiktok)
            return "FAILED"

    def _run_one_account_config(self, config: dict):
        """Chạy bot cho 1 cấu hình acc cụ thể từ wizard/queue.
        Hỗ trợ fail_limit, rest_cycle, và delay override per-account."""
        account_id = str(config.get("account_id", ""))
        fail_limit = int(config.get("fail_limit", 0))
        rest_after = int(config.get("rest_after_jobs", 0))
        rest_duration = int(config.get("rest_duration_min", 5))
        device_id = config.get("device_id", "")
        tiktok_target = config.get("tiktok_account", "")

        # Áp dụng delay override nếu có, nếu không giữ dashboard default
        for key in ["delay_action", "delay_complete", "delay_like", "delay_follow",
                     "delay_job_min", "delay_job_max"]:
            if config.get(key) is not None:
                dashboard[key] = config[key]

        # Lấy credentials
        accs = load_accounts()
        if account_id not in accs:
            add_log(f"Account ID {account_id} không tồn tại trong datagolike.json!", "ERROR")
            return False
        username = accs[account_id].get("tk", "")
        password = accs[account_id].get("mk", "")
        if not username or not password:
            add_log(f"Tài khoản ID {account_id} thiếu thông tin đăng nhập!", "ERROR")
            return False

        dashboard["selected_account_id"] = account_id
        dashboard["account"] = username
        add_log(f"Đang xử lý tài khoản GoLike: {username} (ID: {account_id})", "INFO")

        # Kết nối thiết bị
        if not self.connect_device(device_id=device_id if device_id else None):
            add_log(f"Không thể kết nối thiết bị cho tài khoản {username}", "ERROR")
            return False

        # Khởi tạo driver và đăng nhập
        if not self.init_driver():
            add_log(f"Không thể khởi tạo trình duyệt cho tài khoản {username}", "ERROR")
            return False

        if not self.login_golike(username, password):
            add_log(f"Đăng nhập thất bại cho tài khoản {username}", "ERROR")
            return False

        # Đặt acc TikTok ưu tiên
        if tiktok_target:
            dashboard["selected_tiktok_account"] = tiktok_target

        # Chọn section TikTok
        if not self.select_tiktok_section():
            add_log(f"Không thể chọn tài khoản TikTok cho tài khoản {username}", "ERROR")
            return False

        # Job loop với fail_limit và rest_cycle
        consecutive_fails = 0
        jobs_since_rest = 0
        dashboard["consecutive_failures"] = 0

        add_log(f"Bắt đầu job loop: fail_limit={fail_limit}, rest_after={rest_after}, rest_duration={rest_duration}ph", "INFO")
        while self.running:
            if self.paused:
                dashboard["status"] = "PAUSED"
                while self.paused and self.running:
                    sleep(1)
                if not self.running:
                    break
                dashboard["status"] = "RUNNING"

            dashboard["status"] = "RUNNING"
            try:
                result = self.run_job_cycle()
            except Exception as e:
                add_log(f"Lỗi trong job cycle: {e}", "ERROR")
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
                add_log("Đạt giới hạn jobs/ngày. Dừng session.", "INFO")
                break
            elif result == "SKIPPED":
                # "SKIPPED" = hết job hoặc job không khả dụng — không phải lỗi thực sự.
                skip_limit = max(fail_limit, 4) if fail_limit > 0 else 4
                consecutive_fails += 1
                dashboard["consecutive_failures"] = consecutive_fails
                if consecutive_fails >= skip_limit:
                    add_log(f"Hết job khả dụng ({consecutive_fails} lần skip liên tiếp). Dừng tài khoản {username}.", "INFO")
                    break
            elif result == "FAILED":
                consecutive_fails += 1
                dashboard["consecutive_failures"] = consecutive_fails
                if fail_limit > 0 and consecutive_fails >= fail_limit:
                    add_log(f"Đạt giới hạn {fail_limit} thất bại liên tiếp. Dừng tài khoản {username}.", "WARNING")
                    break

            # Delay giữa các job
            delay_min = int(dashboard.get("delay_job_min", 8))
            delay_max = int(dashboard.get("delay_job_max", 14))
            delay_sec = random.randint(delay_min, delay_max)
            for s in range(delay_sec, 0, -1):
                if not self.running:
                    break
                dashboard["current_action"] = f"⏱️ Chờ job tiếp theo... {s}s"
                sleep(1)

        # Cleanup
        self.close_driver()
        self.u2_device = None
        self.device_id = None
        dashboard["consecutive_failures"] = 0
        add_log(f"Hoàn tất xử lý tài khoản {username}.", "INFO")
        return True

    def _rest_for_duration(self, minutes: int):
        """Nghỉ X phút trước khi resume. Poll stop signal. Returns True nếu nghỉ xong tự nhiên, False nếu bị stop."""
        add_log(f"🔔 Bắt đầu nghỉ: {minutes} phút.", "INFO")
        dashboard["status"] = "RESTING"
        seconds = minutes * 60
        for s in range(seconds, 0, -1):
            if not self.running:
                dashboard["status"] = "STOPPED"
                add_log("Bot dừng trong thời gian nghỉ.", "WARNING")
                return False
            dashboard["current_action"] = f"💤 Nghỉ... {s // 60}m {s % 60}s"
            sleep(1)
        dashboard["status"] = "RUNNING"
        add_log("Hết thời gian nghỉ. Resume làm job.", "INFO")
        return True

    def scan_tiktok_for_account(self, username: str, password: str, account_id: str | None = None):
        """Quét danh sách acc TikTok của 1 acc GoLike — login, vào TikTok, cache, đăng xuất.
        KHÔNG được gọi khi bot đang chạy.
        account_id: ID GoLike đang quét (cache key). Nếu None → fallback selected_account_id."""
        if not self.connect_device():
            return None
        if not self.init_driver():
            return None
        if not self.login_golike(username, password):
            return None
        if not self.select_tiktok_section(skip_choice=True):
            return None

        accounts = dashboard.get("tiktok_accounts", [])
        scanned_at = datetime.now().isoformat()

        # Cache kết quả — dùng account_id actually being scanned
        cache = load_tiktok_cache()
        cache_key = str(account_id) if account_id else str(dashboard.get("selected_account_id", "1"))
        cache[cache_key] = {
            "scanned_at": scanned_at,
            "accounts": accounts
        }
        save_tiktok_cache(cache)
        dashboard["tiktok_cache"] = cache

        self.close_driver()
        add_log(f"Đã quét và cache {len(accounts)} acc TikTok cho acc GoLogin {username}.", "SUCCESS")
        return {"scanned_at": scanned_at, "accounts": accounts}

    def _process_batch_queue(self):
        """Chạy tuần tự batch_queue: mỗi acc config chạy xong → acc kế."""
        dashboard["status"] = "RUNNING"
        while self.running and len(dashboard.get("batch_queue", [])) > 0:
            if self.paused:
                dashboard["status"] = "PAUSED"
                while self.paused and self.running:
                    sleep(1)
                if not self.running:
                    break
                dashboard["status"] = "RUNNING"

            config = dashboard["batch_queue"].pop(0)
            dashboard["queue_current_config"] = config
            acc_id = config.get("account_id", "?")
            add_log(f"Bắt đầu queue item: acc {acc_id}", "INFO")
            self._run_one_account_config(config)
            if not self.running:
                break

        dashboard["queue_current_config"] = None
        dashboard["status"] = "STOPPED"
        dashboard["current_action"] = "Chờ lệnh"
        self.running = False
        self.paused = False
        add_log("Batch queue hoàn tất hoặc đã dừng.", "SYSTEM")

    def _process_single_account(self, account_id, username, password):
        """[Legacy] Process a single account for the old multi-account mode."""
        dashboard["selected_account_id"] = str(account_id)
        dashboard["account"] = username
        add_log(f"Đang xử lý tài khoản GoLike: {username} (ID: {account_id})", "INFO")

        # Connect device
        if dashboard.get("multi_account_mode", False):
            if not dashboard.get("selected_device_id"):
                add_log(f"Vui lòng chọn thiết bị ADB cho tài khoản {username} trên Dashboard", "WARNING")
                return False
            target_device = dashboard["selected_device_id"]
        else:
            target_device = None

        if not self.connect_device(device_id=target_device):
            add_log(f"Không thể kết nối thiết bị cho tài khoản {username}", "ERROR")
            return False

        if not self.init_driver():
            add_log(f"Không thể khởi tạo trình duyệt cho tài khoản {username}", "ERROR")
            return False

        if not self.login_golike(username, password):
            add_log(f"Đăng nhập thất bại cho tài khoản {username}", "ERROR")
            return False

        if not self.select_tiktok_section():
            add_log(f"Không thể chọn tài khoản TikTok cho tài khoản {username}", "ERROR")
            return False

        jobs_done = 0
        while self.running:
            if self.paused:
                dashboard["status"] = "PAUSED"
                while self.paused and self.running:
                    sleep(1)
                if not self.running:
                    break
                dashboard["status"] = "RUNNING"

            dashboard["status"] = "RUNNING"
            try:
                self.run_job_cycle()
                jobs_done += 1
                jobs_per_account = int(dashboard.get("jobs_per_account", 0))
                if jobs_per_account > 0 and jobs_done >= jobs_per_account:
                    add_log(f"Đã đạt giới hạn {jobs_per_account} job cho tài khoản {username}", "INFO")
                    break
            except Exception as e:
                add_log(f"Lỗi trong quá trình làm job cho tài khoản {username}: {e}", "ERROR")
                sleep(3)

            delay_min = int(dashboard.get("delay_job_min", 8))
            delay_max = int(dashboard.get("delay_job_max", 14))
            delay_sec = random.randint(delay_min, delay_max)
            for s in range(delay_sec, 0, -1):
                if not self.running:
                    break
                dashboard["current_action"] = f"⏱️ Chờ job tiếp theo... {s}s"
                sleep(1)

        self.close_driver()
        self.u2_device = None
        self.device_id = None
        add_log(f"Hoàn tất xử lý tài khoản {username}", "INFO")
        return True

    def run_all_accounts(self):
        """Iterate over all accounts and process each one."""
        accounts = load_accounts()
        if not accounts:
            add_log("Không có tài khoản GoLike nào để xử lý", "ERROR")
            dashboard["status"] = "STOPPED"
            return

        # Sort accounts by integer ID for consistent order
        sorted_accounts = sorted(accounts.items(), key=lambda x: int(x[0]))
        dashboard["total_accounts"] = len(sorted_accounts)
        dashboard["current_account_index"] = 0

        for idx, (account_id, account_data) in enumerate(sorted_accounts):
            if not self.running:
                break
            dashboard["current_account_index"] = idx
            username = account_data.get("tk", "")
            password = account_data.get("mk", "")
            if not username or not password:
                add_log(f"Tài khoản ID {account_id} thiếu thông tin đăng nhập, bỏ qua", "WARNING")
                continue

            self._process_single_account(account_id, username, password)
            # After processing an account (whether success or failure), we continue to the next if still running

        # After processing all accounts or if stopped
        dashboard["status"] = "STOPPED"
        dashboard["current_action"] = "Chờ lệnh"
        dashboard["multi_account_mode"] = False  # Reset the flag
        dashboard["current_account_index"] = 0
        dashboard["total_accounts"] = 0
        add_log("Hoàn tất xử lý tất cả tài khoản hoặc đã dừng.", "SYSTEM")
        self.stop()

    def bot_loop(self):
        """Vòng lặp chính của Bot"""
        add_log("Khởi chạy Bot Loop...", "SYSTEM")

        # Handle device selection for single account mode
        if not dashboard.get("multi_account_mode", False):
            if not self.connect_device():
                dashboard["status"] = "STOPPED"
                self.stop()
                return
        else:
            # In multi-account mode, device selection happens per account
            pass

        if not self.init_driver():
            dashboard["status"] = "STOPPED"
            self.stop()
            return

        if not self.login_golike():
            dashboard["status"] = "STOPPED"
            self.stop()
            return

        if not self.select_tiktok_section():
            dashboard["status"] = "STOPPED"
            self.stop()
            return

        dashboard["status"] = "RUNNING"
        add_log("Bot đã sẵn sàng và đang chạy tác vụ!", "SUCCESS")

        while self.running:
            if self.paused:
                dashboard["status"] = "PAUSED"
                sleep(1)
                continue

            dashboard["status"] = "RUNNING"
            try:
                self.run_job_cycle()
            except Exception as e:
                add_log(f"Lỗi trong vòng lặp làm job: {e}", "ERROR")
                sleep(3)

            # Delay an toàn giữa các job (lấy từ config dashboard)
            delay_min = int(dashboard.get("delay_job_min", 8))
            delay_max = int(dashboard.get("delay_job_max", 14))
            delay_sec = random.randint(delay_min, delay_max)
            for s in range(delay_sec, 0, -1):
                if not self.running:
                    break
                dashboard["current_action"] = f"⏱️ Chờ job tiếp theo... {s}s"
                sleep(1)

        dashboard["status"] = "STOPPED"
        dashboard["current_action"] = "Chờ lệnh"
        add_log("Bot đã dừng làm việc hoàn toàn.", "SYSTEM")
        self.stop()

    def start(self, config: dict = None):
        """Kích hoạt bot chạy ngầm qua SessionManager.
        Có config → thêm vào batch_queue rồi bắt đầu session.
        Không config + batch_queue có item → feed queue.
        Không config + queue rỗng → chạy legacy bot_loop."""
        if config:
            dashboard["batch_queue"] = [config] + dashboard.get("batch_queue", [])
        if len(dashboard.get("batch_queue", [])) > 0:
            session_manager._feed_queue()
            self.running = True
            dashboard["status"] = "RUNNING"
            add_log("Đã phát lệnh START (parallel mode).", "INFO")
            return True
        else:
            # Legacy single-account mode
            self.running = True
            self.paused = False
            dashboard["status"] = "STARTING"
            self.bot_thread = threading.Thread(target=self.bot_loop, daemon=True)
            self.bot_thread.start()
            add_log("Đã phát lệnh START bot.", "INFO")
            return True

    def pause(self):
        """Tạm dừng / tiếp tục tất cả sessions"""
        if session_manager.sessions:
            # Pause/resume all parallel sessions
            for sid in session_manager.sessions:
                session_manager.pause_session(sid)
            return True
        if self.running:
            self.paused = not self.paused
            status_str = "PAUSED" if self.paused else "RUNNING"
            dashboard["status"] = status_str
            add_log(f"Đã chuyển trạng thái Bot sang: {status_str}", "INFO")
            return True
        return False

    def stop(self):
        """Dừng tất cả sessions và bot."""
        # Kill all parallel sessions first
        session_manager.stop_all()
        # Legacy cleanup
        self.running = False
        self.paused = False
        dashboard["status"] = "STOPPED"
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                add_log(f"Lỗi khi đóng Trình duyệt Chrome: {e}", "ERROR")
            finally:
                self.driver = None
        add_log("Đã phát lệnh STOP bot.", "INFO")
        return True

    def start_multi_account_mode(self):
        """Khích hoạt bot chạy tất cả acc qua parallel sessions."""
        accs = load_accounts()
        if not accs:
            add_log("Không có tài khoản nào!", "ERROR")
            return False

        for acc_id in sorted(accs.keys(), key=lambda x: int(x)):
            config = {
                "account_id": str(acc_id),
                "device_id": "",
                "tiktok_account": "",
                "fail_limit": 0,
                "rest_after_jobs": 0,
                "rest_duration_min": 5
            }
            session_manager.start_session(config)

        dashboard["status"] = "RUNNING"
        add_log(f"Đã khởi chạy {len(accs)} parallel sessions.", "SUCCESS")
        return True

# Instance bot dùng chung
bot_instance = GoLikeBot()

# Override running để check cả parallel sessions
@property
def _is_running(self):
    return self.running or len(session_manager.sessions) > 0

GoLikeBot.is_busy = _is_running

if __name__ == "__main__":
    print("=== Đang khởi chạy GoLike Bot ở chế độ CLI ===")
    bot_instance.start()
    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        bot_instance.stop()