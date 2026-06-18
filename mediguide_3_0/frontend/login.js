function showLoginMessage(text, ok) {
    const el = document.getElementById("loginMsg");
    if (!el) return;
    el.className = `message ${ok ? "ok" : "err"}`;
    el.textContent = text;
    el.style.display = "block";
}

function cleanNextPath(rawNext) {
    const nextPath = String(rawNext || "").trim();
    if (!nextPath || !nextPath.startsWith("/")) return "/dashboard";
    if (nextPath.startsWith("/admin")) return "/dashboard";
    return nextPath;
}

const params = new URLSearchParams(window.location.search);
const nextPath = cleanNextPath(params.get("next"));

async function checkSession() {
    try {
        const res = await fetch("/auth-status");
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.authenticated) return;
        if (data.is_admin) return;
        window.location.href = nextPath;
    } catch (_e) {
        // stay on login page
    }
}

document.getElementById("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
        username: document.getElementById("loginUsername").value.trim(),
        password: document.getElementById("loginPassword").value,
        admin: false
    };

    try {
        const res = await fetch("/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.error || `Login failed (${res.status})`);
        }
        window.location.href = nextPath;
    } catch (err) {
        showLoginMessage(err.message, false);
    }
});

checkSession();
