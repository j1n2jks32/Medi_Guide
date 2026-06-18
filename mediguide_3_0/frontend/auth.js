function showMessage(el, text, ok) {
    if (!el) return;
    el.className = `message ${ok ? "ok" : "err"}`;
    el.textContent = text;
    el.style.display = "block";
}

function cleanNextPath(rawNext) {
    const nextPath = String(rawNext || "").trim();
    if (!nextPath || !nextPath.startsWith("/")) return "/profile";
    return nextPath;
}

const params = new URLSearchParams(window.location.search);
const nextPath = cleanNextPath(params.get("next"));
const forceAdmin = params.get("admin") === "1";

const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");
const loginMsg = document.getElementById("loginMsg");
const signupMsg = document.getElementById("signupMsg");
const loginAsAdmin = document.getElementById("loginAsAdmin");

if (forceAdmin && loginAsAdmin) {
    loginAsAdmin.checked = true;
}

async function checkExistingSession() {
    try {
        const res = await fetch("/auth-status");
        const data = await res.json();
        if (!res.ok || !data.authenticated) return;
        if (data.is_admin) {
            window.location.href = "/admin";
            return;
        }
        if (nextPath.startsWith("/admin")) {
            window.location.href = "/profile";
            return;
        }
        window.location.href = nextPath || "/profile";
    } catch (_e) {
        // Ignore and stay on auth page.
    }
}

loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginMsg.style.display = "none";

    const payload = {
        username: document.getElementById("loginUsername").value.trim(),
        password: document.getElementById("loginPassword").value,
        admin: !!loginAsAdmin.checked
    };

    try {
        const res = await fetch("/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.error || `Login failed (${res.status})`);
        }

        if (data.is_admin) {
            window.location.href = "/admin";
            return;
        }

        if (nextPath.startsWith("/admin")) {
            window.location.href = "/profile";
            return;
        }
        window.location.href = nextPath || "/profile";
    } catch (err) {
        showMessage(loginMsg, err.message, false);
    }
});

signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    signupMsg.style.display = "none";

    const payload = {
        name: document.getElementById("signupName").value.trim(),
        username: document.getElementById("signupUsername").value.trim(),
        email: document.getElementById("signupEmail").value.trim(),
        password: document.getElementById("signupPassword").value
    };

    try {
        const res = await fetch("/auth/signup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.error || `Signup failed (${res.status})`);
        }

        showMessage(signupMsg, "Signup successful. Please login.", true);
        document.getElementById("loginUsername").value = payload.username;
    } catch (err) {
        showMessage(signupMsg, err.message, false);
    }
});

checkExistingSession();
