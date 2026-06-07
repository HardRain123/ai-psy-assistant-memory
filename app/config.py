import os
from urllib.parse import urlparse


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")
SESSION_MINUTES = _int_env("SESSION_LIMIT_MINUTES", 50)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ENABLE_DEBUG_ENDPOINTS = _bool_env("ENABLE_DEBUG_ENDPOINTS", False)
TESTING = _bool_env("TESTING", False)
TASK_WORKER_ENABLED = _bool_env("TASK_WORKER_ENABLED", True)
TASK_SCAN_INTERVAL_SECONDS = _int_env("TASK_SCAN_INTERVAL_SECONDS", 60)
AUTH_SECRET = os.getenv("AUTH_SECRET", "")
BACKEND_SHARED_TOKEN = os.getenv("BACKEND_SHARED_TOKEN", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_TTL_DAYS = _int_env("SESSION_TTL_DAYS", 7)
PASSWORD_RESET_TTL_MINUTES = _int_env("PASSWORD_RESET_TTL_MINUTES", 30)
PASSWORD_RESET_COOLDOWN_SECONDS = _int_env("PASSWORD_RESET_COOLDOWN_SECONDS", 120)
EMAIL_VERIFICATION_TTL_HOURS = _int_env("EMAIL_VERIFICATION_TTL_HOURS", 24)
TOKEN_RETENTION_DAYS = _int_env("TOKEN_RETENTION_DAYS", 7)
ACCOUNT_RATE_LIMIT_WINDOW_SECONDS = _int_env("ACCOUNT_RATE_LIMIT_WINDOW_SECONDS", 900)
ACCOUNT_RATE_LIMIT_MAX_REQUESTS = _int_env("ACCOUNT_RATE_LIMIT_MAX_REQUESTS", 5)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _int_env("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:3000")

DATABASE_SCHEME = urlparse(DATABASE_URL).scheme
IS_POSTGRES = DATABASE_SCHEME in {"postgres", "postgresql"}
IS_SQLITE = not IS_POSTGRES

# Backward-compatible name used by older modules.
DB = DATABASE_URL


if APP_ENV.lower() == "production":
    missing = [
        name
        for name, value in [
            ("AUTH_SECRET", AUTH_SECRET),
            ("BACKEND_SHARED_TOKEN", BACKEND_SHARED_TOKEN),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required production environment variables: "
            + ", ".join(missing)
        )


def is_testing_mode() -> bool:
    """Read dynamically so tests can toggle protection after app import."""
    return _bool_env("TESTING", TESTING) or os.getenv("APP_ENV", APP_ENV).lower() == "test"
