// State tracking
let lastLogCount = 0;
let ttModalShown = false;
let deviceOptions = []; // Store available device options

function showTikTokModal(accounts) {
    const overlay = document.getElementById("tt-modal-overlay");
    const list = document.getElementById("tt-modal-list");
    const countEl = document.getElementById("tt-modal-count");

    countEl.innerText = accounts.length;
    list.innerHTML = "";

    accounts.forEach((name, idx) => {
        const btn = document.createElement("button");
        btn.style.cssText = `
            background: linear-gradient(135deg, #1e2a45, #252f50);
            border: 1px solid #6c63ff55;
            border-radius: 10px;
            padding: 12px 16px;
            color: #e2e8f0;
            font-size: 14px;
            cursor: pointer;
            text-align: left;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 10px;
        `;
        btn.innerHTML = `<span style="background:#6c63ff22; color:#a78bfa; border-radius:6px; padding:2px 8px; font-size:12px; font-weight:700;">${idx + 1}</span> 🆔 ${name}`;
        btn.onmouseover = () => { btn.style.borderColor = "#6c63ff"; btn.style.background = "linear-gradient(135deg, #252f5a, #2d3a6a)"; };
        btn.onmouseout = () => { btn.style.borderColor = "#6c63ff55"; btn.style.background = "linear-gradient(135deg, #1e2a45, #252f50)"; };
        btn.onclick = () => chooseTikTokAccount(name);
        list.appendChild(btn);
    });

    overlay.style.display = "flex";
    ttModalShown = true;
}

function hideTikTokModal() {
    document.getElementById("tt-modal-overlay").style.display = "none";
    ttModalShown = false;
}

async function chooseTikTokAccount(name) {
    try {
        await fetch("/api/tiktok_account/choose", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tiktok_account: name })
        });
        hideTikTokModal();
        fetchLogs();
    } catch (err) {
        alert("Lỗi xác nhận chọn tài khoản TikTok: " + err);
    }
}

async function fetchDashboard() {
    try {
        const res = await fetch("/api/dashboard");
        if (!res.ok) return;
        const data = await res.json();

        // Kiểm tra popup chọn acc TikTok
        if (data.pending_tiktok_choice && !ttModalShown) {
            showTikTokModal(data.tiktok_accounts || []);
        } else if (!data.pending_tiktok_choice && ttModalShown) {
            hideTikTokModal();
        }

        // Update Stat Cards
        const statJob = document.getElementById("stat-job");
        if (statJob) statJob.innerText = data.job || 0;
        const statSuccess = document.getElementById("stat-success");
        if (statSuccess) statSuccess.innerText = data.success || 0;
        const statFailed = document.getElementById("stat-failed");
        if (statFailed) statFailed.innerText = data.failed || 0;

        // Format Currency
        const moneyFormatted = new Intl.NumberFormat('vi-VN').format(data.money || 0) + 'đ';
        const statMoney = document.getElementById("stat-money");
        if (statMoney) statMoney.innerText = moneyFormatted;

        // Calculate Success Rate
        const total = (data.success || 0) + (data.failed || 0);
        const rate = total > 0 ? Math.round((data.success / total) * 100) : 0;
        const statSuccessRate = document.getElementById("stat-success-rate");
        if (statSuccessRate) statSuccessRate.innerText = `Tỷ lệ thành công: ${rate}%`;

        // Update Info Rows
        const infoAccount = document.getElementById("info-account");
        if (infoAccount) infoAccount.innerText = data.account || "--";
        const infoDevice = document.getElementById("info-device");
        if (infoDevice) infoDevice.innerText = data.device || "--";
        const infoJobtype = document.getElementById("info-jobtype");
        if (infoJobtype) infoJobtype.innerText = data.job_type || "--";
        const infoJobid = document.getElementById("info-jobid");
        if (infoJobid) infoJobid.innerText = data.job_id || "--";
        const infoCurrentAction = document.getElementById("info-current-action");
        if (infoCurrentAction) infoCurrentAction.innerText = data.current_action || "Chờ lệnh";

        // Sync delay config inputs (chỉ update nếu user không đang focus vào ô nhập)
        if (document.activeElement.id.indexOf("cfg-delay") === -1) {
            if (data.delay_job_min !== undefined) {
                const el = document.getElementById("cfg-delay-job-min");
                if (el) el.value = data.delay_job_min;
            }
            if (data.delay_job_max !== undefined) {
                const el = document.getElementById("cfg-delay-job-max");
                if (el) el.value = data.delay_job_max;
            }
            if (data.delay_action !== undefined) {
                const el = document.getElementById("cfg-delay-action");
                if (el) el.value = data.delay_action;
            }
            if (data.delay_complete !== undefined) {
                const el = document.getElementById("cfg-delay-complete");
                if (el) el.value = data.delay_complete;
            }
            if (data.delay_like !== undefined) {
                const el = document.getElementById("cfg-delay-like");
                if (el) el.value = data.delay_like;
            }
            if (data.delay_follow !== undefined) {
                const el = document.getElementById("cfg-delay-follow");
                if (el) el.value = data.delay_follow;
            }
            if (data.delay_interaction !== undefined) {
                const el = document.getElementById("cfg-delay-interaction");
                if (el) el.value = data.delay_interaction;
            }
            if (data.delay_interaction_jitter !== undefined) {
                const el = document.getElementById("cfg-delay-interaction-jitter");
                if (el) el.value = data.delay_interaction_jitter;
            }
        }
        const infoReward = document.getElementById("info-reward");
        if (infoReward) {
            const rewardFormatted = new Intl.NumberFormat('vi-VN').format(data.reward || 0) + 'đ';
            infoReward.innerText = rewardFormatted;
        }
        const infoRuntime = document.getElementById("info-runtime");
        if (infoRuntime) infoRuntime.innerText = data.runtime || "0s";

        // Update Status Badge
        const statusBadge = document.getElementById("bot-status");
        const statusDot = document.getElementById("status-dot");
        if (statusBadge && statusDot) {
            const currentStatus = (data.status || "STOPPED").toUpperCase();

            statusBadge.innerText = currentStatus;
            statusBadge.className = "status-text";
            statusDot.className = "pulse-dot";

            if (currentStatus === "RUNNING") {
                statusBadge.classList.add("text-running");
                statusDot.classList.add("dot-running");
            } else if (currentStatus === "PAUSED") {
                statusBadge.classList.add("text-paused");
                statusDot.classList.add("dot-paused");
            } else if (currentStatus === "STARTING") {
                statusBadge.classList.add("text-starting");
                statusDot.classList.add("dot-starting");
            } else {
                statusBadge.classList.add("text-stopped");
                statusDot.classList.add("dot-stopped");
            }
        }

        // NOTE: wizard device-select is populated by renderWizStep(2)
        // Do NOT overwrite it here — polling race causes flicker/reset
    } catch (err) {
        console.error("Lỗi cập nhật dashboard:", err);
    }
}

async function fetchLogs() {
    try {
        const res = await fetch("/api/logs");
        if (!res.ok) return;
        const logsData = await res.json();

        const consoleElem = document.getElementById("log-console");

        if (logsData.length !== lastLogCount) {
            consoleElem.innerHTML = "";
            logsData.forEach(item => {
                const line = document.createElement("div");
                let levelClass = "log-info";
                if (item.level === "SUCCESS") levelClass = "log-success";
                else if (item.level === "ERROR") levelClass = "log-error";
                else if (item.level === "WARNING") levelClass = "log-warning";
                else if (item.level === "SYSTEM") levelClass = "log-system";

                line.className = `log-line ${levelClass}`;
                line.innerText = `[${item.time}] ${item.message}`;
                consoleElem.appendChild(line);
            });
            consoleElem.scrollTop = consoleElem.scrollHeight;
            lastLogCount = logsData.length;
        }
    } catch (err) {
        console.error("Lỗi fetch logs:", err);
    }
}

async function fetchHistory() {
    try {
        const res = await fetch("/api/history");
        if (!res.ok) return;
        const historyData = await res.json();

        const countEl = document.getElementById("history-count");
        if (countEl) countEl.innerText = `${historyData.length} bản ghi`;

        const tbody = document.getElementById("history-tbody");
        if (!tbody) return;  // Element doesn't exist in current page

        if (!historyData || historyData.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="table-empty">Chưa có lịch sử làm job</td></tr>`;
            return;
        }

        let html = "";
        historyData.forEach(item => {
            const isSuccess = item.status === "SUCCESS";
            const badgeClass = isSuccess ? "badge-success" : "badge-failed";
            const statusText = isSuccess ? "Success" : "Failed";
            const rewardText = new Intl.NumberFormat('vi-VN').format(item.reward || 0) + 'đ';

            const accountDisplay = (item.username && item.username !== '--')
                ? item.username
                : (item.account_id || '--');
            html += `
                <tr>
                    <td class="mono-font">${item.time}</td>
                    <td style="font-size:11px;color:#9ca3af;">${accountDisplay}</td>
                    <td><span class="badge-job">${item.job_type}</span></td>
                    <td class="mono-font">${item.job_id}</td>
                    <td><span class="badge ${badgeClass}">${statusText}</span></td>
                    <td class="${isSuccess ? 'text-success font-bold' : ''}">${rewardText}</td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    } catch (err) {
        console.error("Lỗi fetch history:", err);
    }
}

async function fetchAccounts() {
    try {
        const res = await fetch("/api/accounts");
        if (!res.ok) return;
        const data = await res.json();
        const accs = data.accounts || {};
        const selectedId = data.selected_id || "1";

        const tbody = document.getElementById("accounts-tbody");
        if (!tbody) return;  // Element doesn't exist in current page
        const keys = Object.keys(accs);

        if (keys.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="table-empty">Chưa có tài khoản nào. Hãy thêm ở khung bên cạnh!</td></tr>`;
            return;
        }

        let html = "";
        keys.forEach(id => {
            const isSelected = id === selectedId;
            const statusBadge = isSelected
                ? `<span class="badge badge-success">Active</span>`
                : `<span class="badge badge-secondary">InActive</span>`;

            html += `
                <tr>
                    <td class="mono-font">${id}</td>
                    <td class="font-bold">${accs[id].tk}</td>
                    <td>${statusBadge}</td>
                    <td>
                        ${!isSelected ? `<button class="btn btn-sm btn-select" onclick="selectAccount('${id}')">Chọn</button>` : ''}
                        <button class="btn btn-sm btn-delete" onclick="deleteAccount('${id}')">Xóa</button>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    } catch (err) {
        console.error("Lỗi fetch accounts:", err);
    }
}

async function saveAccount() {
    const tk = document.getElementById("acc-username").value.trim();
    const mk = document.getElementById("acc-password").value.trim();

    if (!tk || !mk) {
        alert("Vui lòng nhập đầy đủ tài khoản và mật khẩu!");
        return;
    }

    try {
        const res = await fetch("/api/accounts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tk, mk })
        });
        const data = await res.json();
        if (res.ok) {
            document.getElementById("acc-username").value = "";
            document.getElementById("acc-password").value = "";
            fetchAccounts();
            fetchDashboard();
            fetchLogs();
        } else {
            alert(data.detail || "Lỗi lưu tài khoản!");
        }
    } catch (err) {
        alert("Lỗi kết nối khi lưu tài khoản: " + err);
    }
}

async function selectAccount(id) {
    try {
        const res = await fetch("/api/accounts/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ account_id: id })
        });
        if (res.ok) {
            fetchAccounts();
            fetchDashboard();
            fetchLogs();
        }
    } catch (err) {
        alert("Lỗi chọn tài khoản: " + err);
    }
}

async function deleteAccount(id) {
    if (!confirm(`Bạn có chắc muốn xóa tài khoản ID ${id}?`)) return;

    try {
        const res = await fetch(`/api/accounts/${id}`, { method: "DELETE" });
        if (res.ok) {
            fetchAccounts();
            fetchDashboard();
            fetchLogs();
        }
    } catch (err) {
        alert("Lỗi xóa tài khoản: " + err);
    }
}

async function controlBot(action) {
    try {
        const res = await fetch(`/api/${action}`, { method: "POST" });
        const data = await res.json();
        fetchDashboard();
        fetchLogs();
    } catch (err) {
        alert(`Lỗi thực thi lệnh ${action}: ` + err);
    }
}

function clearLogs() {
    document.getElementById("log-console").innerHTML = `<div class="log-line log-system">[SYSTEM] Đã xóa nhật ký hiển thị trên màn hình.</div>`;
    lastLogCount = 0;
}

async function setTikTokAccount() {
    const val = document.getElementById("tt-acc-input").value.trim();
    try {
        const res = await fetch("/api/tiktok_account/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tiktok_account: val })
        });
        if (res.ok) {
            fetchDashboard();
            fetchLogs();
        }
    } catch (err) {
        alert("Lỗi lưu tài khoản TikTok ưu tiên: " + err);
    }
}

async function saveDelayConfig() {
    const min = parseInt(document.getElementById("cfg-delay-job-min").value) || 8;
    const max = parseInt(document.getElementById("cfg-delay-job-max").value) || 14;
    const action = parseInt(document.getElementById("cfg-delay-action").value) || 5;
    const complete = parseInt(document.getElementById("cfg-delay-complete").value) || 6;
    const like = parseInt(document.getElementById("cfg-delay-like").value) || 2;
    const follow = parseInt(document.getElementById("cfg-delay-follow").value) || 3;
    const interaction = parseFloat(document.getElementById("cfg-delay-interaction").value) || 1.5;
    const interactionJitter = parseFloat(document.getElementById("cfg-delay-interaction-jitter").value) || 0.5;

    if (max < min) {
        alert("Delay max phải >= delay min!");
        return;
    }

    try {
        const res = await fetch("/api/config/delay", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                delay_job_min: min,
                delay_job_max: max,
                delay_action: action,
                delay_complete: complete,
                delay_like: like,
                delay_follow: follow,
                delay_interaction: interaction,
                delay_interaction_jitter: interactionJitter
            })
        });
        if (res.ok) {
            const msg = document.getElementById("delay-save-msg");
            msg.style.display = "inline";
            setTimeout(() => { msg.style.display = "none"; }, 2500);
            fetchLogs();
        } else {
            const err = await res.json();
            alert("Lỗi: " + (err.detail || "Không lưu được config!"));
        }
    } catch (err) {
        alert("Lỗi kết nối khi lưu delay config: " + err);
    }
}

// Device management functions
async function fetchDevices() {
    try {
        const res = await fetch("/api/dashboard");
        if (!res.ok) return;
        const data = await res.json();

        const infoDevice = document.getElementById("info-device");
        if (infoDevice) infoDevice.innerText = data.selected_device_id || "--";

        // Populate unified device table
        const tbody = document.getElementById("unified-devices-tbody");
        if (!tbody) return;  // Element doesn't exist in current page
        const devices = data.unified_devices || [];
        if (!devices.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="table-empty">Ấn "Làm mới" để quét thiết bị</td></tr>';
            return;
        }
        tbody.innerHTML = '';
        devices.forEach(d => {
            const typeIcon = d.type === 'adb' ? '📱 USB' : '📡 WiFi';
            const statusBadge = document.querySelector('.status-' + d.level)
                ? `<span class="status-dot status-${d.level}"></span>${d.level === 'online' ? 'Online' : 'Offline'}`
                : (d.level === 'online' ? '🟢 Online' : '⚫ Offline');
            const baseBtn = d.type === 'wifi'
                ? `<button class="btn btn-sm btn-primary" onclick="wifiReconnect('${d.device_id}')" style="padding:2px 8px;font-size:11px;">🔗 Kết nối</button>`
                : `<button class="btn btn-sm btn-secondary" onclick="selectDeviceById('${d.id}')" style="padding:2px 8px;font-size:11px;">✅ Chọn</button>`;
            const actionBtn = baseBtn + ` <button class="btn btn-sm btn-delete" onclick="deleteDevice('${d.device_id}','${d.type}')" style="padding:2px 8px;font-size:11px;">🗑️ Xóa</button>`;
            const selectedStyle = d.id === data.selected_device_id ? ' style="background:rgba(108,99,255,0.15);"' : '';
            tbody.innerHTML += `<tr${selectedStyle}>
                <td>${typeIcon}</td>
                <td>${d.name}</td>
                <td style="font-family:monospace;font-size:11px;">${d.id}</td>
                <td>${statusBadge}</td>
                <td>${actionBtn}</td>
            </tr>`;
        });
    } catch (err) {
        console.error("Lỗi fetch devices:", err);
    }
}

async function selectDeviceById(deviceId) {
    try {
        const res = await fetch("/api/device/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_id: deviceId })
        });
        if (res.ok) {
            showNotification("Đã chọn thiết bị: " + deviceId, "success");
            fetchDashboard();
            fetchDevices();
        }
    } catch (err) {
        alert("Lỗi chọn thiết bị: " + err);
    }
}

async function refreshDevices() {
    try {
        const res = await fetch("/api/refresh_devices", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });

        if (res.ok) {
            const data = await res.json();
            showNotification(data.message || "Đã làm mới danh sách thiết bị", "info");
            fetchDevices();
        } else {
            const err = await res.json();
            alert("Lỗi làm mới thiết bị: " + (err.detail || "Unknown error"));
        }
    } catch (err) {
        alert("Lỗi kết nối khi làm mới thiết bị: " + err);
    }
}

async function selectDevice() {
    // Deprecated: use selectDeviceById() on unified panel
    return;

    try {
        // Update dashboard with selected device
        const res = await fetch("/api/device/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_id: selectedDevice })
        });

        if (res.ok) {
            fetchDevices(); // Refresh device list
            fetchDashboard(); // Update dashboard
        } else {
            const err = await res.json();
            alert("Lỗi chọn thiết bị: " + (err.detail || "Unknown error"));
        }
    } catch (err) {
        alert("Lỗi kết nối khi chọn thiết bị: " + err);
    }
}

// Helper function to show notifications
function showNotification(message, type = "info") {
    // Create notification element
    const notification = document.createElement("div");
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 8px;
        color: white;
        font-weight: 500;
        z-index: 1000;
        display: flex;
        align-items: center;
        gap: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideIn 0.3s ease-out;
    `;

    // Set background color based on type
    const colors = {
        info: "#3b82f6",
        success: "#22c55e",
        warning: "#eab308",
        error: "#ef4444"
    };
    notification.style.backgroundColor = colors[type] || colors.info;

    // Add icon based on type
    const icons = {
        info: "ℹ️",
        success: "✅",
        warning: "⚠️",
        error: "❌"
    };
    notification.innerHTML = `<span>${icons[type] || icons.info}</span><span>${message}</span>`;

    // Add to document
    document.body.appendChild(notification);

    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = "slideOut 0.3s ease-in";
        setTimeout(() => {
            document.body.removeChild(notification);
        }, 300);
    }, 3000);
}

// Add CSS animations for notifications
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

async function startMultipleAccounts() {
    try {
        const res = await fetch("/api/start-multi", { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to start multi-account mode");
        fetchLogs();
    } catch (err) {
        alert("Lỗi khởi động chế độ nhiều acc: " + err);
    }
}

// ======================== Start Wizard ========================
let wizardStep = 1;
let wizardMode = 'start';  // 'start' or 'queue'
let wizardAccCache = {};   // cached accounts for step 1

function openStartWizard(mode) {
    wizardMode = mode;
    wizardStep = 1;
    document.getElementById('wizard-overlay').style.display = 'flex';
    document.getElementById('wizard-title').innerText = mode === 'queue' ? '➕ Add to Queue' : '🚧 Start Wizard';
    document.getElementById('wizard-subtitle').innerText = mode === 'queue'
        ? 'Thêm cấu hình acc vào hàng đợi'
        : 'Cấu hình acc trước khi chạy';
    fetch('/api/accounts').then(r => r.json()).then(data => {
        wizardAccCache = data.accounts || {};
        renderWizStep();
    });
}

function closeWizard() {
    document.getElementById('wizard-overlay').style.display = 'none';
}

function renderWizStep(step) {
    if (step === undefined) step = wizardStep;
    wizardStep = step;
    // Show/hide step divs
    for (let s = 1; s <= 4; s++) {
        const el = document.getElementById(`wiz-step-${s}`);
        el.style.display = (s === step) ? 'block' : 'none';
        el.classList.toggle('active', s === step);
    }
    // Update step indicators
    document.querySelectorAll('.wiz-step').forEach(el => {
        const s = parseInt(el.dataset.step);
        el.classList.remove('active', 'done');
        if (s === step) el.classList.add('active');
        else if (s < step) el.classList.add('done');
    });
    // Nav buttons
    document.getElementById('wiz-prev').disabled = (step === 1);
    document.getElementById('wiz-next').style.display = (step < 4) ? '' : 'none';
    document.getElementById('wiz-start').style.display = (step === 4) ? '' : 'none';

    // Populate step content
    if (step === 1) {
        const sel = document.getElementById('wiz-account-select');
        const keys = Object.keys(wizardAccCache);
        const currentAcc = document.getElementById('info-account')?.innerText || '';
        sel.innerHTML = '<option value="">-- Chọn tài khoản --</option>';
        keys.forEach(id => {
            const a = wizardAccCache[id];
            const selected = (currentAcc && currentAcc === a.tk) ? ' selected' : '';
            sel.innerHTML += `<option value="${id}"${selected}>#${id} — ${a.tk}</option>`;
        });
        if (keys.length === 0) {
            sel.innerHTML = '<option value="">-- Chưa có tài khoản nào --</option>';
        }
    }
    if (step === 2) {
        const sel = document.getElementById('wiz-device-select');
        sel.innerHTML = '<option value="">-- Đang quét thiết bị...</option>';
        // Force refresh devices first, then populate
        fetch('/api/refresh_devices', { method: 'POST' }).then(r => r.json()).then(refreshed => {
            const devs = refreshed.devices || [];
            sel.innerHTML = '<option value="">-- Chọn thiết bị --</option>';
            if (devs.length === 0) {
                sel.innerHTML = '<option value="">-- Không tìm thấy thiết bị --</option>';
            }
            devs.forEach(d => {
                const icon = d.type === 'adb' ? '📱' : '📡';
                const sts = d.level === 'online' ? '🟢' : '⚫';
                sel.innerHTML += `<option value="${d.id}">${icon} ${sts} ${d.name}</option>`;
            });
            if (devs.length === 1) {
                sel.value = devs[0].id;
            }
        }).catch(() => {
            sel.innerHTML = '<option value="">-- Lỗi quét thiết bị --</option>';
        });
    }
    if (step === 3) {
        const sel = document.getElementById('wiz-tiktok-select');
        const info = document.getElementById('wiz-tiktok-info');
        const accId = document.getElementById('wiz-account-select')?.value;
        if (accId) {
            fetch(`/api/accounts/${accId}/tiktok-cache`).then(r => r.json()).then(d => {
                if (d.accounts && d.accounts.length > 0) {
                    info.innerHTML = `<span style="color:#22c55e;">✓ Đã cache ${d.accounts.length} acc TikTok (${d.scanned_at?.substring(0,10) || '?'})</span>`;
                    sel.innerHTML = '<option value="">-- Tự động chọn --</option>' +
                        d.accounts.map((a, i) => `<option value="${a}">${i+1}. ${a}</option>`).join('');
                } else {
                    info.innerHTML = '<span style="color:#eab308;">⚠ Chưa có cache. Nhấn Scan.</span>';
                    sel.innerHTML = '<option value="">-- Tự động chọn --</option>';
                }
            }).catch(() => {
                info.innerHTML = '<span style="color:#eab308;">⚠ Chưa scan.</span>';
            });
        }
    }
}

function wizNext() {
    if (wizardStep < 4) renderWizStep(wizardStep + 1);
}

function wizPrev() {
    if (wizardStep > 1) renderWizStep(wizardStep - 1);
}

function wizLaunch() {
    const accSelect = document.getElementById('wiz-account-select');
    const accountId = accSelect?.value;
    if (!accountId) { alert('Vui lòng chọn tài khoản GoLike!'); return; }

    const config = {
        account_id: accountId,
        device_id: document.getElementById('wiz-device-select')?.value || '',
        tiktok_account: document.getElementById('wiz-tiktok-select')?.value || '',
        fail_limit: parseInt(document.getElementById('wiz-fail-limit').value) || 0,
        rest_after_jobs: parseInt(document.getElementById('wiz-rest-after').value) || 0,
        rest_duration_min: parseInt(document.getElementById('wiz-rest-duration').value) || 5
    };

    const endpoint = wizardMode === 'queue' ? '/api/queue/add' : '/api/start';
    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    }).then(r => r.json()).then(data => {
        closeWizard();
        fetchDashboard();
        fetchLogs();
        fetchQueue();
    }).catch(err => alert('Lỗi: ' + err));
}

async function wizScanTiktok() {
    const accId = document.getElementById('wiz-account-select')?.value;
    if (!accId) { alert('Vui lòng chọn acc GoLike trước!'); return; }
    const statusEl = document.getElementById('wiz-scan-status');
    if (statusEl) { statusEl.style.display = 'inline'; statusEl.innerText = 'Đang scan...'; }
    try {
        const res = await fetch(`/api/accounts/${accId}/scan-tiktok`, { method: 'POST' });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Scan failed'); }
        const data = await res.json();
        renderWizStep(3); // Refresh step 3 with new cache
        showNotification('✅ Đã scan ' + (data.tiktok_accounts?.length || 0) + ' acc TikTok', 'success');
    } catch (err) {
        showNotification('Scan thất bại: ' + err.message, 'error');
    }
    if (statusEl) statusEl.style.display = 'none';
}

function skipTikTokSelection() {
    renderWizStep(4);
}

// ======================== Batch Queue ========================
function fetchQueue() {
    fetch('/api/queue').then(r => r.json()).then(data => {
        renderQueue(data);
    }).catch(() => {});
}

function renderQueue(data) {
    const panel = document.getElementById('queue-panel');
    const list = document.getElementById('queue-list');
    const status = document.getElementById('queue-status');
    const q = data?.queue || [];
    const cur = data?.current;

    if (!cur && q.length === 0) {
        panel.style.display = 'none';
        return;
    }
    panel.style.display = '';
    status.innerText = cur ? `🟢 Đang chạy: #${cur.account_id}` : `⏳ ${q.length} acc pending`;

    let html = '';
    if (cur) {
        html += `<div class="queue-item current" style="border-color:#22c55e;">
            <span>🟢 #${cur.account_id} (${cur.username || '?'}) — Đang chạy</span>
        </div>`;
    }
    q.forEach((item, i) => {
        html += `<div class="queue-item" style="border-color:#6c63ff55;">
            <span>#${item.account_id} (${item.username || '?'})</span>
            <span style="margin-left:auto; display:flex; gap:8px; align-items:center;">
                <span style="font-size:11px; color:#a78bfa;">fail:${item.fail_limit} rest:${item.rest_after_jobs}/${item.rest_duration_min}ph</span>
                <button class="btn btn-sm btn-delete" onclick="removeFromQueue(${i})">Xóa</button>
            </span>
        </div>`;
    });
    if (!html) html = '<p style="color:#4a5568; font-size:13px;">Queue trống</p>';
    list.innerHTML = html;
}

function removeFromQueue(index) {
    fetch(`/api/queue/${index}`, { method: 'DELETE' }).then(r => r.json()).then(() => fetchQueue());
}

// ======================== Dashboard integration ========================
// Show/hide Add-to-Queue button based on bot status
const origFetchDashboard = fetchDashboard;
fetchDashboard = async function() {
    await origFetchDashboard();
    try {
        const res = await fetch('/api/dashboard');
        const data = await res.json();
        const isRunning = data.status === 'RUNNING' || data.status === 'RESTING';
        document.getElementById('btn-add-queue').style.display = isRunning ? '' : 'none';
        document.getElementById('btn-start').style.display = isRunning ? 'none' : '';
        // Update RESTING dot color
        const dot = document.getElementById('status-dot');
        if (data.status === 'RESTING') {
            document.getElementById('bot-status').innerText = 'RESTING';
            document.getElementById('bot-status').className = 'status-text';
            dot.className = 'pulse-dot status-resting';
        }
    } catch(e) {}
};

// Polling intervals
// ======================== Parallel Sessions ========================
function fetchSessions() {
    fetch('/api/sessions').then(r => r.json()).then(data => {
        renderSessions(data);
    }).catch(() => {});
}

function renderSessions(data) {
    const panel = document.getElementById('sessions-panel');
    const list = document.getElementById('sessions-list');
    const countEl = document.getElementById('sessions-count');
    const sessions = data?.sessions || [];
    const queue = data?.batch_queue || [];

    if (sessions.length === 0) {
        panel.style.display = 'none';
        return;
    }
    panel.style.display = '';
    countEl.innerText = `${sessions.length} active`;

    let html = '';
    sessions.forEach(s => {
        const sc = s.status === 'RUNNING' ? '#22c55e' : (s.status === 'PAUSED' ? '#eab308' : '#f43f5e');
        html += `<div class="session-card" style="display:flex; align-items:center; gap:10px;
            padding:10px 14px; border:1px solid ${sc}55; border-radius:10px;
            background:rgba(255,255,255,0.03); font-size:13px;">
            <span style="width:8px;height:8px;border-radius:50%;background:${sc};box-shadow:0 0 6px ${sc};flex-shrink:0;"></span>
            <span style="flex:1;font-weight:600;">#${s.account_id} <span style="color:#9ca3af;font-weight:400;">${s.username || '?'}</span></span>
            <span style="font-size:11px;color:#a78bfa;">📱 ${s.tiktok_account || 'auto'}</span>
            <span style="font-size:11px;color:#34d399;">🟣 ${s.current_action || '--'}</span>
            <span style="font-size:11px;color:#6b7280;">${s.job_count} jobs | ${s.success_count}✓ ${s.fail_count}✗</span>
            <span style="font-size:11px;color:#eab308;">${new Intl.NumberFormat('vi-VN').format(s.total_money || 0)}đ</span>
            <button class="btn btn-sm btn-delete" style="padding:3px 8px;font-size:11px;" onclick="stopSession('${s.session_id}')">⏹ Dừng</button>
        </div>`;
    });
    if (!html) html = '<p style="color:#4a5568;font-size:13px;">No active sessions</p>';
    list.innerHTML = html;
}

function stopSession(sessionId) {
    fetch(`/api/sessions/${sessionId}/stop`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'not_found') {
                // Session already gone — force refresh to clear stale card
                fetchSessions();
                fetchDashboard();
                fetchLogs();
            }
        })
        .then(() => { fetchDashboard(); fetchSessions(); fetchQueue(); fetchLogs(); });
}

function stopAllSessions() {
    if (!confirm('Dừng TẤT CẢ Chrome sessions và xóa queue?')) return;
    fetch('/api/stop-all', { method: 'POST' })
        .then(() => { fetchDashboard(); fetchSessions(); fetchQueue(); fetchLogs(); });
}

// Update controlBot('stop') to stop-all in parallel mode
const origControlBot = controlBot;
controlBot = async function(action) {
    if (action === 'stop') {
        // In parallel mode, stop calls stop-all
        const res = await fetch('/api/dashboard');
        const data = await res.json();
        if (data.sessions_list && data.sessions_list.length > 0) {
            return stopAllSessions();
        }
    }
    return origControlBot(action);
};

// ════════════════════════════════════════════════════════════
// WiFi ADB Functions
// ════════════════════════════════════════════════════════════

let wifiDevices = [];
let wifiScanActive = false;

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function fetchWiFiDevices() {
    // Delegates to unified device fetch
    await fetchDevices();
}

async function wifiScanNetwork() {
    if (wifiScanActive) return;
    const btn = document.getElementById('btn-wifi-scan');
    const progressContainer = document.getElementById('wifi-scan-progress-container');
    const progressBar = document.getElementById('wifi-scan-progress-bar');
    const statusText = document.getElementById('wifi-scan-status-text');

    btn.disabled = true;
    btn.textContent = '⏳ Đang quét...';
    progressContainer.style.display = '';
    statusText.innerText = 'Đang quét mạng LAN...';
    progressBar.style.width = '5%';
    wifiScanActive = true;

    try {
        const res = await fetch('/api/wifi/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ timeout: 0.3 }),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
    } catch (err) {
        showNotification('Lỗi quét: ' + err.message, 'error');
        btn.disabled = false;
        btn.textContent = '🔍 Quét Mạng';
        progressContainer.style.display = 'none';
        wifiScanActive = false;
        return;
    }

    const pollTimer = setInterval(async () => {
        try {
            const dRes = await fetch('/api/dashboard');
            const dData = await dRes.json();
            const pct = dData.wifi_scan_progress || 0;
            progressBar.style.width = pct + '%';

            if (dData.wifi_scan_in_progress) {
                statusText.innerText = 'Đang quét... ' + Math.round(pct) + '%';
            } else {
                clearInterval(pollTimer);
                wifiScanActive = false;
                btn.disabled = false;
                btn.textContent = '🔍 Quét Mạng';
                progressContainer.style.display = 'none';
                fetchWiFiDevices();
                fetchDashboard();
                const count = (dData.wifi_scan_results || []).length;
                showNotification('Quét Wi-Fi hoàn tất! Tìm thấy ' + count + ' thiết bị.', 'success');
            }
        } catch (_) {}
    }, 1000);
}

function wifiResetForm() {
    document.getElementById('wifi-edit-id').value = '';
    document.getElementById('wifi-device-name').value = '';
    document.getElementById('wifi-device-ip').value = '';
    document.getElementById('wifi-device-port').value = '5555';
}

async function wifiSaveDevice() {
    const id = document.getElementById('wifi-edit-id').value.trim();
    const name = document.getElementById('wifi-device-name').value.trim();
    const ip = document.getElementById('wifi-device-ip').value.trim();
    const port = parseInt(document.getElementById('wifi-device-port').value) || 5555;

    if (!name || !ip) {
        showNotification('Vui lòng nhập tên và IP!', 'error');
        return;
    }

    try {
        let res;
        if (id) {
            res = await fetch('/api/wifi/devices/' + id, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id, name, ip, port })
            });
        } else {
            res = await fetch('/api/wifi/devices/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: '', name, ip, port })
            });
        }
        if (res.ok) {
            wifiResetForm();
            fetchWiFiDevices();
            fetchDashboard();
            fetchLogs();
            showNotification(id ? 'Đã cập nhật thiết bị!' : 'Đã thêm thiết bị!', 'success');
        } else {
            const errData = await res.json();
            showNotification(errData.detail || 'Lỗi lưu thiết bị', 'error');
        }
    } catch (e) {
        showNotification('Lỗi: ' + e.message, 'error');
    }
}

function wifiEditDevice(deviceId) {
    const device = wifiDevices.find(d => d.id === deviceId);
    if (!device) return;
    document.getElementById('wifi-edit-id').value = device.id;
    document.getElementById('wifi-device-name').value = device.name || '';
    document.getElementById('wifi-device-ip').value = device.ip || '';
    document.getElementById('wifi-device-port').value = device.port || 5555;
}

async function deleteDevice(deviceId, type) {
    // Dispatch theo loại thiết bị:
    // - wifi: xóa khỏi devices_wifi.json + disconnect ADB
    // - adb (USB): chỉ rút cáp được, không xóa qua app
    if (type === 'wifi') {
        await wifiDeleteDevice(deviceId);
        return;
    }
    showNotification('Không thể xóa thiết bị USB — hãy rút cáp.', 'error');
}

async function wifiDeleteDevice(deviceId) {
    if (!confirm('Bạn có chắc muốn xóa thiết bị này?')) return;
    try {
        const res = await fetch('/api/wifi/devices/' + deviceId, { method: 'DELETE' });
        if (res.ok) {
            fetchWiFiDevices();
            fetchDashboard();
            fetchLogs();
            showNotification('Đã xóa thiết bị Wi-Fi.', 'success');
        }
    } catch (e) {
        showNotification('Lỗi xóa: ' + e.message, 'error');
    }
}

async function wifiReconnect(deviceId) {
    try {
        const res = await fetch('/api/wifi/devices/' + deviceId + '/reconnect', { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
            showNotification('Đã kết nối lại: ' + (data.message || ''), 'success');
            fetchWiFiDevices();
            fetchDashboard();
            fetchLogs();
        } else {
            showNotification('Kết nối thất bại: ' + (data.error || ''), 'error');
        }
    } catch (e) {
        showNotification('Lỗi: ' + e.message, 'error');
    }
}

async function wifiManualConnect() {
    const ip = document.getElementById('wifi-device-ip').value.trim();
    const port = parseInt(document.getElementById('wifi-device-port').value) || 5555;
    if (!ip) { showNotification('Vui lòng nhập IP!', 'error'); return; }

    try {
        const res = await fetch('/api/wifi/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip: ip, port: port })
        });
        const data = await res.json();
        if (data.ok) {
            showNotification(data.message || 'Kết nối thành công!', 'success');
            fetchWiFiDevices();
            fetchDashboard();
            fetchLogs();
        } else {
            showNotification(data.error || 'Kết nối thất bại', 'error');
        }
    } catch (e) {
        showNotification('Lỗi kết nối: ' + e.message, 'error');
    }
}

async function wifiSwitchToTCPIP() {
    const serial = (document.getElementById('wiz-device-select') && document.getElementById('wiz-device-select').value) || '';
    try {
        const res = await fetch('/api/wifi/connect-usb', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_serial: serial })
        });
        const data = await res.json();
        if (data.ok) {
            showNotification(data.message || 'Đã bật TCP/IP!', 'success');
            fetchLogs();
        } else {
            showNotification(data.error || 'Thất bại', 'error');
        }
    } catch (e) {
        showNotification('Lỗi: ' + e.message, 'error');
    }
}

async function wifiPairDevice() {
    // Android hiển thị IP:Port + pairing code riêng → cho nhập 1 lần
    const input = prompt(
        'Nhập ip:port và mã ghép (cách nhau dấu cách):\nVD: 192.168.1.100:40321 123456',
    );
    if (!input || !input.trim()) { return; }

    // Parse: "192.168.1.100:40321 123456" → ip=192.168.1.100, port=40321, code=123456
    const parts = input.trim().split(/\s+/);
    if (parts.length < 2) {
        showNotification('Nhập sai định dạng! VD: 192.168.1.100:40321 123456', 'error');
        return;
    }
    const addr = parts[0]; // "ip:port"
    const code = parts.slice(1).join(''); // pairing code (ghép các từ sau)
    const addrParts = addr.split(':');
    if (addrParts.length < 2) {
        showNotification('Thiếu dấu ":" giữa IP và port', 'error');
        return;
    }
    const ip = addrParts[0];
    const port = parseInt(addrParts[1]) || 5555;

    try {
        const res = await fetch('/api/wifi/pair', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip: ip, port: port, code: code })
        });
        const data = await res.json();
        if (data.ok) {
            // Auto-fill IP + Port vào form để dùng cho nút kết nối
            document.getElementById('wifi-device-ip').value = ip;
            document.getElementById('wifi-device-port').value = port;
            showNotification(data.message || 'Pairing thành công!', 'success');
        } else {
            showNotification(data.error || 'Pairing thất bại', 'error');
        }
    } catch (e) {
        showNotification('Lỗi: ' + e.message, 'error');
    }
}

async function wifiRefresh() {
    try {
        await fetch('/api/wifi/refresh-status', { method: 'POST' });
        fetchWiFiDevices();
        fetchLogs();
    } catch (e) {
        console.error('WiFi refresh error:', e);
    }
}

// ═════════════════════════════════════════════════════════════
// Telegram Bot Management (Multi-Bot)
// ═════════════════════════════════════════════════════════════

async function loadTelegramBots() {
    try {
        const res = await fetch("/api/config/telegram");
        if (!res.ok) return;
        const data = await res.json();
        renderTelegramBots(data.telegram_bots || []);
    } catch (e) {
        console.error("Lỗi tải Telegram bots:", e);
    }
}

function renderTelegramBots(bots) {
    const tbody = document.getElementById("telegram-bots-table-body");
    if (!tbody) return;

    if (bots.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="padding:20px; text-align:center; color:#4a5568;">Chưa có bot nào. Hãy thêm bot mới.</td></tr>';
        return;
    }

    let html = "";
    bots.forEach((bot, index) => {
        const name = bot.name || `Bot ${index+1}`;
        const chatId = bot.chat_id || "";
        const shortChatId = chatId.length > 15 ? chatId.substring(0, 15) + "..." : chatId;
        html += `
            <tr>
                <td style="padding:8px; color:#e2e8f0;">${name}</td>
                <td style="padding:8px; color:#94a3b8; font-family:monospace; font-size:12px;" title="${chatId}">${shortChatId}</td>
                <td style="padding:8px;">
                    <input type="text" id="test-msg-${index}" placeholder="Tin nhắn test (để trống = mặc định)" style="width:100%; padding:6px 8px; background:#030712; border:1px solid rgba(255,255,255,0.1); color:#fff; border-radius:6px; font-size:12px;">
                </td>
                <td style="padding:8px; display:flex; gap:6px;">
                    <button class="btn btn-primary btn-sm" onclick="testTelegramBot('${bot.name || ''}', ${index})" title="Gửi test">📤 Test</button>
                    <button class="btn btn-secondary btn-sm" onclick="editTelegramBot(${index}, ${JSON.stringify(bot).replace(/"/g, '"')})" title="Sửa">✏️ Sửa</button>
                    <button class="btn btn-delete btn-sm" onclick="deleteTelegramBot(${index})" title="Xóa">🗑️ Xóa</button>
                </td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

async function saveTelegramBot() {
    const name = document.getElementById("cfg-telegram-bot-name").value.trim();
    const token = document.getElementById("cfg-telegram-bot-token").value.trim();
    const chatId = document.getElementById("cfg-telegram-chat-id").value.trim();
    const editIndex = document.getElementById("cfg-telegram-edit-index").value;

    if (!name || !token || !chatId) {
        showNotification("Vui lòng nhập đầy đủ Tên Bot, Token và Chat ID!", "error");
        return;
    }

    try {
        const res = await fetch("/api/config/telegram");
        const data = await res.json();
        let bots = data.telegram_bots || [];

        const newBot = { name, token, chat_id: chatId };

        if (editIndex !== "") {
            // Edit existing
            bots[parseInt(editIndex)] = newBot;
            showNotification(`Đã cập nhật bot: ${name}`, "success");
        } else {
            // Add new
            bots.push(newBot);
            showNotification(`Đã thêm bot mới: ${name}`, "success");
        }

        await fetch("/api/config/telegram", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ telegram_bots: bots })
        });

        clearTelegramForm();
        loadTelegramBots();
        fetchLogs();
        fetchDashboard();
    } catch (e) {
        showNotification("Lỗi lưu bot: " + e.message, "error");
    }
}

function editTelegramBot(index, bot) {
    document.getElementById("cfg-telegram-bot-name").value = bot.name || "";
    document.getElementById("cfg-telegram-bot-token").value = bot.token || "";
    document.getElementById("cfg-telegram-chat-id").value = bot.chat_id || "";
    document.getElementById("cfg-telegram-edit-index").value = index;
    showNotification(`Đang sửa: ${bot.name}`, "info");
}

function clearTelegramForm() {
    document.getElementById("cfg-telegram-bot-name").value = "";
    document.getElementById("cfg-telegram-bot-token").value = "";
    document.getElementById("cfg-telegram-chat-id").value = "";
    document.getElementById("cfg-telegram-edit-index").value = "";
}

async function deleteTelegramBot(index) {
    if (!confirm("Bạn có chắc muốn xóa bot này?")) return;

    try {
        const res = await fetch("/api/config/telegram");
        const data = await res.json();
        let bots = data.telegram_bots || [];

        const deletedName = bots[index]?.name || `Bot ${index+1}`;
        bots.splice(index, 1);

        await fetch("/api/config/telegram", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ telegram_bots: bots })
        });

        showNotification(`Đã xóa bot: ${deletedName}`, "success");
        loadTelegramBots();
        fetchLogs();
        fetchDashboard();
    } catch (e) {
        showNotification("Lỗi xóa bot: " + e.message, "error");
    }
}

async function testTelegramBot(botName, index) {
    const customMsg = document.getElementById(`test-msg-${index}`)?.value || "";
    const message = customMsg.trim() || "✅ *GoLike Bot Test*\\n\\nTelegram notification working from GoLike Dashboard.";

    try {
        const res = await fetch("/api/config/telegram/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bot_name: botName || undefined, message })
        });

        if (res.ok) {
            showNotification(`Đã gửi test tới ${botName || "bot mặc định"}!`, "success");
            fetchLogs();
        } else {
            const err = await res.json();
            showNotification("Test thất bại: " + (err.detail || "Không rõ lỗi"), "error");
        }
    } catch (e) {
        showNotification("Lỗi kết nối: " + e.message, "error");
    }
}

// Keep old function for backward compat
async function testTelegram() {
    testTelegramBot("", 0);
}

// ════════════════════════════════════════════════════════════
// Polling — giảm tần suất để tránh ăn CPU khi idle
// ════════════════════════════════════════════════════════════

// Base intervals (ms) — active tab
const POLL_DASHBOARD  = 2000;   // was 800ms
const POLL_LOGS       = 2000;   // was 1000ms
const POLL_HISTORY    = 5000;   // was 2000ms
const POLL_ACCOUNTS   = 10000;  // was 5000ms
const POLL_DEVICES    = 5000;   // was 3000ms
const POLL_QUEUE      = 3000;   // was 2000ms
const POLL_SESSIONS   = 3000;   // was 2000ms
const POLL_WIFI       = 8000;   // was 4000ms

let _pollTimers = [];

function _clearAllPollTimers() {
    _pollTimers.forEach(t => clearInterval(t));
    _pollTimers = [];
}

function startPolling() {
    _clearAllPollTimers();
    _pollTimers.push(setInterval(fetchDashboard, POLL_DASHBOARD));
    _pollTimers.push(setInterval(fetchLogs,      POLL_LOGS));
    _pollTimers.push(setInterval(fetchHistory,   POLL_HISTORY));
    _pollTimers.push(setInterval(fetchAccounts,  POLL_ACCOUNTS));
    _pollTimers.push(setInterval(fetchDevices,   POLL_DEVICES));
    _pollTimers.push(setInterval(fetchQueue,     POLL_QUEUE));
    _pollTimers.push(setInterval(fetchSessions,  POLL_SESSIONS));
    _pollTimers.push(setInterval(fetchWiFiDevices, POLL_WIFI));
}

// Page Visibility API: giảm poll khi tab không focus
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        _clearAllPollTimers();
        // Tab ẩn → poll chậm gấp 5 lần
        _pollTimers.push(setInterval(fetchDashboard, POLL_DASHBOARD * 5));
        _pollTimers.push(setInterval(fetchLogs,      POLL_LOGS * 5));
    } else {
        // Tab active → khôi phục poll bình thường + fetch ngay
        startPolling();
        fetchDashboard();
        fetchLogs();
    }
});

startPolling();

// Initial Load
fetchDashboard();
fetchLogs();
fetchHistory();
fetchAccounts();
fetchDevices();
fetchQueue();
fetchSessions();
fetchWiFiDevices();
loadTelegramBots();