"""
Cloudflare Turnstile / Challenge solver.
Phát hiện và giải Cloudflare challenge khi GoLike redirect.
"""
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains


# ── Detection patterns ──────────────────────────────
CF_INDICATORS = [
    # Turnstile widget (managed mode)
    ("css", "div.cf-turnstile"),
    ("css", "iframe[src*='challenges.cloudflare.com']"),
    ("css", "iframe[src*='challenges.cloudflare.com/cdn-cgi/challenge-platform']"),
    # Challenge page
    ("css", "#challenge-stage"),
    ("css", "div#cf-challenge-running"),
    # Checking browser text
    ("xpath", "//*[contains(text(),'Verifying') and contains(text(),'human')]"),
    ("xpath", "//*[contains(text(),'Verify you are human')]"),
    ("xpath", "//*[contains(text(),'Checking your browser')]"),
    # JS challenge / interstitial
    ("css", "div.cf-browser-verification"),
    ("css", "div#cf-please-wait"),
    # Error page (blocked)
    ("css", "div.error-code"),
    ("css", "div.cf-error-code"),
]


def detect_cloudflare(driver, timeout: float = 2.0) -> bool:
    """Kiểm tra có Cloudflare challenge đang hiển thị không.
    Scan nhanh DOM — không wait. Return True nếu phát hiện."""
    try:
        for method, selector in CF_INDICATORS:
            try:
                if method == "css":
                    els = driver.find_elements(By.CSS_SELECTOR, selector)
                else:
                    els = driver.find_elements(By.XPATH, selector)
                if els:
                    return True
            except Exception:
                continue
        # Check page title for cloudflare
        title = driver.title or ""
        if "just a moment" in title.lower() or "cloudflare" in title.lower():
            return True
        return False
    except Exception:
        return False


def _click_turnstile_checkbox(driver, timeout: float = 10.0) -> bool:
    """Click Turnstile checkbox và đợi tự pass.
    Cloudflare tự verify background — ta chỉ cần click và chờ."""
    try:
        # Find Turnstile iframe
        wait = WebDriverWait(driver, timeout)
        iframe = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='challenges.cloudflare.com']"))
        )
        driver.switch_to.frame(iframe)

        # Click checkbox
        checkbox = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "label.cb-lb, div#checkbox, input[type='checkbox']"))
        )
        checkbox.click()
        driver.switch_to.default_content()

        # Wait for challenge to clear
        for _ in range(20):  # up to 20s
            time.sleep(1)
            if not detect_cloudflare(driver):
                return True
        return not detect_cloudflare(driver)
    except TimeoutException:
        driver.switch_to.default_content()
        return False
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False


def solve_cloudflare(driver, max_attempts: int = 3, log_func=None) -> bool:
    """Phát hiện + giải Cloudflare challenge.
    Trả về True nếu pass, False nếu vẫn bị block hoặc hết retry."""
    def _log(msg, level="WARNING"):
        if log_func:
            log_func(msg, level)

    for attempt in range(1, max_attempts + 1):
        if not detect_cloudflare(driver, timeout=2.0):
            return True  # No challenge visible

        _log(f"Phát hiện Cloudflare challenge! Đang giải (attempt {attempt}/{max_attempts})...")

        try:
            # Strategy 1: Click checkbox
            if _click_turnstile_checkbox(driver, timeout=8.0):
                # Re-check
                time.sleep(1)
                if not detect_cloudflare(driver):
                    _log("Cloudflare challenge passed!")
                    return True
        except Exception:
            pass

        # Strategy 2: If still blocked after checkbox, just wait (sometimes auto-resolves)
        _log("Đợi Cloudflare tự unlock...")
        for i in range(10):
            time.sleep(1)
            if not detect_cloudflare(driver, timeout=1.0):
                _log("Cloudflare tự unlock thành công.", "SUCCESS")
                return True

        # Exponential backoff for next attempt
        if attempt < max_attempts:
            wait_s = 2 ** attempt
            _log(f"Retry #{attempt + 1} sau {wait_s}s...", "INFO")
            time.sleep(wait_s)

    _log(f"Không vượt được Cloudflare sau {max_attempts} lần thử!", "ERROR")
    return False


def _click_interactive(driver, selector: str, method: str = "css") -> bool:
    """Helper: click element if present; return True if successfully clicked."""
    try:
        if method == "xpath":
            el = driver.find_element(By.XPATH, selector)
        else:
            el = driver.find_element(By.CSS_SELECTOR, selector)
        if el.is_displayed():
            el.click()
            return True
    except Exception:
        pass
    return False