"""Runtime settings for the task service.

Values come from config/app.json and can be overridden by environment
variables, which is how the deploy script injects per-host settings.
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.environ.get(
    "APP_CONFIG", os.path.join(BASE_DIR, "config", "app.json")
)


def _load_file(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _env_int(name, fallback):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    return int(raw)


def _env_list(name, fallback):
    raw = os.environ.get(name)
    if not raw:
        return fallback
    return [item.strip() for item in raw.split(",") if item.strip()]


_raw = _load_file(CONFIG_PATH)

HOST = os.environ.get("APP_HOST", _raw["server"]["host"])
PORT = _env_int("APP_PORT", _raw["server"]["port"])
DATABASE_PATH = os.environ.get(
    "DATABASE_PATH", os.path.join(BASE_DIR, _raw["database"]["path"])
)
UPLOAD_DIR = os.environ.get(
    "UPLOAD_DIR", os.path.join(BASE_DIR, _raw["uploads"]["directory"])
)
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", _raw["uploads"]["max_bytes"])

TOKEN_SECRET = os.environ.get("TOKEN_SECRET", _raw["auth"]["token_secret"])
TOKEN_TTL_MINUTES = _env_int("TOKEN_TTL_MINUTES", _raw["auth"]["token_ttl_minutes"])
PASSWORD_ITERATIONS = _raw["auth"]["password_iterations"]
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", _raw["auth"]["admin_email"])
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

ALLOWED_ORIGINS = _env_list("ALLOWED_ORIGINS", _raw["server"]["allowed_origins"])
PAGE_SIZE_DEFAULT = _raw["pagination"]["default"]
PAGE_SIZE_MAX = _raw["pagination"]["max"]

JOB_POLL_SECONDS = _raw["worker"]["poll_seconds"]
JOB_LEASE_SECONDS = _raw["worker"]["lease_seconds"]
WEBHOOK_TIMEOUT_SECONDS = _raw["worker"]["webhook_timeout_seconds"]
WEBHOOK_MAX_ATTEMPTS = _raw["worker"]["webhook_max_attempts"]
