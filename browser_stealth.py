"""
Shared anti-detection CDP script for Chrome/Selenium.
Inject via Page.addScriptToEvaluateOnNewDocument BEFORE any page load.
Covers: Cloudflare Turnstile, DataDome, Akamai, reCAPTCHA, and general bot detection.
"""
import random

# ── User-Agent rotation pool (recent Windows Chrome versions) ──
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7871.127 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7911.96 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7593.144 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.7012.122 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.6587.98 Safari/537.36",
]

# ── Chrome startup flags (merged with existing) ──
CHROME_FLAGS = [
    "--disable-blink-features=AutomationControlled",
    "--remote-debugging-port=0",
    "--disable-features=Translate,OptimizationGuideModelDownloading,OptimizationHints",
    "--disable-component-extensions",
    "--disable-component-update",
    "--disable-sync",
    "--disable-background-networking",
    "--disable-client-side-phishing-detection",
    "--disable-default-apps",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-breakpad",
    "--password-store=basic",
    "--use-mock-keychain",
]

# ── CDP script: inject before every page load ──
ANTIDETECT_SCRIPT = r"""
// ── Navigator core spoofing ──────────────────────────
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32'
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['vi-VN', 'vi', 'en-US']
});

Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.'
});

// ── Hardware concurrency / device memory ─────────────
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8
});

Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8
});

Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => 0
});

// ── Plugins / MimeTypes (real browser có 3-5 plugins) ──
// Cloudflare checks navigator.plugins.length > 0 to rule out headless
(function() {
    try {
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                if (navigator._cachedPlugins) return navigator._cachedPlugins;
                const proto = Object.getPrototypeOf(navigator.plugins);
                const arr = Object.create(proto);
                const p = {
                    name: 'Chrome PDF Plugin',
                    filename: 'internal-pdf-viewer',
                    description: 'Portable Document Format',
                    length: 1,
                    item: function() { return undefined; },
                    namedItem: function() { return undefined; },
                };
                arr[0] = p;
                arr[1] = p;
                arr[2] = p;
                Object.defineProperty(arr, 'length', { value: 3 });
                navigator._cachedPlugins = arr;
                return arr;
            }
        });
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => {
                if (navigator._cachedMimeTypes) return navigator._cachedMimeTypes;
                const proto = Object.getPrototypeOf(navigator.mimeTypes);
                const arr = Object.create(proto);
                Object.defineProperty(arr, 'length', { value: 3 });
                navigator._cachedMimeTypes = arr;
                return arr;
            }
        });
    } catch(e) { /* silent fail — non-critical */ }
})();

// ── Chrome runtime (window.chrome) ──────────────────
if (!window.chrome) {
    window.chrome = {};
}
if (!window.chrome.runtime) {
    window.chrome.runtime = {};
}
if (!window.chrome.app) {
    window.chrome.app = { isInstalled: false };
}
window.chrome.loadTimes = function() {};

// ── Permissions / Notifications ─────────────────────
const _origQuery = window.navigator.permissions.query;
window.navigator.permissions.__proto__.query = function(parameters) {
    if (parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
    }
    return _origQuery.call(this, parameters);
};

// ── Screen resolution match window size ─────────────
Object.defineProperty(screen, 'width', {
    get: () => window.outerWidth
});
Object.defineProperty(screen, 'height', {
    get: () => window.outerHeight
});
Object.defineProperty(screen, 'availWidth', {
    get: () => window.outerWidth
});
Object.defineProperty(screen, 'availHeight', {
    get: () => window.outerHeight - 40 // taskbar
});

// ── Network info ────────────────────────────────────
try {
    if (navigator.connection) {
        Object.defineProperty(navigator.connection, 'rtt', {
            get: () => 50 + Math.floor(Math.random() * 30)
        });
    }
} catch(e) {}

// ── Canvas fingerprint noise ────────────────────────
// Injects subtle noise into canvas output so hash-based fingerprinting fails.
// Guard: use a flag to prevent re-entry (toDataURL may internally call getImageData).
try {
    const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        if (this._noising) return _origToDataURL.apply(this, arguments);
        this._noising = true;
        try {
            const ctx = this.getContext('2d', { willReadFrequently: true });
            if (ctx && this.width > 0 && this.height > 0) {
                const imageData = ctx.getImageData(0, 0, this.width, this.height);
                const len = imageData.data.length;
                const step = Math.max(1, Math.floor(len / 200));
                for (let i = step - 1; i < len; i += step) {
                    imageData.data[i] = imageData.data[i] ^ 1;
                }
                ctx.putImageData(imageData, 0, 0);
            }
        } catch(e) {}
        this._noising = false;
        return _origToDataURL.apply(this, arguments);
    };
} catch(e) {}

try {
    const _origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
        const imageData = _origGetImageData.call(this, x, y, w, h);
        try {
            const len = imageData.data.length;
            const step = Math.max(1, Math.floor(len / 200));
            for (let i = step - 1; i < len; i += step) {
                imageData.data[i] = imageData.data[i] ^ 1;
            }
        } catch(e) {}
        return imageData;
    };
} catch(e) {}

// ── WebGL fingerprint spoof (reported GPU: Apple M1 GPU compatible) ──
(function() {
    try {
        const _origGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {
            if (p === 37445) return 'Google Inc. (Apple)';
            if (p === 37446) return 'ANGLE (Apple, Apple M1, OpenGL 4.1)';
            return _origGetParameter.call(this, p);
        };
    } catch(e) {}
})();

// ── AudioContext fingerprint noise ──────────────────
(function() {
    try {
        if (typeof AudioContext !== 'undefined') {
            const _origCreateOscillator = AudioContext.prototype.createOscillator;
            // Override only if exists; just tiny noise to oscillator frequency
            if (_origCreateOscillator) {
                AudioContext.prototype.createOscillator = function() {
                    const osc = _origCreateOscillator.call(this);
                    if (osc.frequency) {
                        const origSet = Object.getOwnPropertyDescriptor(osc.frequency.__proto__, 'value');
                        if (origSet && origSet.set) {
                            const origSetter = origSet.set;
                            Object.defineProperty(osc.frequency, 'value', {
                                get: function() { return origSet.get ? origSet.get.call(this) : 440; },
                                set: function(v) { origSetter.call(this, v + (Math.random() - 0.5) * 0.1); }
                            });
                        }
                    }
                    return osc;
                };
            }
        }
    } catch(e) {}
})();

// ── Intl pass-through (locale fingerprint stays real) ──
// Cloudflare checks navigator.languages against Intl.DateTimeFormat
// Already set languages above — Intl will match

// ── Clean up automation traces ─────────────────────
try {
    const _prefix = 'cdc_adoQpoasnfa76pfcZLmcfl_';
    delete window[_prefix + 'Array'];
    delete window[_prefix + 'Promise'];
    delete window[_prefix + 'Symbol'];
    delete window[_prefix + 'JSON'];
    delete window[_prefix + 'Proxy'];
} catch(e) {}
"""


def get_random_user_agent() -> str:
    """Chọn ngẫu nhiên 1 UA trong pool."""
    return random.choice(USER_AGENTS)


def get_chrome_options_flags() -> list[str]:
    """Trả về list Chrome startup flags."""
    return list(CHROME_FLAGS)


def get_antidetect_script() -> str:
    """Trả về CDP script JavaScript."""
    return ANTIDETECT_SCRIPT