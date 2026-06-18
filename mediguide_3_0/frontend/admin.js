const totalReq = document.getElementById("totalReq");
const assistantSessions = document.getElementById("assistantSessions");
const emergencyCount = document.getElementById("emergencyCount");
const totalUsers = document.getElementById("totalUsers");
const lastRefresh = document.getElementById("lastRefresh");
const sourceChips = document.getElementById("sourceChips");
const severityChips = document.getElementById("severityChips");
const recentRecommendations = document.getElementById("recentRecommendations");
const recentAssistant = document.getElementById("recentAssistant");
const registeredUsers = document.getElementById("registeredUsers");
const refreshBtn = document.getElementById("refreshBtn");
const adminLogoutBtn = document.getElementById("adminLogoutBtn");

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderChips(container, dataMap) {
    container.innerHTML = "";
    const keys = Object.keys(dataMap || {});
    if (!keys.length) {
        container.innerHTML = `<div class="chip">No data</div>`;
        return;
    }
    keys.forEach((key) => {
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.textContent = `${key}: ${dataMap[key]}`;
        container.appendChild(chip);
    });
}

function renderRecommendations(rows) {
    recentRecommendations.innerHTML = "";
    if (!rows || !rows.length) {
        recentRecommendations.innerHTML = `<tr><td colspan="6">No records yet.</td></tr>`;
        return;
    }

    rows.forEach((row) => {
        recentRecommendations.innerHTML += `
            <tr>
                <td>${escapeHtml(row.time_utc || "-")}</td>
                <td>${escapeHtml(row.channel || "-")}</td>
                <td>${escapeHtml(row.symptoms || "-")}</td>
                <td>${escapeHtml(row.disease || "-")}</td>
                <td>${escapeHtml(row.severity || "-")}</td>
                <td>${escapeHtml(row.source || "-")}</td>
            </tr>
        `;
    });
}

function renderAssistant(rows) {
    recentAssistant.innerHTML = "";
    if (!rows || !rows.length) {
        recentAssistant.innerHTML = `<tr><td colspan="6">No assistant sessions yet.</td></tr>`;
        return;
    }

    rows.forEach((row) => {
        recentAssistant.innerHTML += `
            <tr>
                <td>${escapeHtml(row.time_utc || "-")}</td>
                <td>${escapeHtml(row.complaint || "-")}</td>
                <td>${escapeHtml(row.question_count || 0)}</td>
                <td>${escapeHtml(row.disease || "-")}</td>
                <td>${escapeHtml(row.severity || "-")}</td>
                <td>${escapeHtml(row.source || "-")}</td>
            </tr>
        `;
    });
}

function renderUsers(rows) {
    registeredUsers.innerHTML = "";
    if (!rows || !rows.length) {
        registeredUsers.innerHTML = `<tr><td colspan="8">No registered users yet.</td></tr>`;
        return;
    }

    rows.forEach((row) => {
        registeredUsers.innerHTML += `
            <tr>
                <td>${escapeHtml(row.username || "-")}</td>
                <td>${escapeHtml(row.name || "-")}</td>
                <td>${escapeHtml(row.email || "-")}</td>
                <td>${escapeHtml(row.phone || "-")}</td>
                <td>${escapeHtml(`${row.gender || "-"} / ${row.age || "-"}`)}</td>
                <td>${escapeHtml(row.medicine_count || 0)}</td>
                <td>${escapeHtml(row.created_at || "-")}</td>
                <td>${escapeHtml(row.last_login_at || "-")}</td>
            </tr>
        `;
    });
}

function setUnauthorizedState() {
    totalReq.textContent = "-";
    assistantSessions.textContent = "-";
    emergencyCount.textContent = "-";
    totalUsers.textContent = "-";
    lastRefresh.textContent = "Login required";
    sourceChips.innerHTML = `<div class="chip">Admin session expired.</div>`;
    severityChips.innerHTML = `<div class="chip">Please login as admin.</div>`;
    recentRecommendations.innerHTML = `<tr><td colspan="6">Unauthorized.</td></tr>`;
    recentAssistant.innerHTML = `<tr><td colspan="6">Unauthorized.</td></tr>`;
    registeredUsers.innerHTML = `<tr><td colspan="8">Unauthorized.</td></tr>`;
}

async function logoutAdmin() {
    try {
        await fetch("/auth/logout", { method: "POST" });
    } catch (_e) {
        // Redirect anyway.
    }
    window.location.href = "/admin/login?next=/admin/dashboard";
}

async function loadStats() {
    try {
        const [statsRes, usersRes] = await Promise.all([
            fetch("/admin-stats"),
            fetch("/admin-users")
        ]);

        if (statsRes.status === 401 || usersRes.status === 401) {
            setUnauthorizedState();
            window.location.href = "/admin/login?next=/admin/dashboard";
            return;
        }

        if (!statsRes.ok || !usersRes.ok) {
            throw new Error("Failed to load admin data");
        }
        const data = await statsRes.json();
        const userData = await usersRes.json();

        totalReq.textContent = data.total_requests || 0;
        assistantSessions.textContent = data.chatbot_sessions || 0;
        emergencyCount.textContent = data.emergency_cases || 0;
        totalUsers.textContent = userData.total_users || 0;
        lastRefresh.textContent = new Date().toISOString().slice(11, 19);

        renderChips(sourceChips, data.source_counts || {});
        renderChips(severityChips, data.severity_counts || {});
        renderRecommendations(data.recent_recommendations || []);
        renderAssistant(data.recent_chatbot || []);
        renderUsers(userData.users || []);
    } catch (error) {
        totalReq.textContent = "-";
        assistantSessions.textContent = "-";
        emergencyCount.textContent = "-";
        totalUsers.textContent = "-";
        lastRefresh.textContent = "API unavailable";
        sourceChips.innerHTML = `<div class="chip">Admin API not available on current backend process.</div>`;
        severityChips.innerHTML = `<div class="chip">Restart backend to enable live admin stats.</div>`;
        recentRecommendations.innerHTML = `<tr><td colspan="6">Admin stats endpoint unavailable.</td></tr>`;
        recentAssistant.innerHTML = `<tr><td colspan="6">Admin stats endpoint unavailable.</td></tr>`;
        registeredUsers.innerHTML = `<tr><td colspan="8">Admin users endpoint unavailable.</td></tr>`;
        console.error(error);
    }
}

refreshBtn.addEventListener("click", loadStats);
if (adminLogoutBtn) {
    adminLogoutBtn.addEventListener("click", logoutAdmin);
}

loadStats();
setInterval(loadStats, 15000);
