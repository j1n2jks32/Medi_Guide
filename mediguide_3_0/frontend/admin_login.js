function showAdminMessage(text, ok) {
    const el = document.getElementById("adminMsg");
    if (!el) return;
    el.className = `message ${ok ? "ok" : "err"}`;
    el.textContent = text;
    el.style.display = "block";
}

function cleanAdminNext(rawNext) {
    const nextPath = String(rawNext || "").trim();
    if (!nextPath || !nextPath.startsWith("/admin")) return "/admin/dashboard";
    return nextPath;
}

const params = new URLSearchParams(window.location.search);
const nextPath = cleanAdminNext(params.get("next"));

async function checkAdminSession() {
    try {
        const res = await fetch("/auth-status");
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.authenticated) return;
        if (data.is_admin) {
            window.location.href = nextPath;
            return;
        }
        window.location.href = "/dashboard";
    } catch (_e) {
        // stay on page
    }
}

document.getElementById("adminLoginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
        username: document.getElementById("adminUsername").value.trim(),
        password: document.getElementById("adminPassword").value,
        admin: true
    };

    try {
        const res = await fetch("/admin/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success || !data.is_admin) {
            throw new Error(data.error || `Admin login failed (${res.status})`);
        }
        window.location.href = nextPath;
    } catch (err) {
        showAdminMessage(err.message, false);
    }
});

checkAdminSession();
