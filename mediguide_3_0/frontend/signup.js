function showSignupMessage(text, ok) {
    const el = document.getElementById("signupMsg");
    if (!el) return;
    el.className = `message ${ok ? "ok" : "err"}`;
    el.textContent = text;
    el.style.display = "block";
}

const params = new URLSearchParams(window.location.search);
const nextPath = String(params.get("next") || "/dashboard").trim();

document.getElementById("signupForm").addEventListener("submit", async (e) => {
    e.preventDefault();

    const payload = {
        name: document.getElementById("signupName").value.trim(),
        username: document.getElementById("signupUsername").value.trim(),
        email: document.getElementById("signupEmail").value.trim(),
        password: document.getElementById("signupPassword").value
    };

    try {
        const res = await fetch("/signup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.error || `Signup failed (${res.status})`);
        }

        showSignupMessage("Signup successful. Redirecting to login...", true);
        setTimeout(() => {
            const query = new URLSearchParams({ next: nextPath.startsWith("/") ? nextPath : "/dashboard" });
            window.location.href = `/login?${query.toString()}`;
        }, 900);
    } catch (err) {
        showSignupMessage(err.message, false);
    }
});
