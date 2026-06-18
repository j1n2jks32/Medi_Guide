from flask import Flask, request, jsonify, send_from_directory, session, redirect, render_template
import requests
import json
import re
import os
import time
import threading
import urllib.parse
import atexit
import uuid
from datetime import datetime
import dataset_search
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
    SELENIUM_IMPORT_ERROR = ""
except Exception as selenium_import_error:
    SELENIUM_AVAILABLE = False
    SELENIUM_IMPORT_ERROR = str(selenium_import_error)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    APSCHEDULER_AVAILABLE = True
    APSCHEDULER_IMPORT_ERROR = ""
except Exception as apscheduler_import_error:
    APSCHEDULER_AVAILABLE = False
    APSCHEDULER_IMPORT_ERROR = str(apscheduler_import_error)


def _load_env_file(path, overwrite=False):
    """Load KEY=VALUE pairs from a .env file if present."""
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and (overwrite or key not in os.environ):
                    os.environ[key] = val
    except Exception as e:
        print("Failed to load .env:", e)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")

_load_env_file(os.path.join(BASE_DIR, ".env"))

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=FRONTEND_DIR,
    static_url_path=""
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "mediguide-dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["LAST_PROFILE_PHONE"] = ""


def _env_int(name, default):
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return int(default)


def _env_float(name, default):
    try:
        return float(str(os.getenv(name, default)).strip())
    except Exception:
        return float(default)


OLLAMA_MODEL = "llama3"
OLLAMA_URL = "http://localhost:11434/api/generate"
MAX_LOGS = 300
DEFAULT_COUNTRY_CODE = os.getenv("DEFAULT_COUNTRY_CODE", "+91").strip() or "+91"
WHATSAPP_QR_TIMEOUT_SECONDS = _env_int("WHATSAPP_QR_TIMEOUT_SECONDS", 60)
WHATSAPP_SEND_TIMEOUT_SECONDS = _env_int("WHATSAPP_SEND_TIMEOUT_SECONDS", 35)
WHATSAPP_POST_SEND_WAIT_SECONDS = _env_float("WHATSAPP_POST_SEND_WAIT_SECONDS", 2)
WHATSAPP_PROFILE_DIR = os.getenv(
    "WHATSAPP_PROFILE_DIR",
    ".whatsapp_profile"
).strip()
if WHATSAPP_PROFILE_DIR and not os.path.isabs(WHATSAPP_PROFILE_DIR):
    WHATSAPP_PROFILE_DIR = os.path.join(BASE_DIR, WHATSAPP_PROFILE_DIR)
WHATSAPP_HEADLESS = str(os.getenv("WHATSAPP_HEADLESS", "0")).strip().lower() in {"1", "true", "yes"}
WHATSAPP_SEND_LOCK = threading.Lock()
_WHATSAPP_CHROMEDRIVER_PATH = None
AUTH_STORE_PATH = os.getenv("AUTH_STORE_PATH", "users_store.json").strip()
if AUTH_STORE_PATH and not os.path.isabs(AUTH_STORE_PATH):
    AUTH_STORE_PATH = os.path.join(BASE_DIR, AUTH_STORE_PATH)
ADMIN_USERNAME = (os.getenv("MEDIGUIDE_ADMIN_USERNAME", "jnanesh") or "jnanesh").strip()
ADMIN_PASSWORD = (os.getenv("MEDIGUIDE_ADMIN_PASSWORD", "jnanesh@123") or "jnanesh@123").strip()
USER_STORE_LOCK = threading.Lock()
REMINDER_CHECK_INTERVAL_SECONDS = max(10, _env_int("REMINDER_CHECK_INTERVAL_SECONDS", 30))
REMINDER_SCHEDULER_ENABLED = str(
    os.getenv("REMINDER_SCHEDULER_ENABLED", "1")
).strip().lower() in {"1", "true", "yes"}
scheduler = None
REMINDER_RUN_LOCK = threading.Lock()
REMINDER_SEND_DEDUPE_LOCK = threading.Lock()
REMINDER_DEDUPE_CACHE = {}
REMINDER_DEDUPE_TTL_SECONDS = max(3600, _env_int("REMINDER_DEDUPE_TTL_SECONDS", 172800))


def _default_user_store():
    return {"users": {}, "reminders": []}


def _new_user_id():
    return uuid.uuid4().hex


def _new_reminder_id():
    return uuid.uuid4().hex


def _default_reminder_message(medicine):
    med = str(medicine or "").strip()
    if med:
        return f"MediGuide Reminder: Take your medicine {med}."
    return "MediGuide Reminder: Take your medicine."


def _normalize_medicine_key(name):
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def _ensure_store_schema(store):
    changed = False
    if not isinstance(store, dict):
        return _default_user_store(), True

    users = store.get("users")
    if not isinstance(users, dict):
        store["users"] = {}
        users = store["users"]
        changed = True

    reminders = store.get("reminders")
    if not isinstance(reminders, list):
        store["reminders"] = []
        changed = True

    used_ids = set()
    for user_key, user in users.items():
        if not isinstance(user, dict):
            users[user_key] = {}
            user = users[user_key]
            changed = True
        user_id = str(user.get("user_id", "")).strip()
        if not user_id or user_id in used_ids:
            user["user_id"] = _new_user_id()
            user_id = user["user_id"]
            changed = True
        used_ids.add(user_id)

    return store, changed


def _find_user_by_user_id(store, user_id):
    target = str(user_id or "").strip()
    if not target:
        return "", None

    users = store.get("users", {})
    for user_key, user in users.items():
        if not isinstance(user, dict):
            continue
        if str(user.get("user_id", "")).strip() == target:
            return str(user_key), user
    return "", None


def _load_user_store():
    if not AUTH_STORE_PATH:
        return _default_user_store()
    if not os.path.exists(AUTH_STORE_PATH):
        return _default_user_store()
    try:
        with open(AUTH_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data, _ = _ensure_store_schema(data)
        return data
    except Exception as e:
        app.logger.exception("Failed to load users store: %s", e)
        return _default_user_store()


def _save_user_store(store):
    store, _ = _ensure_store_schema(store)

    if not AUTH_STORE_PATH:
        raise RuntimeError("AUTH_STORE_PATH is not configured")

    auth_dir = os.path.dirname(AUTH_STORE_PATH)
    if auth_dir and not os.path.exists(auth_dir):
        os.makedirs(auth_dir, exist_ok=True)

    tmp_path = f"{AUTH_STORE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, AUTH_STORE_PATH)


def _normalized_username(raw_username):
    username = str(raw_username or "").strip()
    if not re.match(r"^[A-Za-z0-9_.-]{3,32}$", username):
        return ""
    return username


def _session_user_key():
    return str(session.get("username_key", "")).strip().lower()


def _session_user_id():
    return str(session.get("user_id", "")).strip()


def _session_role():
    role = str(session.get("role", "")).strip().lower()
    if role in {"admin", "user"}:
        return role
    # Backward compatibility for older sessions.
    if bool(session.get("is_admin")):
        return "admin"
    if _session_user_key():
        return "user"
    return ""


def _is_logged_in_user():
    return _session_role() == "user" and bool(_session_user_key())


def _is_admin_session():
    return _session_role() == "admin"


def _get_user_record(username_key):
    if not username_key:
        return None
    with USER_STORE_LOCK:
        store = _load_user_store()
        user = store.get("users", {}).get(username_key)
        return user if isinstance(user, dict) else None


def _get_current_user_record():
    if not _is_logged_in_user():
        return None
    return _get_user_record(_session_user_key())


def _sync_user_reminders_for_profile(store, user_key, profile_data, updated_at):
    users = store.get("users", {})
    user = users.get(user_key)
    if not isinstance(user, dict):
        return []

    user_id = str(user.get("user_id", "")).strip()
    if not user_id:
        user_id = _new_user_id()
        user["user_id"] = user_id

    phone = str((profile_data or {}).get("phone", "")).strip()
    medicines = _sanitize_medicines((profile_data or {}).get("medicines", []))

    current_reminders = []
    for reminder in store.get("reminders", []):
        if not isinstance(reminder, dict):
            continue
        if str(reminder.get("user_id", "")).strip() == user_id:
            current_reminders.append(reminder)

    existing_by_key = {}
    for reminder in current_reminders:
        key = (
            _normalize_medicine_key(reminder.get("medicine", "")),
            _normalize_reminder_time(reminder.get("reminder_time", reminder.get("time", "")))
        )
        if key[0] and key[1] and key not in existing_by_key:
            existing_by_key[key] = reminder

    refreshed_reminders = []
    for medicine in medicines:
        med_name = str(medicine.get("name", "")).strip()
        reminder_time = _normalize_reminder_time(medicine.get("time", ""))
        if not med_name or not reminder_time:
            continue

        reminder_key = (_normalize_medicine_key(med_name), reminder_time)
        existing = existing_by_key.get(reminder_key, {})
        created_at = str(existing.get("created_at", "")).strip() or updated_at
        reminder_id = str(existing.get("id", "")).strip() or _new_reminder_id()
        reminder_message = str(existing.get("message", "")).strip() or _default_reminder_message(med_name)

        refreshed_reminders.append({
            "id": reminder_id,
            "user_id": user_id,
            "phone": phone,
            "medicine": med_name,
            "reminder_time": reminder_time,
            "message": reminder_message,
            "enabled": bool(medicine.get("enabled", True)),
            "created_at": created_at,
            "updated_at": updated_at
        })

    other_users_reminders = []
    for reminder in store.get("reminders", []):
        if not isinstance(reminder, dict):
            continue
        if str(reminder.get("user_id", "")).strip() != user_id:
            other_users_reminders.append(reminder)

    store["reminders"] = other_users_reminders + refreshed_reminders
    return refreshed_reminders


def _safe_next_path(raw_path, default="/profile"):
    path = str(raw_path or "").strip()
    if not path.startswith("/"):
        return default
    if path.startswith("//"):
        return default
    return path


def _redirect_to_user_login(next_path="/dashboard"):
    safe_next = _safe_next_path(next_path, default="/dashboard")
    query = urllib.parse.urlencode({"next": safe_next})
    return redirect(f"/login?{query}")


def _redirect_to_admin_login(next_path="/admin/dashboard"):
    safe_next = _safe_next_path(next_path, default="/admin/dashboard")
    query = urllib.parse.urlencode({"next": safe_next})
    return redirect(f"/admin/login?{query}")


def _redirect_to_auth(next_path, admin=False):
    if admin:
        return _redirect_to_admin_login(next_path)
    return _redirect_to_user_login(next_path)


def _require_user_json():
    if _is_logged_in_user():
        return None
    return jsonify({"error": "Login required"}), 401


def _require_admin_json():
    if _is_admin_session():
        return None
    return jsonify({"error": "Admin login required"}), 401


def _resolve_reminder_phone(raw_phone):
    phone = str(raw_phone or "").strip()
    if phone:
        return phone

    current_user = _get_current_user_record()
    if current_user:
        profile = current_user.get("profile", {})
        profile_phone = str(profile.get("phone", "")).strip()
        if profile_phone:
            return profile_phone

    return ""


def _empty_profile():
    return {
        "name": "",
        "phone": "",
        "email": "",
        "age": "",
        "gender": "",
        "medicines": [],
        "created_at": ""
    }


def _normalize_reminder_time(raw_time):
    value = str(raw_time or "").strip()
    if not value:
        return ""

    hhmm = re.match(r"^(\d{1,2}):(\d{2})$", value)
    if hhmm:
        hour = int(hhmm.group(1))
        minute = int(hhmm.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return ""

    ampm = re.match(r"^(\d{1,2}):(\d{2})\s*([AaPp][Mm])$", value)
    if ampm:
        hour = int(ampm.group(1))
        minute = int(ampm.group(2))
        marker = ampm.group(3).upper()
        if not (1 <= hour <= 12 and 0 <= minute <= 59):
            return ""
        hour = hour % 12
        if marker == "PM":
            hour += 12
        return f"{hour:02d}:{minute:02d}"

    return ""


def _sanitize_medicines(items):
    medicines = []
    if not isinstance(items, list):
        return medicines

    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        reminder_time = _normalize_reminder_time(item.get("time", ""))
        if not name or not reminder_time:
            continue
        medicines.append({
            "id": item.get("id", int(time.time() * 1000) + len(medicines)),
            "name": name[:120],
            "time": reminder_time,
            "enabled": bool(item.get("enabled", True))
        })
    return medicines[:100]

SAFE_OTC_MEDICINES = [
    "Paracetamol",
    "Acetaminophen",
    "Tylenol",
    "Ibuprofen",
    "Cetirizine",
    "ORS",
    "Antacid",
    "Saline nasal spray",
    "Eye drops",
    "Lubricating eye drops",
    "Dextromethorphan",
    "Guaifenesin"
]

RECOMMENDATION_LOGS = []
CHATBOT_LOGS = []

QUESTION_FLOWS = {
    "weakness_fatigue": [
        "Since when are you experiencing this weakness?",
        "Do you also have fever, dizziness, or breathing difficulty?",
        "How is your sleep and appetite lately?",
        "Any recent illness, stress, or changes in diet?"
    ],
    "pain_general": [
        "Where exactly is the pain located?",
        "How did it start (suddenly or gradually)?",
        "What makes the pain better or worse?",
        "Rate the pain from 1 to 10 and describe its character."
    ],
    "digestive": [
        "Since when are you having these stomach issues?",
        "Any specific food triggers or relief?",
        "Do you have nausea, vomiting, or diarrhea?",
        "Any fever or weight changes?"
    ],
    "respiratory": [
        "Since when are you having these breathing symptoms?",
        "Do you have fever, cough with phlegm, or chest tightness?",
        "Any allergies or asthma history?",
        "How is your sleep and daily activity affected?"
    ],
    "headache": [
        "Since when did the headache start?",
        "Where is the pain and what does it feel like?",
        "Any vision changes, nausea, or sensitivity to light?",
        "Any recent stress, lack of sleep, or head injury?"
    ],
    "leg_pain": [
        "Where exactly is the pain (thigh, knee, calf, ankle, or foot)?",
        "How did it start (injury, sudden onset, or gradual)?",
        "Any swelling, redness, numbness, or trouble walking?",
        "Rate pain from 1 to 10 and tell what makes it worse."
    ],
    "general": [
        "Since when are you having this problem?",
        "Do you also have fever, vomiting, or breathing difficulty?",
        "Is the problem improving, stable, or getting worse today?",
        "Any chronic disease, pregnancy, or regular medicines?"
    ]
}


# -------------------------------
# Language Detection
# -------------------------------
def detect_language(text):
    for ch in text:
        if '\u0C80' <= ch <= '\u0CFF':
            return "Kannada"
        elif '\u0900' <= ch <= '\u097F':
            return "Hindi"
    return "English"


# -------------------------------
# Emergency Detection
# -------------------------------
def is_emergency(text):

    text = text.lower()

    emergency_keywords = [
        "chest pain",
        "heart pain", 
        "difficulty breathing",
        "shortness of breath",
        "heart attack",
        "stroke",
        "unconscious",
        "severe bleeding",
        "fainting",
        "seizure",
        "confusion",
        "blood in vomit",
        "coughing blood"
    ]

    return any(word in text for word in emergency_keywords)


# -------------------------------
# Rule Engine (Common Symptoms)
# -------------------------------
def symptom_rule_engine(symptoms):
    s = symptoms.lower()
    tokens = set(re.findall(r"[a-z]+", s))
    no_patterns = re.findall(r"\b(?:no|not|without|none)\s+([a-z]+)\b", s)
    negated_tokens = set(no_patterns)

    profiles = [
        {
            "disease": "Common Cold",
            "keywords": {"cold", "cough", "runny", "nose", "sneezing", "throat"},
            "required_any": {"cold", "cough", "sneezing", "throat"},
            "medicine": "Cetirizine or saline nasal spray",
            "advice": "Drink warm fluids, rest, and monitor for high fever.",
            "severity": "LOW"
        },
        {
            "disease": "Viral Fever",
            "keywords": {"fever", "temperature", "chills", "weakness", "body", "ache", "fatigue", "tired"},
            "required_any": {"fever", "temperature"},
            "medicine": "Paracetamol",
            "advice": "Hydrate, rest, and seek care if fever persists more than 2 days.",
            "severity": "MODERATE"
        },
        {
            "disease": "General Weakness/Fatigue",
            "keywords": {"weakness", "weak", "fatigue", "tired", "exhausted", "lethargic", "no", "energy", "drained", "low", "energy"},
            "required_any": {"weakness", "weak", "fatigue", "tired", "exhausted"},
            "medicine": "Multivitamin supplements (after consultation)",
            "advice": "Ensure proper nutrition, 7-8 hours sleep, hydration. If persistent > 2 weeks, consult doctor for blood tests.",
            "severity": "MODERATE"
        },
        {
            "disease": "Anemia-Related Weakness",
            "keywords": {"weakness", "fatigue", "pale", "dizzy", "breathless", "tired", "exhausted", "low", "energy"},
            "required_any": {"weakness", "fatigue", "tired"},
            "medicine": "Iron supplements (only after blood test)",
            "advice": "Eat iron-rich foods (spinach, dates, jaggery). Consult doctor for CBC blood test if weakness persists.",
            "severity": "MODERATE"
        },
        {
            "disease": "Dehydration-Related Weakness",
            "keywords": {"weakness", "weak", "dizzy", "dry", "mouth", "thirsty", "tired", "headache", "no", "energy"},
            "required_any": {"weakness", "dizzy", "dry"},
            "medicine": "ORS (Oral Rehydration Solution)",
            "advice": "Drink 2-3 liters water daily. Take ORS if dehydrated. Avoid caffeine and alcohol.",
            "severity": "MODERATE"
        },
        {
            "disease": "Stress-Induced Fatigue",
            "keywords": {"weakness", "fatigue", "stress", "anxiety", "tired", "sleep", "problems", "mental", "exhausted"},
            "required_any": {"weakness", "fatigue", "stress"},
            "medicine": "Stress management techniques",
            "advice": "Practice meditation, deep breathing. Ensure 7-8 hours quality sleep. Consider professional counseling if chronic.",
            "severity": "LOW"
        },
        {
            "disease": "Post-Viral Fatigue",
            "keywords": {"weakness", "fatigue", "tired", "after", "fever", "illness", "viral", "recovery", "weak"},
            "required_any": {"weakness", "fatigue", "tired"},
            "medicine": "Gradual return to activity",
            "advice": "Rest is crucial. Eat protein-rich diet. Gradually increase activity levels over 2-3 weeks.",
            "severity": "MODERATE"
        },
        {
            "disease": "Nutritional Deficiency Weakness",
            "keywords": {"weakness", "fatigue", "tired", "diet", "poor", "appetite", "weight", "loss", "energy"},
            "required_any": {"weakness", "fatigue", "tired"},
            "medicine": "Nutritional supplements",
            "advice": "Eat balanced diet with proteins, vitamins. Consider B-complex vitamins after medical consultation.",
            "severity": "MODERATE"
        },
        {
            "disease": "Tension Headache",
            "keywords": {"headache", "stress", "neck", "tightness"},
            "required_any": {"headache"},
            "medicine": "Paracetamol or Ibuprofen",
            "advice": "Rest in a quiet room and stay hydrated.",
            "severity": "LOW"
        },
        {
            "disease": "Eye Irritation / Conjunctival Inflammation",
            "keywords": {"eye", "redness", "itching", "watering", "burning", "discharge", "pain"},
            "required_any": {"eye"},
            "medicine": "Lubricating eye drops",
            "advice": "Avoid rubbing eyes, clean with sterile water, and seek care for vision changes or severe pain.",
            "severity": "MODERATE"
        },
        {
            "disease": "Acidity / Gastritis",
            "keywords": {"acidity", "gas", "heartburn", "stomach", "burning", "nausea"},
            "required_any": {"acidity", "heartburn", "stomach", "nausea"},
            "medicine": "Antacid",
            "advice": "Avoid spicy/oily food and eat small frequent meals.",
            "severity": "LOW"
        },
        {
            "disease": "Mild Dehydration",
            "keywords": {"dehydration", "dry", "mouth", "dizziness", "thirst"},
            "required_any": {"dehydration", "dry", "dizziness"},
            "medicine": "ORS",
            "advice": "Take oral rehydration fluids and monitor urine output.",
            "severity": "MODERATE"
        },
        {
            "disease": "Muscle Strain / Overuse Leg Pain",
            "keywords": {"leg", "knee", "calf", "ankle", "thigh", "strain", "swelling", "walking", "pain"},
            "required_any": {"leg", "knee", "calf", "ankle", "thigh"},
            "medicine": "Paracetamol or Ibuprofen",
            "advice": "Rest affected leg, apply cold pack for 24 hours, and avoid heavy activity.",
            "severity": "MODERATE"
        }
    ]

    best_match = None
    best_score = 0

    for profile in profiles:
        required_any = profile.get("required_any", set())
        if required_any and not tokens.intersection(required_any):
            continue
        if required_any and tokens.intersection(required_any).intersection(negated_tokens):
            continue

        score = len(tokens.intersection(profile["keywords"]))
        if score > best_score:
            best_score = score
            best_match = profile

    if not best_match:
        return None

    if best_score < 1:
        return None

    if best_score >= 3:
        confidence = "HIGH"
    elif best_score == 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    return {
        "disease": best_match["disease"],
        "medicine": f"{best_match['medicine']} (OTC only, follow label dose)",
        "advice": f"{best_match['advice']} Avoid self-medication if pregnant or if chronic disease is present.",
        "severity": best_match["severity"],
        "confidence": confidence
    }


def sanitize_ai_result(result):
    if not isinstance(result, dict):
        return None

    disease = str(result.get("disease", "")).strip()
    medicine = str(result.get("medicine", "")).strip()
    advice = str(result.get("advice", "")).strip()
    severity = str(result.get("severity", "")).strip().upper()
    confidence = str(result.get("confidence", "")).strip().upper()

    if not disease or not advice:
        return None

    unsafe_terms = [
        "antibiotic", "amoxicillin", "azithromycin", "steroid", "opioid",
        "morphine", "tramadol", "insulin", "warfarin", "prednisone"
    ]
    medicine_lower = medicine.lower()
    if any(term in medicine_lower for term in unsafe_terms):
        medicine = "No safe OTC medicine recommendation. Consult a doctor."
        advice = f"{advice} Prescription medicine should only be taken after medical evaluation."

    if severity not in {"LOW", "MODERATE", "HIGH", "CRITICAL"}:
        severity = "MODERATE"
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        confidence = "MEDIUM"

    if medicine:
        safe_match = any(name.lower() in medicine.lower() for name in SAFE_OTC_MEDICINES)
        if not safe_match:
            medicine = "No safe OTC medicine recommendation. Consult a doctor."
        else:
            medicine = f"{medicine} (OTC guidance only; follow label dose)"
    else:
        medicine = "No safe OTC medicine recommendation. Consult a doctor."

    return {
        "disease": disease,
        "medicine": medicine,
        "advice": advice,
        "severity": severity,
        "confidence": confidence
    }


def detect_track(complaint):
    text = complaint.lower()
    
    # Check for eye issues first (more specific)
    eye_terms = {"eye", "eyes", "vision", "sight", "redness", "itching", "watering", "burning", "discharge"}
    if any(term in text for term in eye_terms):
        return "general"  # Eye issues go to general flow
    
    # Check for weakness/fatigue
    weakness_terms = {"weakness", "weak", "fatigue", "tired", "exhausted", "no energy", "drained", "lethargic"}
    if any(term in text for term in weakness_terms):
        return "weakness_fatigue"
    
    # Check for digestive issues
    digestive_terms = {"stomach", "abdomen", "nausea", "vomiting", "diarrhea", "constipation", "acidity", "gas", "heartburn"}
    if any(term in text for term in digestive_terms):
        return "digestive"
    
    # Check for respiratory issues
    respiratory_terms = {"breath", "breathing", "cough", "cold", "throat", "lungs", "asthma"}
    if any(term in text for term in respiratory_terms):
        return "respiratory"
    
    # Check for headache
    headache_terms = {"headache", "head", "migraine", "dizzy"}
    if any(term in text for term in headache_terms):
        return "headache"
    
    # Check for leg pain
    leg_terms = {"leg", "knee", "calf", "ankle", "foot", "thigh"}
    if any(term in text for term in leg_terms):
        return "leg_pain"
    
    # Check for general pain
    pain_terms = {"pain", "ache", "hurt", "sore", "discomfort"}
    if any(term in text for term in pain_terms):
        return "pain_general"
    
    return "general"


def next_chatbot_question(complaint, answers):
    track = detect_track(complaint)
    flow = QUESTION_FLOWS.get(track, QUESTION_FLOWS["general"])
    index = len(answers)
    if index < len(flow):
        return flow[index]
    return None


def build_chatbot_symptom_text(complaint, answers):
    lines = [f"Primary complaint: {complaint}"]
    for idx, item in enumerate(answers, start=1):
        a = str(item.get("answer", "")).strip()
        if a:
            lines.append(f"Answer {idx}: {a}")
    return " | ".join(lines)


def log_recommendation(symptoms, result, channel):
    entry = {
        "time_utc": datetime.utcnow().isoformat(timespec="seconds"),
        "channel": channel,
        "symptoms": symptoms[:200],
        "disease": result.get("disease", ""),
        "medicine": result.get("medicine", ""),
        "severity": result.get("severity", ""),
        "source": result.get("source", "")
    }
    RECOMMENDATION_LOGS.append(entry)
    if len(RECOMMENDATION_LOGS) > MAX_LOGS:
        del RECOMMENDATION_LOGS[:-MAX_LOGS]


# -------------------------------
# Ollama Request
# -------------------------------
def ask_ollama(prompt):

    try:

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=40
        )

        if response.status_code == 200:
            return response.json().get("response", "").strip()

        return None

    except Exception as e:
        print("Ollama error:", e)
        return None


# -------------------------------
# AI Medical Reasoning
# -------------------------------
def medical_reasoning(symptoms):
    # The medical_reasoning function now expects a conversation summary string
    # and returns a structured JSON with explanation. We instruct the model
    # to reason from the conversation rather than matching rules.

    prompt = """
You are an expert clinical triage assistant. You MUST reason from the provided conversation
context and produce a single, structured JSON final recommendation when asked.

INPUT: A short conversation summary and metadata is provided below. Analyze all information
and decide whether you have enough information to produce a final recommendation.

REQUIREMENTS:
- Use only the conversation context; do NOT use any hardcoded symptom->disease matching lists.
- Ask at most 4-6 follow-up questions in total (this is enforced by the dynamic-question flow).
- Recommend ONLY OTC or self-care options. NEVER provide prescription medicines.
- If the case appears emergent, set severity to CRITICAL and give immediate emergency instructions in the "advice" field.
- Provide a short explanation field describing which symptoms supported your conclusion.

OUTPUT: Return ONLY valid JSON with these keys:
{
    "possible_condition": "",
    "recommended_otc": "",
    "advice": "",
    "severity": "LOW | MODERATE | HIGH | CRITICAL",
    "confidence": "LOW | MEDIUM | HIGH",
    "explanation": ""  // 1-2 sentence rationale
}

CONTEXT:
"""

    prompt = prompt + "\n" + str(symptoms)

    prompt += "\n\nIf you cannot safely produce a recommendation, return null or an empty JSON object."

    response = ask_ollama(prompt)

    if not response:
        return None

    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        json_text = response[start:end]
        return json.loads(json_text)
    except Exception:
        return None


# -------------------------------
# Nearby Hospitals
# -------------------------------
def find_nearby_hospitals(lat, lon):

    try:

        url = f"https://nominatim.openstreetmap.org/search?format=json&q=hospital&limit=5&viewbox={lon-0.1},{lat+0.1},{lon+0.1},{lat-0.1}&bounded=1"

        headers = {"User-Agent": "MediGuide"}

        response = requests.get(url, headers=headers)

        data = response.json()

        hospitals = []

        for place in data:

            name = place.get("display_name", "Hospital")

            lat_val = place.get("lat")
            lon_val = place.get("lon")

            maps = f"https://www.google.com/maps/search/?api=1&query={lat_val},{lon_val}"

            hospitals.append({
                "name": name,
                "maps": maps
            })

        return hospitals

    except Exception as e:

        print("Hospital API error:", e)

        return []


def reverse_geocode_location(lat, lon):
    """Return a short human-readable location label for the given coordinates."""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        headers = {"User-Agent": "MediGuide"}
        params = {
            "format": "jsonv2",
            "lat": lat,
            "lon": lon,
            "zoom": 10,
            "addressdetails": 1
        }

        response = requests.get(url, headers=headers, params=params, timeout=10)
        data = response.json() if response.ok else {}
        address = data.get("address", {}) if isinstance(data, dict) else {}

        locality = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("county")
            or ""
        )
        state = address.get("state", "")
        country = address.get("country", "")
        label = ", ".join([part for part in [locality, state, country] if part])
        if not label:
            label = str(data.get("display_name", "")).strip()

        return {
            "label": label,
            "locality": locality,
            "state": state,
            "country": country
        }
    except Exception as e:
        print("Reverse geocode error:", e)
        return {"label": "", "locality": "", "state": "", "country": ""}


def _format_phone_for_whatsapp(phone):
    raw = str(phone or "").strip()
    if not raw:
        return None, "Phone number not provided"

    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None, "Invalid phone number"

    # If user entered without country code, prepend default country code.
    if raw.startswith("+"):
        formatted = f"+{digits}"
    else:
        default_digits = re.sub(r"\D", "", DEFAULT_COUNTRY_CODE)
        if default_digits and digits.startswith(default_digits):
            formatted = f"+{digits}"
        elif len(digits) == 10 and default_digits:
            formatted = f"+{default_digits}{digits}"
        else:
            formatted = f"+{digits}"

    if not re.match(r"^\+[0-9]{10,15}$", formatted):
        return None, "Phone number must be in international format (+countrycode...)."
    return formatted, ""


def _ensure_chromedriver():
    global _WHATSAPP_CHROMEDRIVER_PATH
    if not SELENIUM_AVAILABLE:
        raise RuntimeError(f"selenium/webdriver not available: {SELENIUM_IMPORT_ERROR}")
    if _WHATSAPP_CHROMEDRIVER_PATH:
        return _WHATSAPP_CHROMEDRIVER_PATH
    _WHATSAPP_CHROMEDRIVER_PATH = ChromeDriverManager().install()
    return _WHATSAPP_CHROMEDRIVER_PATH


def _build_whatsapp_chat_url(formatted_phone, message):
    phone_digits = re.sub(r"\D", "", formatted_phone)
    encoded_message = urllib.parse.quote(str(message), safe="")
    return f"https://web.whatsapp.com/send?phone={phone_digits}&text={encoded_message}", phone_digits


def _build_whatsapp_driver():
    driver_path = _ensure_chromedriver()
    os.makedirs(WHATSAPP_PROFILE_DIR, exist_ok=True)

    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={WHATSAPP_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    if WHATSAPP_HEADLESS:
        options.add_argument("--headless=new")

    return webdriver.Chrome(service=Service(driver_path), options=options)


def _wait_for_whatsapp_login(driver, timeout_seconds):
    timeout_seconds = max(15, int(timeout_seconds))
    deadline = time.time() + timeout_seconds
    qr_required = False

    while time.time() < deadline:
        if driver.find_elements(By.ID, "pane-side"):
            return {"ready": True, "qr_required": qr_required}

        if not qr_required:
            qr_canvas = driver.find_elements(By.XPATH, "//canvas[contains(@aria-label, 'Scan')]")
            qr_canvas += driver.find_elements(By.CSS_SELECTOR, "canvas")
            if qr_canvas:
                qr_required = True
                app.logger.info("WhatsApp Web requires QR login. Scan QR code in browser window.")

        time.sleep(2)

    return {"ready": False, "qr_required": qr_required}


def _click_whatsapp_send_button(driver, timeout_seconds):
    timeout_seconds = max(10, int(timeout_seconds))
    xpaths = [
        '//button[@aria-label="Send"]',
        '//span[@data-icon="send"]',
        '//div[@role="button"]//span[@data-icon="send"]'
    ]

    last_error = None
    for xpath in xpaths:
        try:
            button = WebDriverWait(driver, timeout_seconds).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            button.click()
            return
        except Exception as e:
            last_error = e

    raise TimeoutException(
        f"Could not find/click WhatsApp send button within {timeout_seconds}s. Last error: {last_error}"
    )


def send_whatsapp(phone, message):
    """
    Send a WhatsApp message using Selenium automation:
    1) open WhatsApp Web
    2) wait for QR login (first time)
    3) open chat with prefilled message
    4) click Send button
    """
    formatted_phone, phone_error = _format_phone_for_whatsapp(phone)
    if phone_error:
        app.logger.error("WhatsApp send blocked due to phone format: %s", phone_error)
        return {"success": False, "error": phone_error, "status_code": 0}

    text = str(message or "").strip()
    if not text:
        return {"success": False, "error": "Message text is empty", "status_code": 0}

    if not SELENIUM_AVAILABLE:
        return {
            "success": False,
            "status_code": 0,
            "error": f"selenium/webdriver not available: {SELENIUM_IMPORT_ERROR}"
        }

    url, phone_digits = _build_whatsapp_chat_url(formatted_phone, text)
    driver = None
    login_state = {"qr_required": False}

    try:
        with WHATSAPP_SEND_LOCK:
            driver = _build_whatsapp_driver()
            driver.get("https://web.whatsapp.com")

            login_state = _wait_for_whatsapp_login(driver, WHATSAPP_QR_TIMEOUT_SECONDS)
            if not login_state.get("ready"):
                raise TimeoutException("WhatsApp Web login timed out. Scan QR code and retry.")

            driver.get(url)
            _click_whatsapp_send_button(driver, WHATSAPP_SEND_TIMEOUT_SECONDS)
            time.sleep(max(0.5, WHATSAPP_POST_SEND_WAIT_SECONDS))

        app.logger.info("WhatsApp reminder sent for %s", formatted_phone)
        return {
            "success": True,
            "status_code": 200,
            "provider": "selenium-whatsapp-web",
            "phone": formatted_phone,
            "phone_digits": phone_digits,
            "url": url,
            "qr_required": bool(login_state.get("qr_required"))
        }
    except Exception as e:
        app.logger.exception("Failed to send WhatsApp reminder for %s", formatted_phone)
        return {
            "success": False,
            "status_code": 0,
            "provider": "selenium-whatsapp-web",
            "phone": formatted_phone,
            "url": url,
            "error": str(e)
        }
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def open_whatsapp_reminder(phone, medicine):
    med = str(medicine or "").strip()
    if not med:
        return {"success": False, "error": "Medicine is required", "status_code": 0}
    message = f"⚕️ MediGuide Reminder: Time to take your medicine {med}."
    return send_whatsapp(phone, message)


def _medicine_from_recommendation(result):
    if not isinstance(result, dict):
        return ""
    medicine = str(result.get("recommended_otc") or result.get("medicine") or "").strip()
    return medicine


def _should_send_medicine_reminder(medicine_text):
    if not medicine_text:
        return False
    lowered = medicine_text.lower()
    skip_tokens = [
        "do not self-medicate",
        "no safe otc",
        "consult a doctor",
        "consult doctor"
    ]
    return not any(token in lowered for token in skip_tokens)


def maybe_send_whatsapp_for_recommendation(phone, result):
    """Send WhatsApp reminder when medicine is suggested."""
    status = {
        "attempted": False,
        "success": False,
        "reason": ""
    }

    phone = str(phone or "").strip()
    if not phone:
        status["reason"] = "phone_not_provided"
        return status

    formatted_phone, phone_error = _format_phone_for_whatsapp(phone)
    if phone_error:
        status["reason"] = "invalid_phone_format"
        status["error"] = phone_error
        return status

    medicine = _medicine_from_recommendation(result)
    if not _should_send_medicine_reminder(medicine):
        status["reason"] = "no_medicine_suggested"
        return status

    wa_result = open_whatsapp_reminder(formatted_phone, medicine)
    status["attempted"] = True
    status["success"] = bool(wa_result.get("success"))
    status["medicine"] = medicine
    status["provider"] = wa_result.get("provider", "selenium-whatsapp-web")
    if wa_result.get("success"):
        status["status_code"] = wa_result.get("status_code")
        status["phone"] = wa_result.get("phone", formatted_phone)
        status["url"] = wa_result.get("url", "")
        status["qr_required"] = bool(wa_result.get("qr_required"))
    else:
        status["error"] = wa_result.get("error", "WhatsApp send failed")
        status["status_code"] = wa_result.get("status_code", 0)
    return status


def get_all_reminders():
    reminders = []
    with USER_STORE_LOCK:
        store = _load_user_store()
        store, changed = _ensure_store_schema(store)
        raw_reminders = store.get("reminders", [])

        normalized_reminders = []
        for reminder in raw_reminders:
            if not isinstance(reminder, dict):
                changed = True
                continue

            user_id = str(reminder.get("user_id", "")).strip()
            user_key, user = _find_user_by_user_id(store, user_id)
            if not user:
                changed = True
                continue

            profile = user.get("profile", {})
            if not isinstance(profile, dict):
                changed = True
                continue

            owner_phone = str(profile.get("phone", "")).strip()
            if not owner_phone:
                continue

            medicine_name = str(reminder.get("medicine", "")).strip()
            reminder_time = _normalize_reminder_time(reminder.get("reminder_time", reminder.get("time", "")))
            if not medicine_name or not reminder_time:
                changed = True
                continue

            normalized = {
                "id": str(reminder.get("id", "")).strip() or _new_reminder_id(),
                "user_id": user_id,
                "user_key": str(user_key),
                "username": str(user.get("username", user_key)),
                "phone": owner_phone,
                "medicine": medicine_name,
                "time": reminder_time,
                "message": str(reminder.get("message", "")).strip() or _default_reminder_message(medicine_name),
                "enabled": bool(reminder.get("enabled", True)),
                "created_at": str(reminder.get("created_at", "")).strip(),
                "updated_at": str(reminder.get("updated_at", "")).strip()
            }
            normalized_reminders.append(normalized)
            reminders.append(normalized)

        if changed:
            store["reminders"] = normalized_reminders
            _save_user_store(store)
    return reminders


def _reminder_send_key(reminder, current_day, current_time):
    return "|".join([
        str(reminder.get("user_id", "")),
        str(reminder.get("id", "")),
        str(current_day),
        str(current_time)
    ])


def _cleanup_reminder_dedupe_cache(now_ts):
    stale_keys = []
    for key, sent_at in REMINDER_DEDUPE_CACHE.items():
        if (now_ts - sent_at) > REMINDER_DEDUPE_TTL_SECONDS:
            stale_keys.append(key)
    for key in stale_keys:
        REMINDER_DEDUPE_CACHE.pop(key, None)


def _was_reminder_sent(send_key):
    now_ts = time.time()
    with REMINDER_SEND_DEDUPE_LOCK:
        _cleanup_reminder_dedupe_cache(now_ts)
        return send_key in REMINDER_DEDUPE_CACHE


def _mark_reminder_sent(send_key):
    with REMINDER_SEND_DEDUPE_LOCK:
        REMINDER_DEDUPE_CACHE[send_key] = time.time()


def check_reminders():
    if not REMINDER_SCHEDULER_ENABLED:
        return

    with REMINDER_RUN_LOCK:
        now_local = datetime.now()
        current_day = now_local.strftime("%Y-%m-%d")
        current_time = now_local.strftime("%H:%M")

        reminders = get_all_reminders()
        if not reminders:
            return

        due_reminders = [
            item for item in reminders
            if bool(item.get("enabled", True)) and item.get("time") == current_time
        ]
        for reminder in due_reminders:
            send_key = _reminder_send_key(reminder, current_day, current_time)
            if _was_reminder_sent(send_key):
                continue

            result = send_whatsapp(reminder.get("phone", ""), reminder.get("message", ""))
            if result.get("success"):
                _mark_reminder_sent(send_key)
                app.logger.info(
                    "Scheduler sent WhatsApp reminder for user=%s medicine=%s",
                    reminder.get("username", ""),
                    reminder.get("medicine", "")
                )
            else:
                app.logger.warning(
                    "Scheduler reminder failed for user=%s medicine=%s: %s",
                    reminder.get("username", ""),
                    reminder.get("medicine", ""),
                    result.get("error", "unknown error")
                )


def _start_reminder_scheduler():
    global scheduler

    if not REMINDER_SCHEDULER_ENABLED:
        app.logger.info("Reminder scheduler disabled by REMINDER_SCHEDULER_ENABLED.")
        return False

    if not APSCHEDULER_AVAILABLE:
        app.logger.warning(
            "APScheduler not available. Install 'apscheduler'. Import error: %s",
            APSCHEDULER_IMPORT_ERROR
        )
        return False

    if scheduler is not None and getattr(scheduler, "running", False):
        return True

    try:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            check_reminders,
            trigger="interval",
            seconds=REMINDER_CHECK_INTERVAL_SECONDS,
            id="mediguide_reminder_checker",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        scheduler.start()
        app.logger.info(
            "Reminder scheduler started (interval=%ss).",
            REMINDER_CHECK_INTERVAL_SECONDS
        )
        return True
    except Exception:
        app.logger.exception("Failed to start reminder scheduler.")
        scheduler = None
        return False


def _stop_reminder_scheduler():
    global scheduler
    if scheduler is None:
        return

    try:
        scheduler.shutdown(wait=False)
    except Exception:
        app.logger.exception("Error while stopping reminder scheduler.")
    finally:
        scheduler = None


def _bootstrap_background_jobs():
    # Avoid duplicate scheduler in Flask debug reloader parent process.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    _start_reminder_scheduler()


def geocode_location_query(location_query):
    """Resolve a text location (city/pincode/area) to coordinates."""
    try:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "MediGuide"}
        params = {
            "format": "jsonv2",
            "q": location_query,
            "limit": 1,
            "addressdetails": 1
        }
        response = requests.get(url, headers=headers, params=params, timeout=10)
        data = response.json() if response.ok else []
        if not data:
            return None
        top = data[0]
        lat = float(top.get("lat"))
        lon = float(top.get("lon"))
        label = str(top.get("display_name", "")).strip()
        return {"lat": lat, "lon": lon, "label": label}
    except Exception as e:
        print("Geocode query error:", e)
        return None


def generate_recommendation(symptoms, channel="direct"):
    # Emergency check
    if is_emergency(symptoms):
        result = {
            "disease": "Medical Emergency",
            "medicine": "Do NOT self-medicate",
            "advice": "Call ambulance immediately (108) and go to nearest hospital.",
            "severity": "CRITICAL",
            "confidence": "HIGH",
            "source": "EMERGENCY-PROTOCOL"
        }
        log_recommendation(symptoms, result, channel)
        return result
    # Rule engine first (deterministic common symptoms)
    rule_result = symptom_rule_engine(symptoms)
    if rule_result:
        rule_result["source"] = "RULE-ENGINE"
        log_recommendation(symptoms, {"disease": rule_result.get("disease",""), "medicine": rule_result.get("medicine",""), "severity": rule_result.get("severity",""), "source": "RULE-ENGINE"}, channel)
        return {
            "possible_condition": rule_result.get("disease"),
            "recommended_otc": rule_result.get("medicine"),
            "advice": rule_result.get("advice"),
            "severity": rule_result.get("severity","MODERATE"),
            "confidence": rule_result.get("confidence","HIGH"),
            "explanation": "Matched internal rule engine for common symptoms.",
            "source": "RULE-ENGINE"
        }

    # Dataset lookup (fast local retrieval)
    try:
        ds_hits = dataset_search.find_similar(symptoms, topn=5)
    except Exception:
        ds_hits = []

    # pick best hit
    if ds_hits:
        top = ds_hits[0]
        score = float(top.get('score', 0.0))
        # lower threshold for leg-related complaints
        track = detect_track(symptoms)
        threshold = 0.35
        if track == 'leg_pain':
            threshold = 0.25

        if score >= threshold:
            result = {
                "possible_condition": top.get('disease', 'General Health Issue'),
                "recommended_otc": top.get('medicine', 'No safe OTC recommendation; consult a doctor.'),
                "advice": top.get('advice', 'Follow up with clinician.'),
                "severity": "LOW",
                "confidence": "HIGH" if score >= 0.6 else "MEDIUM",
                "explanation": f"Matched local dataset symptom example (score={score:.2f}).",
                "source": "DATASET"
            }
            log_recommendation(symptoms, {"disease": result.get("possible_condition",""), "medicine": result.get("recommended_otc",""), "severity": result.get("severity",""), "source": "DATASET"}, channel)
            return result

    # Deterministic fallback only (no external LLM calls).
    s = symptoms.lower()
    weakness_keywords = {"weakness", "weak", "fatigue", "tired", "exhausted", "no energy", "drained", "lethargic"}

    if any(keyword in s for keyword in weakness_keywords):
        fallback = {
            "possible_condition": "General Weakness/Fatigue",
            "recommended_otc": "Multivitamin supplements (after consultation)",
            "advice": "Ensure 7-8 hours quality sleep, stay hydrated, eat balanced diet with proteins. If weakness persists > 2 weeks, consult doctor for blood tests to check anemia, thyroid, vitamin deficiencies.",
            "severity": "MODERATE",
            "confidence": "MEDIUM",
            "explanation": "Identified weakness-related symptoms; general wellness advice provided.",
            "source": "ENHANCED-FALLBACK"
        }
    else:
        fallback = {
            "possible_condition": "General Health Issue",
            "recommended_otc": "No safe OTC recommendation; consult a doctor.",
            "advice": "Hydrate, rest, and seek clinical advice for targeted treatment. Monitor symptoms and seek immediate care if they worsen.",
            "severity": "MODERATE",
            "confidence": "LOW",
            "explanation": "Insufficient information for specific diagnosis; please consult a clinician.",
            "source": "ENHANCED-FALLBACK"
        }

    log_recommendation(
        symptoms,
        {
            "disease": fallback.get("possible_condition", ""),
            "medicine": fallback.get("recommended_otc", ""),
            "severity": fallback.get("severity", ""),
            "source": fallback.get("source", "ENHANCED-FALLBACK")
        },
        channel
    )
    return fallback


# -------------------------------
# Frontend
# -------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/heart-monitor")
def heart_monitor():
    return render_template("heart_monitor.html")


def _request_payload():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict()
    return {}


def _create_user_account(data):
    username = _normalized_username(data.get("username", ""))
    password = str(data.get("password", "")).strip()
    email = str(data.get("email", "")).strip()
    name = str(data.get("name", "")).strip()

    if not username:
        return {"error": "Username must be 3-32 chars: letters, numbers, ., _, -"}, 400
    if username.lower() == ADMIN_USERNAME.lower():
        return {"error": "This username is reserved"}, 400
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters"}, 400

    email_regex = re.compile(r'^[^@]+@[^@]+\.[^@]+$')
    if email and not email_regex.match(email):
        return {"error": "Invalid email format"}, 400

    now = datetime.utcnow().isoformat(timespec="seconds")
    user_key = username.lower()

    with USER_STORE_LOCK:
        store = _load_user_store()
        store, _ = _ensure_store_schema(store)
        users = store.setdefault("users", {})
        if user_key in users:
            return {"error": "Username already exists"}, 409

        profile = _empty_profile()
        profile["name"] = name
        profile["email"] = email
        profile["created_at"] = now

        new_user_id = _new_user_id()
        users[user_key] = {
            "user_id": new_user_id,
            "username": username,
            "password_hash": generate_password_hash(password),
            "created_at": now,
            "last_login_at": "",
            "last_profile_update": "",
            "profile": profile
        }
        _save_user_store(store)

    return {
        "success": True,
        "message": "Signup successful. Please login.",
        "user_id": new_user_id
    }, 200


def _perform_admin_login(raw_username, password):
    now = datetime.utcnow().isoformat(timespec="seconds")
    if raw_username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session.clear()
        session["username"] = ADMIN_USERNAME
        session["username_key"] = "__admin__"
        session["user_id"] = "admin"
        session["role"] = "admin"
        session["is_admin"] = True
        session["login_at"] = now
        return {
            "success": True,
            "is_admin": True,
            "username": ADMIN_USERNAME,
            "user_id": "admin"
        }, 200
    return {"error": "Invalid admin credentials"}, 401


def _perform_user_login(raw_username, password):
    if not raw_username or not password:
        return {"error": "Username and password are required"}, 400

    username = _normalized_username(raw_username)
    if not username:
        return {"error": "Invalid username format"}, 400

    user_key = username.lower()
    now = datetime.utcnow().isoformat(timespec="seconds")

    with USER_STORE_LOCK:
        store = _load_user_store()
        store, schema_changed = _ensure_store_schema(store)
        user = store.get("users", {}).get(user_key)
        if not user or not check_password_hash(str(user.get("password_hash", "")), password):
            return {"error": "Invalid username or password"}, 401

        if schema_changed:
            _save_user_store(store)
            user = store.get("users", {}).get(user_key) or user

        user["last_login_at"] = now
        user_id = str(user.get("user_id", "")).strip()
        if not user_id:
            user_id = _new_user_id()
            user["user_id"] = user_id
        store["users"][user_key] = user
        _save_user_store(store)

    session.clear()
    session["username"] = str(user.get("username", username))
    session["username_key"] = user_key
    session["user_id"] = str(user.get("user_id", ""))
    session["role"] = "user"
    session["is_admin"] = False
    session["login_at"] = now

    profile_phone = str((user.get("profile") or {}).get("phone", "")).strip()
    if profile_phone:
        app.config["LAST_PROFILE_PHONE"] = profile_phone

    return {
        "success": True,
        "is_admin": False,
        "username": str(user.get("username", username)),
        "user_id": str(user.get("user_id", "")),
        "has_profile": bool(profile_phone)
    }, 200


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        data = _request_payload()
        payload, status = _perform_user_login(
            str(data.get("username", "")).strip(),
            str(data.get("password", "")).strip()
        )
        return jsonify(payload), status
    return send_from_directory(app.static_folder, "login.html")


@app.route("/login.js")
def login_js():
    return send_from_directory(app.static_folder, "login.js")


@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    if request.method == "POST":
        data = _request_payload()
        payload, status = _create_user_account(data)
        return jsonify(payload), status
    return send_from_directory(app.static_folder, "signup.html")


@app.route("/signup.js")
def signup_js():
    return send_from_directory(app.static_folder, "signup.js")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    if request.method == "POST":
        data = _request_payload()
        payload, status = _perform_admin_login(
            str(data.get("username", "")).strip(),
            str(data.get("password", "")).strip()
        )
        return jsonify(payload), status
    return send_from_directory(app.static_folder, "admin_login.html")


@app.route("/admin/login.js")
def admin_login_js():
    return send_from_directory(app.static_folder, "admin_login.js")


@app.route("/admin-login")
def admin_login_compat():
    next_path = _safe_next_path(request.args.get("next", ""), default="/admin/dashboard")
    query = urllib.parse.urlencode({"next": next_path})
    return redirect(f"/admin/login?{query}")


@app.route("/admin-login.js")
def admin_login_js_compat():
    return redirect("/admin/login.js")


@app.route("/auth")
def auth_page():
    next_path = _safe_next_path(request.args.get("next", ""), default="/dashboard")
    admin_flag = str(request.args.get("admin", "0")).strip() == "1"
    target = "/admin/login" if (admin_flag or next_path.startswith("/admin")) else "/login"
    query = urllib.parse.urlencode({"next": next_path})
    return redirect(f"{target}?{query}")


@app.route("/auth.js")
def auth_js():
    return send_from_directory(app.static_folder, "auth.js")


@app.route("/auth-status", methods=["GET"])
def auth_status():
    if _is_admin_session():
        return jsonify({
            "authenticated": True,
            "is_admin": True,
            "role": "admin",
            "username": str(session.get("username", ADMIN_USERNAME)),
            "user_id": str(session.get("user_id", "admin"))
        })

    if _is_logged_in_user():
        user = _get_current_user_record()
        if not user:
            session.clear()
            return jsonify({
                "authenticated": False,
                "is_admin": False,
                "role": "",
                "username": "",
                "user_id": ""
            })
        profile = user.get("profile", {})
        return jsonify({
            "authenticated": True,
            "is_admin": False,
            "role": "user",
            "username": str(user.get("username", session.get("username", ""))),
            "user_id": str(user.get("user_id", _session_user_id())),
            "has_profile": bool(str(profile.get("phone", "")).strip())
        })

    return jsonify({
        "authenticated": False,
        "is_admin": False,
        "role": "",
        "username": "",
        "user_id": ""
    })


@app.route("/auth/signup", methods=["POST"])
def auth_signup():
    try:
        data = _request_payload()
        payload, status = _create_user_account(data)
        return jsonify(payload), status
    except Exception:
        app.logger.exception("Signup failed")
        return jsonify({"error": "Failed to create account"}), 500


@app.route("/auth/login", methods=["POST"])
def auth_login():
    try:
        data = _request_payload()
        raw_username = str(data.get("username", "")).strip()
        password = str(data.get("password", "")).strip()
        admin_login = bool(data.get("admin"))
        if admin_login:
            payload, status = _perform_admin_login(raw_username, password)
        else:
            payload, status = _perform_user_login(raw_username, password)
        return jsonify(payload), status
    except Exception:
        app.logger.exception("Login failed")
        return jsonify({"error": "Login failed"}), 500


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/profile-data", methods=["GET"])
def profile_data():
    auth_error = _require_user_json()
    if auth_error:
        return auth_error

    user = _get_current_user_record()
    if not user:
        session.clear()
        return jsonify({"error": "Session expired. Please login again."}), 401

    profile = user.get("profile", _empty_profile())
    if not isinstance(profile, dict):
        profile = _empty_profile()

    profile.setdefault("medicines", [])
    return jsonify({
        "success": True,
        "user_id": str(user.get("user_id", "")),
        "username": str(user.get("username", "")),
        "profile": profile
    })


@app.route("/chatbot")
def chatbot_page():
    # Chatbot removed per user request
    return (jsonify({"error": "Chatbot feature removed"}), 404)


@app.route("/chatbot.html")
def chatbot_page_html():
    # Chatbot removed per user request
    return (jsonify({"error": "Chatbot feature removed"}), 404)


@app.route("/chatbot.js")
def chatbot_js():
    # Chatbot removed per user request
    return (jsonify({"error": "Chatbot feature removed"}), 404)


@app.route("/admin.js")
def admin_js():
    return send_from_directory(app.static_folder, "admin.js")




@app.route("/profile")
def profile_page():
    if _is_logged_in_user():
        return redirect("/dashboard")
    return send_from_directory(app.static_folder, "profile_options.html")


@app.route("/profile.html")
def profile_page_html():
    return redirect("/profile")


@app.route("/dashboard")
def user_dashboard():
    if not _is_logged_in_user():
        return _redirect_to_user_login("/dashboard")
    return send_from_directory(app.static_folder, "profile.html")


@app.route("/dashboard.html")
def user_dashboard_html():
    return redirect("/dashboard")


@app.route("/profile.js")
def profile_js():
    return send_from_directory(app.static_folder, "profile.js")


@app.route("/save-profile", methods=["POST"])
def save_profile():
    """Save user profile data"""
    try:
        auth_error = _require_user_json()
        if auth_error:
            return auth_error

        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        # Validate required fields
        required_fields = ["name", "phone", "email"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Validate phone number format
        phone = data.get("phone", "").strip()
        phone_regex = re.compile(r'^\+[0-9]{10,15}$')
        if not phone_regex.match(phone):
            return jsonify({"error": "Invalid phone number format. Use +country code format (e.g., +1234567890)"}), 400
        
        # Validate email format
        email = data.get("email", "").strip()
        email_regex = re.compile(r'^[^@]+@[^@]+\.[^@]+$')
        if not email_regex.match(email):
            return jsonify({"error": "Invalid email format"}), 400
        
        # Store profile (in production, use database)
        user = _get_current_user_record()
        if not user:
            session.clear()
            return jsonify({"error": "Session expired. Please login again."}), 401

        existing_profile = user.get("profile", {})
        existing_created_at = str(existing_profile.get("created_at", "")).strip() if isinstance(existing_profile, dict) else ""
        now = datetime.utcnow().isoformat(timespec="seconds")

        profile_data = {
            "name": data.get("name"),
            "phone": phone,
            "email": email,
            "age": data.get("age", ""),
            "gender": data.get("gender", ""),
            "medicines": _sanitize_medicines(data.get("medicines", [])),
            "created_at": existing_created_at or now,
            "updated_at": now
        }
        
        # Log profile save
        print(f"Profile saved: {profile_data['name']} ({phone})")
        app.config["LAST_PROFILE_PHONE"] = phone

        user_key = _session_user_key()
        with USER_STORE_LOCK:
            store = _load_user_store()
            store, _ = _ensure_store_schema(store)
            stored_user = store.get("users", {}).get(user_key)
            if not stored_user:
                session.clear()
                return jsonify({"error": "Session expired. Please login again."}), 401

            stored_user_id = str(stored_user.get("user_id", "")).strip()
            if not stored_user_id:
                stored_user_id = _new_user_id()
                stored_user["user_id"] = stored_user_id

            stored_user["profile"] = profile_data
            stored_user["last_profile_update"] = now
            store["users"][user_key] = stored_user
            stored_reminders = _sync_user_reminders_for_profile(store, user_key, profile_data, now)
            _save_user_store(store)
        
        return jsonify({
            "success": True,
            "message": "Profile saved successfully",
            "username": str(user.get("username", "")),
            "user_id": str(stored_user.get("user_id", "")),
            "reminder_count": len(stored_reminders),
            "profile": profile_data
        })
        
    except Exception as e:
        print(f"Error saving profile: {str(e)}")
        return jsonify({"error": "Failed to save profile"}), 500


@app.route("/add-reminder", methods=["POST"])
def add_reminder():
    try:
        auth_error = _require_user_json()
        if auth_error:
            return auth_error

        data = request.get_json() or {}
        medicine_name = str(data.get("medicine", "")).strip()
        reminder_time = _normalize_reminder_time(data.get("time", ""))
        enabled = bool(data.get("enabled", True))

        if not medicine_name:
            return jsonify({"error": "Medicine is required"}), 400
        if not reminder_time:
            return jsonify({"error": "Reminder time must be HH:MM"}), 400

        user_key = _session_user_key()
        now = datetime.utcnow().isoformat(timespec="seconds")

        with USER_STORE_LOCK:
            store = _load_user_store()
            store, _ = _ensure_store_schema(store)
            user = store.get("users", {}).get(user_key)
            if not isinstance(user, dict):
                session.clear()
                return jsonify({"error": "Session expired. Please login again."}), 401

            profile = user.get("profile", _empty_profile())
            if not isinstance(profile, dict):
                profile = _empty_profile()

            phone = str(profile.get("phone", "")).strip()
            if not phone:
                return jsonify({"error": "Please save your profile phone number first."}), 400

            medicines = _sanitize_medicines(profile.get("medicines", []))
            matched = False
            for medicine in medicines:
                if (
                    _normalize_medicine_key(medicine.get("name", "")) == _normalize_medicine_key(medicine_name)
                    and _normalize_reminder_time(medicine.get("time", "")) == reminder_time
                ):
                    medicine["enabled"] = enabled
                    matched = True
                    break

            if not matched:
                medicines.append({
                    "id": int(time.time() * 1000) + len(medicines),
                    "name": medicine_name[:120],
                    "time": reminder_time,
                    "enabled": enabled
                })

            profile["medicines"] = _sanitize_medicines(medicines)
            profile["updated_at"] = now
            user["profile"] = profile
            user["last_profile_update"] = now
            store["users"][user_key] = user

            reminders = _sync_user_reminders_for_profile(store, user_key, profile, now)
            _save_user_store(store)

        return jsonify({
            "success": True,
            "message": "Reminder saved",
            "user_id": str(user.get("user_id", "")),
            "reminder_count": len(reminders)
        })
    except Exception:
        app.logger.exception("Failed to add reminder")
        return jsonify({"error": "Failed to add reminder"}), 500


@app.route("/send-medicine-reminder", methods=["POST"])
def send_medicine_reminder():
    """Send medicine reminder via Selenium WhatsApp automation."""
    try:
        auth_error = _require_user_json()
        if auth_error:
            return auth_error

        data = request.get_json() or {}

        user = _get_current_user_record()
        if not user:
            session.clear()
            return jsonify({"error": "Session expired. Please login again."}), 401

        profile = user.get("profile", {}) if isinstance(user, dict) else {}
        phone = str(profile.get("phone", "")).strip()
        medicine = str(data.get("medicine", "")).strip()
        message = str(data.get("message", "")).strip()

        if not medicine:
            return jsonify({"error": "Missing required field: medicine"}), 400
        if not phone:
            return jsonify({"error": "Please save your profile phone number first."}), 400
        if not message:
            message = _default_reminder_message(medicine)

        wa_result = send_whatsapp(phone, message)
        if not wa_result.get("success"):
            return jsonify({
                "success": False,
                "error": wa_result.get("error", "WhatsApp delivery failed"),
                "phone": phone,
                "medicine": medicine
            }), 503

        return jsonify({
            "success": True,
            "message": f"WhatsApp reminder sent for {wa_result.get('phone', phone)}",
            "phone": phone,
            "medicine": medicine,
            "user_id": str(user.get("user_id", _session_user_id())),
            "provider": wa_result.get("provider", "selenium-whatsapp-web"),
            "url": wa_result.get("url", ""),
            "qr_required": bool(wa_result.get("qr_required")),
            "timestamp": datetime.utcnow().isoformat(timespec="seconds")
        })
        
    except Exception as e:
        app.logger.exception("Error sending WhatsApp reminder")
        return jsonify({"error": "Failed to send reminder"}), 500


@app.route("/send_whatsapp", methods=["GET"])
def send_whatsapp_route():
    phone = str(request.args.get("phone", "")).strip()
    medicine = request.args.get("medicine", "").strip()

    if not medicine:
        return jsonify({"error": "medicine query param is required"}), 400

    if _is_admin_session():
        if not phone:
            return jsonify({"error": "phone query param is required for admin mode"}), 400
    else:
        auth_error = _require_user_json()
        if auth_error:
            return auth_error

        user = _get_current_user_record()
        if not user:
            session.clear()
            return jsonify({"error": "Session expired. Please login again."}), 401

        profile = user.get("profile", {}) if isinstance(user, dict) else {}
        phone = str(profile.get("phone", "")).strip()
        if not phone:
            return jsonify({"error": "Please save your profile phone number first."}), 400

    result = open_whatsapp_reminder(phone, medicine)
    if not result.get("success"):
        return jsonify({
            "success": False,
            "error": result.get("error", "Failed to send WhatsApp reminder"),
            "phone": phone,
            "medicine": medicine
        }), 503

    return jsonify({
        "success": True,
        "message": "WhatsApp reminder sent",
        "phone": result.get("phone", phone),
        "medicine": medicine,
        "provider": result.get("provider", "selenium-whatsapp-web"),
        "url": result.get("url", ""),
        "qr_required": bool(result.get("qr_required")),
        "timestamp": datetime.utcnow().isoformat(timespec="seconds")
    })


@app.route("/whatsapp-config-status", methods=["GET"])
def whatsapp_config_status():
    profile_ready = False
    if WHATSAPP_PROFILE_DIR:
        profile_ready = os.path.isdir(WHATSAPP_PROFILE_DIR)
    current_user_phone = _resolve_reminder_phone("")

    return jsonify({
        "configured": bool(SELENIUM_AVAILABLE),
        "library": "selenium + webdriver-manager",
        "notes": "Automates WhatsApp Web login and clicks Send button.",
        "selenium_available": bool(SELENIUM_AVAILABLE),
        "apscheduler_available": bool(APSCHEDULER_AVAILABLE),
        "scheduler_enabled": bool(REMINDER_SCHEDULER_ENABLED),
        "scheduler_running": bool(scheduler is not None and getattr(scheduler, "running", False)),
        "import_error": SELENIUM_IMPORT_ERROR if not SELENIUM_AVAILABLE else "",
        "apscheduler_import_error": APSCHEDULER_IMPORT_ERROR if not APSCHEDULER_AVAILABLE else "",
        "profile_dir": WHATSAPP_PROFILE_DIR,
        "profile_dir_exists": profile_ready,
        "headless": WHATSAPP_HEADLESS,
        "has_last_profile_phone": bool(str(app.config.get("LAST_PROFILE_PHONE", "")).strip()),
        "has_current_profile_phone": bool(str(current_user_phone).strip())
    })


@app.route("/admin")
def admin_page():
    return redirect("/admin/dashboard")


@app.route("/admin.html")
def admin_page_html():
    return redirect("/admin/dashboard")


@app.route("/admin/dashboard")
def admin_dashboard():
    if not _is_admin_session():
        return _redirect_to_admin_login("/admin/dashboard")
    return send_from_directory(app.static_folder, "admin.html")


# -------------------------------
# Hospital API
# -------------------------------
@app.route("/nearby-hospitals", methods=["POST"])
def nearby_hospitals():

    data = request.get_json() or {}
    location_query = str(data.get("location_query", "")).strip()
    source = "gps"
    accuracy = None

    if location_query:
        geocoded = geocode_location_query(location_query)
        if not geocoded:
            return jsonify({"error": "Could not resolve the provided location query"}), 400
        lat = geocoded["lat"]
        lon = geocoded["lon"]
        source = "manual"
    else:
        try:
            lat = float(data.get("lat"))
            lon = float(data.get("lon"))
        except (TypeError, ValueError):
            return jsonify({"error": "Valid latitude and longitude are required"}), 400
        try:
            accuracy = float(data.get("accuracy")) if data.get("accuracy") is not None else None
        except (TypeError, ValueError):
            accuracy = None

    hospitals = find_nearby_hospitals(lat, lon)
    location = reverse_geocode_location(lat, lon)
    if source == "manual" and not location.get("label"):
        location["label"] = geocoded.get("label", "")

    return jsonify({
        "ambulance": "108",
        "hospitals": hospitals,
        "coords": {"lat": lat, "lon": lon, "accuracy_m": accuracy},
        "detected_location": location,
        "source": source
    })


@app.route("/chatbot-assistant", methods=["POST"])
def chatbot_assistant():
    data = request.get_json() or {}

    complaint = data.get("complaint", "").strip()
    answers = data.get("answers", [])

    if not complaint:
        return jsonify({"error": "Complaint is required"}), 400
    if not isinstance(answers, list):
        answers = []

    question = next_chatbot_question(complaint, answers)
    if question:
        return jsonify({
            "status": "question",
            "question": question,
            "options": [],
            "step": len(answers) + 1,
            "track": detect_track(complaint),
            "emergency": False
        })

    summary = build_chatbot_symptom_text(complaint, answers)
    result = generate_recommendation(summary, channel="chatbot")

    chatbot_entry = {
        "time_utc": datetime.utcnow().isoformat(timespec="seconds"),
        "complaint": complaint[:120],
        "question_count": len(answers),
        "disease": result.get("possible_condition", result.get("disease", "")),
        "severity": result.get("severity", ""),
        "source": result.get("source", "UNKNOWN")
    }
    CHATBOT_LOGS.append(chatbot_entry)
    if len(CHATBOT_LOGS) > MAX_LOGS:
        del CHATBOT_LOGS[:-MAX_LOGS]

    # Normalize to legacy keys expected by frontend/admin
    if result and isinstance(result, dict) and "possible_condition" in result:
        norm = {
            "disease": result.get("possible_condition"),
            "medicine": result.get("recommended_otc"),
            "advice": result.get("advice"),
            "severity": result.get("severity"),
            "confidence": result.get("confidence","MEDIUM"),
            "explanation": result.get("explanation",""),
            "source": result.get("source", "UNKNOWN")
        }
    else:
        # If older schema, pass through
        norm = result

    return jsonify({
        "status": "final",
        "summary": summary,
        "result": norm
    })


@app.route("/dynamic-question", methods=["POST"])
def dynamic_question():
    data = request.get_json() or {}
    complaint = data.get("complaint", "").strip()
    answers = data.get("answers", []) or []
    age = data.get("age")
    gender = data.get("gender")

    if not complaint:
        return jsonify({"error": "Complaint is required"}), 400
    # Deterministic question flow only â€” do NOT call any external LLM.
    question = next_chatbot_question(complaint, answers)
    if question:
        return jsonify({
            "status": "question",
            "question": question,
            "options": [],
            "step": len(answers) + 1,
            "track": detect_track(complaint),
            "emergency": False
        })

    # No more questions â€” produce dataset-backed recommendation
    summary = build_chatbot_symptom_text(complaint, answers)
    result = generate_recommendation(summary, channel="chatbot")
    return jsonify({
        "status": "final",
        "result": result
    })


@app.route("/admin-stats", methods=["GET"])
def admin_stats():
    auth_error = _require_admin_json()
    if auth_error:
        return auth_error

    source_counts = {}
    severity_counts = {}

    for item in RECOMMENDATION_LOGS:
        source = item.get("source", "UNKNOWN")
        severity = item.get("severity", "UNKNOWN")
        source_counts[source] = source_counts.get(source, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    emergency_cases = source_counts.get("EMERGENCY-PROTOCOL", 0)
    recent_items = list(reversed(RECOMMENDATION_LOGS[-15:]))
    recent_chatbot = list(reversed(CHATBOT_LOGS[-10:]))

    return jsonify({
        "total_requests": len(RECOMMENDATION_LOGS),
        "chatbot_sessions": len(CHATBOT_LOGS),
        "emergency_cases": emergency_cases,
        "source_counts": source_counts,
        "severity_counts": severity_counts,
        "recent_recommendations": recent_items,
        "recent_chatbot": recent_chatbot
    })


@app.route("/admin-users", methods=["GET"])
def admin_users():
    auth_error = _require_admin_json()
    if auth_error:
        return auth_error

    with USER_STORE_LOCK:
        store = _load_user_store()
        store, schema_changed = _ensure_store_schema(store)
        reminders = store.get("reminders", [])
        reminder_counts = {}
        for reminder in reminders:
            if not isinstance(reminder, dict):
                continue
            user_id = str(reminder.get("user_id", "")).strip()
            if not user_id:
                continue
            reminder_counts[user_id] = reminder_counts.get(user_id, 0) + 1

        if schema_changed:
            _save_user_store(store)

        users = []
        for user_key, user in (store.get("users") or {}).items():
            if not isinstance(user, dict):
                continue
            profile = user.get("profile", {})
            if not isinstance(profile, dict):
                profile = {}
            medicines = profile.get("medicines", [])
            if not isinstance(medicines, list):
                medicines = []
            user_id = str(user.get("user_id", "")).strip()
            users.append({
                "user_id": user_id,
                "username": str(user.get("username", user_key)),
                "created_at": str(user.get("created_at", "")),
                "last_login_at": str(user.get("last_login_at", "")),
                "last_profile_update": str(user.get("last_profile_update", "")),
                "name": str(profile.get("name", "")),
                "email": str(profile.get("email", "")),
                "phone": str(profile.get("phone", "")),
                "age": str(profile.get("age", "")),
                "gender": str(profile.get("gender", "")),
                "medicine_count": len(medicines),
                "reminder_count": reminder_counts.get(user_id, 0)
            })

    users.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jsonify({
        "total_users": len(users),
        "users": users
    })


# -------------------------------
# Main Recommendation
# -------------------------------
@app.route("/recommend", methods=["POST"])
def recommend():

    data = request.get_json() or {}

    symptoms = data.get("symptoms", "").strip()

    if not symptoms:
        return jsonify({"error": "Symptoms required"}), 400

    result = generate_recommendation(symptoms, channel="direct")
    # normalize result for older UI consumers
    if result and isinstance(result, dict) and "possible_condition" in result:
        norm = {
            "disease": result.get("possible_condition"),
            "medicine": result.get("recommended_otc"),
            "advice": result.get("advice"),
            "severity": result.get("severity"),
            "confidence": result.get("confidence"),
            "explanation": result.get("explanation"),
            "source": result.get("source", "UNKNOWN")
        }
        return jsonify(norm)

    return jsonify(result)


_bootstrap_background_jobs()
atexit.register(_stop_reminder_scheduler)


if __name__ == "__main__":
    _bootstrap_background_jobs()
    app.run(host="0.0.0.0", port=5000)
