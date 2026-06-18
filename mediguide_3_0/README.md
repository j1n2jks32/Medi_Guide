# MediGuide — local dataset mode

Summary of recent changes:

- Removed the AI/LLM-backed chatbot UI. The project now uses a built-in dataset for deterministic recommendations.
- Backend endpoints `/dynamic-question`, `/chatbot-assistant`, and `/recommend` now prefer local dataset matches and do not call external LLMs.
- Frontend chatbot page and script were removed; navigation and admin UI were updated to reflect "assistant" sessions.
- Added `backend/dataset_search.py` (TF-IDF retrieval) and `backend/generate_dataset.py` for synthetic dataset expansion.

How to run locally:

1. Install Python dependencies:

```powershell
D:/python/python.exe -m pip install -r requirements.txt
```

2. Start the backend (binds to port 5000):

```powershell
D:/python/python.exe backend\app.py
```

3. (Optional) Start ngrok to expose the service publicly:

```powershell
D:\games\ngrok-v3-stable-windows-amd64\ngrok.exe http 5000
```

4. Use the web UI at `/index.html` for quick dataset-based recommendations, or call the API endpoints:

- `POST /recommend` { "symptoms": "..." }
- `POST /dynamic-question` { "complaint": "...", "answers": [...] }
- `POST /chatbot-assistant` { "complaint": "...", "answers": [...] }

To generate a synthetic dataset (example for 100k rows):

```powershell
python backend\generate_dataset.py --source backend\medicine_dataset.csv --output backend\medicine_dataset_expanded.csv --target 100000
```

Notes:
- The generated dataset is synthetic and intended for testing only; do not use it as clinical truth.
- If you want the backend to use the expanded CSV, replace `backend/medicine_dataset.csv` with the expanded file or update `dataset_search._build_index` to point to the expanded file.

WhatsApp reminders (Selenium automation):

Optional `backend/.env` configuration:

```text
DEFAULT_COUNTRY_CODE=+91
WHATSAPP_QR_TIMEOUT_SECONDS=60
WHATSAPP_SEND_TIMEOUT_SECONDS=35
WHATSAPP_POST_SEND_WAIT_SECONDS=2
WHATSAPP_PROFILE_DIR=.whatsapp_profile
WHATSAPP_HEADLESS=0
```

Notes:
- Install Selenium dependencies: `pip install selenium webdriver-manager`.
- Backend opens WhatsApp Web, waits for login/QR on first run, then opens chat and clicks Send.
- Route `GET /send_whatsapp?phone=919876543210&medicine=Paracetamol` sends a prefilled reminder message.
- Verify backend status: `GET /whatsapp-config-status`

Authentication and per-user profiles:

- User pages are split:
- `GET /signup` for user registration
- `GET /login` for user login
- `GET /admin-login` for admin-only login (no signup on admin page)
- `GET /profile` requires user login.
- `GET /admin` requires admin login.
- Admin dashboard includes registered users from `GET /admin-users`.
- Configure admin credentials and auth store in `backend/.env`:

```text
FLASK_SECRET_KEY=change-this-secret-in-production
AUTH_STORE_PATH=users_store.json
MEDIGUIDE_ADMIN_USERNAME=jnanesh
MEDIGUIDE_ADMIN_PASSWORD=jnanesh@123
```

Background reminder scheduler (works even after user logout):

```text
REMINDER_SCHEDULER_ENABLED=1
REMINDER_CHECK_INTERVAL_SECONDS=30
REMINDER_DEDUPE_TTL_SECONDS=172800
```
