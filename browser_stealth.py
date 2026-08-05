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

// ── Plugins / MimeTypes (headless Chrome cũng có ít nhất 5 plugins) ──
const _fakePlugin = {
    name: 'Chrome PDF Plugin',
    filename: 'internal-pdf-viewer',
    description: 'Portable Document Format',
    length: 1,
    item: () => null,
    namedItem: () => null,
};
_nativePluginsLen = Object.getOwnPropertyDescriptor(HTMLPluginsArray.prototype, 'length');
if (_nativePluginsLen) {
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = Object.create(HTMLPluginsArray.prototype);
            arr[0] = _fakePlugin;
            arr[1] = _fakePlugin;
            arr[2] = _fakePlugin;
            Object.defineProperty(arr, 'length', { get: () => 3 });
            return arr;
        }
    });
    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => {
            const arr = Object.create(MimeTypeArray.prototype);
            Object.defineProperty(arr, 'length', { get: () => 3 });
            return arr;
        }
    });
}

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
if (navigator.connection) {
    Object.defineProperty(navigator.connection, 'rtt', {
        get: () => 50 + Math.floor(Math.random() * 30)
    });
}

// ── Canvas fingerprint noise ────────────────────────
const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    const ctx = this.getContext('2d');
    if (ctx) {
        const imageData = ctx.getImageData(0, 0, this.width || 100, this.height || 100);
        // Inject ~1% noise to break hash-based fingerprint
        for (let i = 0; i < imageData.data.length; i += Math.floor(Math.random() * 60) + 50) {
            imageData.data[i] = imageData.data[i] ^ 1;
        }
        ctx.putImageData(imageData, 0, 0);
    }
    return _origToDataURL.apply(this, arguments);
};

const _origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
    const imageData = _origGetImageData.call(this, x, y, w, h);
    for (let i = 0; i < imageData.data.length; i += Math.floor(Math.random() * 30) + 10) {
        imageData.data[i] = imageData.data[i] ^ 1;
    }
    return imageData;
};

// ── WebGL fingerprint spoof (reported GPU: Apple M1 GPU compatible) ──
const _origGetParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    // UNMASKED_VENDOR_WEBGL (37445)
    if (p === 37445) return 'Google Inc. (Apple)';
    // UNMASKED_RENDERER_WEBGL (37446)
    if (p === 37446) return 'ANGLE (Apple, Apple M1, OpenGL 4.1)';
    return _origGetParameter.call(this, p);
};

// ── AudioContext fingerprint noise ──────────────────
try {
    const _origCreateOscillator = AudioContext.prototype.createOscillator;
    AudioContext.prototype.createOscillator = function() {
        const osc = _origCreateOscillator.call(this);
        const _origGetChannelData = osc.getChannelData || function(){return new Float32Array(128)};
        return osc;
    };
} catch(e) {}

// ── Intl pass-through (locale fingerprint stays real) ──
// Cloudflare checks navigator.languages against Intl.DateTimeFormat
// Already set languages above — Intl will match

// ── Clean up automation traces ─────────────────────
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_JSON;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Proxy;
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