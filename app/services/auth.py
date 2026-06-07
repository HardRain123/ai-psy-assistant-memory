import base64
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote

from app.config import (
    ACCOUNT_RATE_LIMIT_MAX_REQUESTS,
    ACCOUNT_RATE_LIMIT_WINDOW_SECONDS,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    AUTH_SECRET,
    EMAIL_VERIFICATION_TTL_HOURS,
    PASSWORD_RESET_COOLDOWN_SECONDS,
    PASSWORD_RESET_TTL_MINUTES,
    SESSION_TTL_DAYS,
    TOKEN_RETENTION_DAYS,
)
from app.services.mail import app_base_url, send_email_message
from app.utils import now_iso


logger = logging.getLogger(__name__)

PASSWORD_ITERATIONS = 210_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,128}@[^@\s]{1,128}\.[^@\s]{2,63}$")

PASSWORD_RESET_REQUEST_MESSAGE = "如果邮箱存在，重置链接会发送到该邮箱。"
PASSWORD_RESET_CONFIRM_SUCCESS_MESSAGE = "密码已重置，请使用新密码重新登录。"
PASSWORD_RESET_INVALID_MESSAGE = "重置链接无效或已过期，请重新申请。"
EMAIL_VERIFICATION_REQUEST_MESSAGE = "如果邮箱可用，验证链接会发送到该邮箱。"
EMAIL_VERIFICATION_SUCCESS_MESSAGE = "邮箱已验证。"
EMAIL_VERIFICATION_INVALID_MESSAGE = "验证链接无效或已过期，请重新申请。"
PASSWORD_CHANGED_MESSAGE = "密码已修改，请使用新密码重新登录。"
LOGOUT_ALL_MESSAGE = "已退出全部设备。"

SECURITY_EVENT_PASSWORD_RESET_REQUESTED = "password_reset_requested"
SECURITY_EVENT_PASSWORD_RESET_COMPLETED = "password_reset_completed"
SECURITY_EVENT_EMAIL_VERIFICATION_REQUESTED = "email_verification_requested"
SECURITY_EVENT_EMAIL_VERIFIED = "email_verified"
SECURITY_EVENT_EMAIL_CHANGED = "email_changed"
SECURITY_EVENT_PASSWORD_CHANGED = "password_changed"
SECURITY_EVENT_LOGOUT_ALL = "logout_all_sessions"


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _auth_secret() -> str:
    return AUTH_SECRET or "development-only-auth-secret"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _normalize_username(username: str) -> str:
    normalized = (username or "").strip().lower()
    if not USERNAME_RE.match(normalized):
        raise AuthError("username must be 3-64 characters using letters, numbers, _ . @ or -")
    return normalized


def _normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if len(normalized) > 254 or not EMAIL_RE.match(normalized):
        raise AuthError("invalid email", status_code=400)
    return normalized


def _normalize_optional_email(email: str) -> str:
    try:
        return _normalize_email(email)
    except AuthError:
        return ""


def _validate_password(password: str):
    if len(password or "") < 8:
        raise AuthError("password must be at least 8 characters")


def hash_password(password: str) -> str:
    _validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        scheme, iterations, salt, expected = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            (password or "").encode("utf-8"),
            _b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(_b64encode(digest), expected)
    except Exception:
        return False


def hash_secret(value: str, purpose: str) -> str:
    digest = hmac.new(
        _auth_secret().encode("utf-8"),
        f"{purpose}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def hash_email_identifier(email: str | None) -> str:
    normalized = _normalize_optional_email(email or "")
    if not normalized:
        return ""
    return hash_secret(normalized, "account-email")


def hash_account_ip(ip_address: str | None) -> str:
    normalized = (ip_address or "").strip()
    if not normalized:
        return ""
    return hash_secret(normalized[:120], "account-ip")


def hash_password_reset_ip(ip_address: str | None) -> str:
    return hash_account_ip(ip_address)


def mask_email(email: str | None) -> str:
    normalized = (email or "").strip()
    if not normalized or "@" not in normalized:
        return ""
    local, domain = normalized.split("@", 1)
    if len(local) <= 1:
        local_mask = local + "***"
    else:
        local_mask = f"{local[0]}***{local[-1]}"
    return f"{local_mask}@{domain}"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _session_expiry() -> str:
    ttl_days = max(int(SESSION_TTL_DAYS or 7), 1)
    return (datetime.now() + timedelta(days=ttl_days)).isoformat()


def _password_reset_expiry() -> str:
    ttl_minutes = max(int(PASSWORD_RESET_TTL_MINUTES or 30), 1)
    return (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()


def _email_verification_expiry() -> str:
    ttl_hours = max(int(EMAIL_VERIFICATION_TTL_HOURS or 24), 1)
    return (datetime.now() + timedelta(hours=ttl_hours)).isoformat()


def _password_reset_cooldown() -> timedelta:
    seconds = max(int(PASSWORD_RESET_COOLDOWN_SECONDS or 120), 0)
    return timedelta(seconds=seconds)


def _token_retention_cutoff() -> str:
    retention_days = max(int(TOKEN_RETENTION_DAYS or 7), 1)
    return (datetime.now() - timedelta(days=retention_days)).isoformat()


def _public_user(row) -> dict:
    return {
        "user_id": row[0],
        "username": row[1],
        "is_admin": bool(row[2]),
    }


def _frontend_url(path: str, token: str) -> str:
    return f"{app_base_url()}{path}?token={quote(token, safe='')}"


def _password_reset_text() -> str:
    return "\n".join(
        [
            "你正在重置 AI 情绪整理助手的登录密码。",
            "",
            "请在 30 分钟内打开下面的一次性链接完成重置：",
            "{RESET_LINK}",
            "",
            "如果这不是你本人操作，可以忽略这封邮件。",
        ]
    )


def _email_verification_text() -> str:
    return "\n".join(
        [
            "请验证你在 AI 情绪整理助手使用的邮箱。",
            "",
            "请在 24 小时内打开下面的一次性链接完成验证：",
            "{VERIFY_LINK}",
            "",
            "如果这不是你本人操作，可以忽略这封邮件。",
        ]
    )


def _create_email_outbox(
    cur,
    *,
    message_type: str,
    recipient_email: str,
    subject: str,
    body_text: str,
    body_html: str = "",
) -> int | None:
    now = now_iso()
    cur.execute(
        """
        INSERT INTO email_outbox (
            message_type, recipient_email, subject, body_text, body_html,
            status, attempt_count, last_error_type, sent_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, ?, ?)
        """,
        (message_type, recipient_email, subject, body_text, body_html, now, now),
    )
    cur.execute(
        """
        SELECT id
        FROM email_outbox
        WHERE message_type = ? AND recipient_email = ? AND created_at = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (message_type, recipient_email, now),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _prepared_email(
    *,
    outbox_id: int | None,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str = "",
) -> dict | None:
    if not outbox_id:
        return None
    return {
        "outbox_id": outbox_id,
        "to_email": to_email,
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
    }


def dispatch_prepared_email(prepared_email: dict | None) -> None:
    if not prepared_email:
        return

    outbox_id = prepared_email.get("outbox_id")
    try:
        send_email_message(
            prepared_email["to_email"],
            prepared_email["subject"],
            prepared_email["body_text"],
            prepared_email.get("body_html", ""),
        )
        status = "sent"
        error_type = None
    except Exception as exc:
        status = "failed"
        error_type = type(exc).__name__
        logger.warning("email_outbox_send_failed outbox_id=%s error_type=%s", outbox_id, error_type)

    from app.db import transaction

    try:
        with transaction() as cur:
            cur.execute(
                """
                UPDATE email_outbox
                SET status = ?,
                    attempt_count = attempt_count + 1,
                    last_error_type = ?,
                    sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, error_type, status, now_iso(), now_iso(), outbox_id),
            )
    except Exception as exc:
        logger.warning("email_outbox_status_update_failed error_type=%s", type(exc).__name__)


def record_account_security_event(
    cur,
    *,
    event_type: str,
    user_id: str | None = None,
    email_hash: str = "",
    ip_hash: str = "",
    user_agent: str = "",
    success: bool = False,
    error: str | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO account_security_events (
            event_type, user_id, email_hash, ip_hash, user_agent, success, error, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            user_id,
            (email_hash or "")[:128],
            (ip_hash or "")[:128],
            (user_agent or "")[:300],
            1 if success else 0,
            (error or "")[:120] if error else None,
            now_iso(),
        ),
    )


def _rate_limited(cur, *, action: str, email_hash: str = "", ip_hash: str = "") -> bool:
    window_seconds = max(int(ACCOUNT_RATE_LIMIT_WINDOW_SECONDS or 900), 1)
    max_requests = max(int(ACCOUNT_RATE_LIMIT_MAX_REQUESTS or 5), 1)
    cutoff = (datetime.now() - timedelta(seconds=window_seconds)).isoformat()

    limited = False
    if email_hash:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM account_rate_limits
            WHERE action = ? AND email_hash = ? AND created_at > ?
            """,
            (action, email_hash, cutoff),
        )
        limited = limited or (cur.fetchone()[0] or 0) >= max_requests

    if ip_hash:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM account_rate_limits
            WHERE action = ? AND ip_hash = ? AND created_at > ?
            """,
            (action, ip_hash, cutoff),
        )
        limited = limited or (cur.fetchone()[0] or 0) >= max_requests

    cur.execute(
        """
        INSERT INTO account_rate_limits (action, email_hash, ip_hash, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (action, email_hash[:128], ip_hash[:128], now_iso()),
    )
    return limited


def cleanup_expired_account_tokens(cur) -> dict:
    cutoff = _token_retention_cutoff()
    cur.execute(
        """
        DELETE FROM password_reset_tokens
        WHERE (used_at IS NOT NULL OR expires_at < ?) AND created_at < ?
        """,
        (now_iso(), cutoff),
    )
    reset_deleted = cur.rowcount
    cur.execute(
        """
        DELETE FROM email_verification_tokens
        WHERE (used_at IS NOT NULL OR expires_at < ?) AND created_at < ?
        """,
        (now_iso(), cutoff),
    )
    verification_deleted = cur.rowcount
    return {
        "password_reset_tokens": reset_deleted,
        "email_verification_tokens": verification_deleted,
    }


def bootstrap_admin(cur):
    cur.execute("SELECT user_id FROM users WHERE is_admin = 1 AND disabled_at IS NULL LIMIT 1")
    if cur.fetchone():
        return {"created": False, "reason": "admin_exists"}

    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        logger.warning("admin_bootstrap_skipped missing ADMIN_USERNAME or ADMIN_PASSWORD")
        return {"created": False, "reason": "missing_admin_env"}

    username = _normalize_username(ADMIN_USERNAME)
    password_hash = hash_password(ADMIN_PASSWORD)
    now = now_iso()

    cur.execute(
        """
        SELECT user_id
        FROM users
        WHERE username = ?
        LIMIT 1
        """,
        (username,),
    )
    row = cur.fetchone()
    if row:
        user_id = row[0]
        cur.execute(
            """
            UPDATE users
            SET password_hash = ?,
                is_admin = 1,
                disabled_at = NULL,
                updated_at = ?
            WHERE user_id = ?
            """,
            (password_hash, now, user_id),
        )
    else:
        user_id = f"user_{uuid.uuid4().hex}"
        cur.execute(
            """
            INSERT INTO users (
                user_id, username, password_hash, is_admin,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (user_id, username, password_hash, now, now),
        )

    logger.info("admin_bootstrapped username=%s user_id=%s", username, user_id)
    return {"created": True, "user_id": user_id, "username": username}


def create_invite_code(cur, created_by_user_id: str, note: str = "", expires_at: str | None = None) -> dict:
    raw_code = secrets.token_urlsafe(18)
    code_hash = hash_secret(raw_code, "invite")
    now = now_iso()
    cur.execute(
        """
        INSERT INTO invite_codes (
            code_hash, created_by_user_id, note, expires_at,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (code_hash, created_by_user_id, note or "", expires_at, now, now),
    )
    cur.execute("SELECT id FROM invite_codes WHERE code_hash = ? LIMIT 1", (code_hash,))
    row = cur.fetchone()
    return {
        "invite_id": row[0] if row else None,
        "code": raw_code,
        "note": note or "",
        "expires_at": expires_at,
        "created_at": now,
    }


def list_invite_codes(cur) -> list[dict]:
    cur.execute(
        """
        SELECT i.id, i.created_by_user_id, i.used_by_user_id, i.note,
               i.expires_at, i.used_at, i.revoked_at, i.created_at, i.updated_at,
               creator.username, used.username
        FROM invite_codes i
        LEFT JOIN users creator ON creator.user_id = i.created_by_user_id
        LEFT JOIN users used ON used.user_id = i.used_by_user_id
        ORDER BY i.created_at DESC
        LIMIT 100
        """
    )
    rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "created_by_user_id": row[1],
            "created_by_username": row[9] or "",
            "used_by_user_id": row[2] or "",
            "used_by_username": row[10] or "",
            "note": row[3] or "",
            "expires_at": row[4],
            "used_at": row[5],
            "revoked_at": row[6],
            "created_at": row[7],
            "updated_at": row[8],
            "status": _invite_status(row[4], row[5], row[6]),
        }
        for row in rows
    ]


def _invite_status(expires_at: str | None, used_at: str | None, revoked_at: str | None) -> str:
    if revoked_at:
        return "revoked"
    if used_at:
        return "used"
    expires = _parse_dt(expires_at)
    if expires and expires <= datetime.now():
        return "expired"
    return "active"


def revoke_invite_code(cur, invite_id: int):
    now = now_iso()
    cur.execute(
        """
        UPDATE invite_codes
        SET revoked_at = COALESCE(revoked_at, ?),
            updated_at = ?
        WHERE id = ?
        """,
        (now, now, invite_id),
    )
    if cur.rowcount == 0:
        raise AuthError("invite not found", status_code=404)
    return {"success": True, "invite_id": invite_id, "revoked_at": now}


def _create_email_verification_token(
    cur,
    *,
    user_id: str,
    email: str,
    request_ip_hash: str = "",
    user_agent: str = "",
) -> dict | None:
    token = secrets.token_urlsafe(48)
    token_hash = hash_secret(token, "email-verification")
    now = now_iso()
    cur.execute(
        """
        INSERT INTO email_verification_tokens (
            user_id, email, token_hash, expires_at, used_at,
            request_ip_hash, user_agent, created_at
        )
        VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            user_id,
            email,
            token_hash,
            _email_verification_expiry(),
            (request_ip_hash or "")[:128],
            (user_agent or "")[:300],
            now,
        ),
    )
    verify_url = _frontend_url("/verify-email", token)
    body_template = _email_verification_text()
    outbox_id = _create_email_outbox(
        cur,
        message_type="email_verification",
        recipient_email=email,
        subject="验证你的邮箱",
        body_text=body_template,
    )
    return _prepared_email(
        outbox_id=outbox_id,
        to_email=email,
        subject="验证你的邮箱",
        body_text=body_template.replace("{VERIFY_LINK}", verify_url),
    )


def register_user(
    cur,
    username: str,
    email: str,
    password: str,
    invite_code: str,
    *,
    request_ip_hash: str = "",
    user_agent: str = "",
) -> dict:
    username = _normalize_username(username)
    email = _normalize_email(email)
    password_hash = hash_password(password)
    invite_hash = hash_secret((invite_code or "").strip(), "invite")

    cur.execute(
        """
        SELECT id, expires_at, used_at, revoked_at
        FROM invite_codes
        WHERE code_hash = ?
        LIMIT 1
        """,
        (invite_hash,),
    )
    invite = cur.fetchone()
    if not invite:
        raise AuthError("invalid invite code", status_code=400)

    invite_id, expires_at, used_at, revoked_at = invite
    if _invite_status(expires_at, used_at, revoked_at) != "active":
        raise AuthError("invite code is not active", status_code=400)

    cur.execute("SELECT user_id FROM users WHERE username = ? LIMIT 1", (username,))
    if cur.fetchone():
        raise AuthError("username already exists", status_code=409)

    cur.execute("SELECT user_id FROM users WHERE email = ? LIMIT 1", (email,))
    if cur.fetchone():
        raise AuthError("email already exists", status_code=409)

    now = now_iso()
    user_id = f"user_{uuid.uuid4().hex}"
    cur.execute(
        """
        INSERT INTO users (
            user_id, username, email, email_verified_at, password_hash, is_admin,
            created_at, updated_at
        )
        VALUES (?, ?, ?, NULL, ?, 0, ?, ?)
        """,
        (user_id, username, email, password_hash, now, now),
    )
    cur.execute(
        """
        UPDATE invite_codes
        SET used_by_user_id = ?,
            used_at = ?,
            updated_at = ?
        WHERE id = ? AND used_at IS NULL AND revoked_at IS NULL
        """,
        (user_id, now, now, invite_id),
    )
    if cur.rowcount != 1:
        raise AuthError("invite code is not active", status_code=400)

    email_message = _create_email_verification_token(
        cur,
        user_id=user_id,
        email=email,
        request_ip_hash=request_ip_hash,
        user_agent=user_agent,
    )
    record_account_security_event(
        cur,
        event_type=SECURITY_EVENT_EMAIL_VERIFICATION_REQUESTED,
        user_id=user_id,
        email_hash=hash_email_identifier(email),
        ip_hash=request_ip_hash,
        user_agent=user_agent,
        success=True,
    )

    return {
        "user": {"user_id": user_id, "username": username, "is_admin": False},
        "registered_at": now,
        "_email_message": email_message,
    }


def create_auth_session(cur, user_id: str, user_agent: str = "", ip_hash: str = "") -> dict:
    token = secrets.token_urlsafe(32)
    token_hash = hash_secret(token, "session")
    now = now_iso()
    expires_at = _session_expiry()
    cur.execute(
        """
        INSERT INTO auth_sessions (
            user_id, token_hash, user_agent, ip_hash,
            created_at, last_seen_at, expires_at, revoked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (user_id, token_hash, user_agent[:300], ip_hash, now, now, expires_at),
    )
    return {"session_token": token, "expires_at": expires_at}


def login_user(cur, username: str, password: str, user_agent: str = "", ip_hash: str = "") -> dict:
    username = _normalize_username(username)
    cur.execute(
        """
        SELECT user_id, username, is_admin, password_hash, disabled_at
        FROM users
        WHERE username = ?
        LIMIT 1
        """,
        (username,),
    )
    row = cur.fetchone()
    if not row or row[4] or not verify_password(password, row[3]):
        raise AuthError("invalid username or password", status_code=401)

    now = now_iso()
    cur.execute(
        "UPDATE users SET last_login_at = ?, updated_at = ? WHERE user_id = ?",
        (now, now, row[0]),
    )
    session = create_auth_session(cur, row[0], user_agent=user_agent, ip_hash=ip_hash)
    return {
        "authenticated": True,
        "user": _public_user(row),
        **session,
    }


def authenticate_session(cur, session_token: str | None, *, rolling: bool = True) -> dict | None:
    if not session_token:
        return None
    token_hash = hash_secret(session_token, "session")
    cur.execute(
        """
        SELECT s.id, s.user_id, s.expires_at, s.revoked_at,
               u.username, u.is_admin, u.disabled_at
        FROM auth_sessions s
        JOIN users u ON u.user_id = s.user_id
        WHERE s.token_hash = ?
        LIMIT 1
        """,
        (token_hash,),
    )
    row = cur.fetchone()
    if not row:
        return None

    session_id, user_id, expires_at, revoked_at, username, is_admin, disabled_at = row
    expires = _parse_dt(expires_at)
    if revoked_at or disabled_at or not expires or expires <= datetime.now():
        return None

    new_expires_at = expires_at
    if rolling:
        new_expires_at = _session_expiry()
        cur.execute(
            """
            UPDATE auth_sessions
            SET last_seen_at = ?,
                expires_at = ?
            WHERE id = ?
            """,
            (now_iso(), new_expires_at, session_id),
        )

    return {
        "user": {
            "user_id": user_id,
            "username": username,
            "is_admin": bool(is_admin),
        },
        "expires_at": new_expires_at,
    }


def logout_session(cur, session_token: str | None) -> dict:
    if not session_token:
        return {"success": True, "revoked": False}
    token_hash = hash_secret(session_token, "session")
    now = now_iso()
    cur.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE token_hash = ?
        """,
        (now, token_hash),
    )
    return {"success": True, "revoked": cur.rowcount > 0}


def get_account(cur, session_token: str | None) -> dict:
    session = require_session(cur, session_token)
    user_id = session["user"]["user_id"]
    cur.execute(
        """
        SELECT user_id, username, email, email_verified_at, is_admin, created_at, updated_at, last_login_at
        FROM users
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        raise AuthError("authentication required", status_code=401)
    return {
        "user_id": row[0],
        "username": row[1] or row[0],
        "email": row[2] or "",
        "email_masked": mask_email(row[2]),
        "has_email": bool(row[2]),
        "email_verified_at": row[3],
        "email_verified": bool(row[3]),
        "is_admin": bool(row[4]),
        "created_at": row[5],
        "updated_at": row[6],
        "last_login_at": row[7],
    }


def _recent_reset_request_exists(cur, user_id: str) -> bool:
    cooldown = _password_reset_cooldown()
    if cooldown.total_seconds() <= 0:
        return False

    cur.execute(
        """
        SELECT created_at
        FROM password_reset_tokens
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    created_at = _parse_dt(row[0]) if row else None
    return bool(created_at and datetime.now() - created_at < cooldown)


def request_password_reset(
    cur,
    email: str,
    *,
    request_ip_hash: str = "",
    user_agent: str = "",
) -> dict:
    cleanup_expired_account_tokens(cur)
    normalized_email = _normalize_optional_email(email)
    email_hash = hash_email_identifier(normalized_email)

    if _rate_limited(
        cur,
        action=SECURITY_EVENT_PASSWORD_RESET_REQUESTED,
        email_hash=email_hash,
        ip_hash=request_ip_hash,
    ):
        record_account_security_event(
            cur,
            event_type=SECURITY_EVENT_PASSWORD_RESET_REQUESTED,
            email_hash=email_hash,
            ip_hash=request_ip_hash,
            user_agent=user_agent,
            success=False,
            error="rate_limited",
        )
        return {"success": True, "message": PASSWORD_RESET_REQUEST_MESSAGE}

    if not normalized_email:
        return {"success": True, "message": PASSWORD_RESET_REQUEST_MESSAGE}

    cur.execute(
        """
        SELECT user_id, disabled_at, email_verified_at
        FROM users
        WHERE email = ?
        LIMIT 1
        """,
        (normalized_email,),
    )
    row = cur.fetchone()
    if not row or row[1] or not row[2]:
        record_account_security_event(
            cur,
            event_type=SECURITY_EVENT_PASSWORD_RESET_REQUESTED,
            user_id=row[0] if row else None,
            email_hash=email_hash,
            ip_hash=request_ip_hash,
            user_agent=user_agent,
            success=False,
            error="unavailable",
        )
        return {"success": True, "message": PASSWORD_RESET_REQUEST_MESSAGE}

    user_id = row[0]
    if _recent_reset_request_exists(cur, user_id):
        record_account_security_event(
            cur,
            event_type=SECURITY_EVENT_PASSWORD_RESET_REQUESTED,
            user_id=user_id,
            email_hash=email_hash,
            ip_hash=request_ip_hash,
            user_agent=user_agent,
            success=False,
            error="cooldown",
        )
        return {"success": True, "message": PASSWORD_RESET_REQUEST_MESSAGE}

    token = secrets.token_urlsafe(48)
    token_hash = hash_secret(token, "password-reset")
    now = now_iso()
    cur.execute(
        """
        INSERT INTO password_reset_tokens (
            user_id, token_hash, expires_at, used_at,
            request_ip_hash, user_agent, created_at
        )
        VALUES (?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            user_id,
            token_hash,
            _password_reset_expiry(),
            (request_ip_hash or "")[:128],
            (user_agent or "")[:300],
            now,
        ),
    )

    reset_url = _frontend_url("/reset-password", token)
    body_template = _password_reset_text()
    outbox_id = _create_email_outbox(
        cur,
        message_type="password_reset",
        recipient_email=normalized_email,
        subject="重置你的密码",
        body_text=body_template,
    )
    record_account_security_event(
        cur,
        event_type=SECURITY_EVENT_PASSWORD_RESET_REQUESTED,
        user_id=user_id,
        email_hash=email_hash,
        ip_hash=request_ip_hash,
        user_agent=user_agent,
        success=True,
    )
    return {
        "success": True,
        "message": PASSWORD_RESET_REQUEST_MESSAGE,
        "_email_message": _prepared_email(
            outbox_id=outbox_id,
            to_email=normalized_email,
            subject="重置你的密码",
            body_text=body_template.replace("{RESET_LINK}", reset_url),
        ),
    }


def reset_password_with_token(cur, token: str, new_password: str) -> dict:
    _validate_password(new_password)
    raw_token = (token or "").strip()
    if not raw_token:
        raise AuthError("password reset token invalid", status_code=400)

    token_hash = hash_secret(raw_token, "password-reset")
    cur.execute(
        """
        SELECT prt.id, prt.user_id, prt.expires_at, prt.used_at, u.disabled_at, u.email
        FROM password_reset_tokens prt
        JOIN users u ON u.user_id = prt.user_id
        WHERE prt.token_hash = ?
        LIMIT 1
        """,
        (token_hash,),
    )
    row = cur.fetchone()
    expires_at = _parse_dt(row[2]) if row else None
    if not row or row[3] or row[4] or not expires_at or expires_at <= datetime.now():
        raise AuthError("password reset token invalid", status_code=400)

    user_id = row[1]
    now = now_iso()
    new_password_hash = hash_password(new_password)
    cur.execute(
        """
        UPDATE users
        SET password_hash = ?,
            updated_at = ?
        WHERE user_id = ?
        """,
        (new_password_hash, now, user_id),
    )
    cur.execute(
        """
        UPDATE password_reset_tokens
        SET used_at = COALESCE(used_at, ?)
        WHERE user_id = ? AND used_at IS NULL
        """,
        (now, user_id),
    )
    if cur.rowcount < 1:
        raise AuthError("password reset token invalid", status_code=400)

    cur.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE user_id = ? AND revoked_at IS NULL
        """,
        (now, user_id),
    )
    revoked_sessions = cur.rowcount
    record_account_security_event(
        cur,
        event_type=SECURITY_EVENT_PASSWORD_RESET_COMPLETED,
        user_id=user_id,
        email_hash=hash_email_identifier(row[5] or ""),
        success=True,
    )
    return {
        "success": True,
        "message": PASSWORD_RESET_CONFIRM_SUCCESS_MESSAGE,
        "revoked_sessions": revoked_sessions,
    }


def request_email_verification(
    cur,
    session_token: str | None,
    email: str = "",
    *,
    request_ip_hash: str = "",
    user_agent: str = "",
) -> dict:
    session = require_session(cur, session_token)
    user_id = session["user"]["user_id"]
    cur.execute(
        """
        SELECT email, email_verified_at
        FROM users
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        raise AuthError("authentication required", status_code=401)

    current_email = row[0] or ""
    requested_email = _normalize_email(email) if (email or "").strip() else current_email
    if not requested_email:
        raise AuthError("invalid email", status_code=400)

    cur.execute(
        """
        SELECT user_id
        FROM users
        WHERE email = ? AND user_id <> ?
        LIMIT 1
        """,
        (requested_email, user_id),
    )
    if cur.fetchone():
        raise AuthError("email already exists", status_code=409)

    now = now_iso()
    email_changed = requested_email != current_email
    if not email_changed and row[1]:
        return {
            "success": True,
            "message": "邮箱已验证，无需重复验证。",
            "email_verified": True,
        }

    email_hash = hash_email_identifier(requested_email)
    cleanup_expired_account_tokens(cur)
    if _rate_limited(
        cur,
        action=SECURITY_EVENT_EMAIL_VERIFICATION_REQUESTED,
        email_hash=email_hash,
        ip_hash=request_ip_hash,
    ):
        record_account_security_event(
            cur,
            event_type=SECURITY_EVENT_EMAIL_VERIFICATION_REQUESTED,
            user_id=user_id,
            email_hash=email_hash,
            ip_hash=request_ip_hash,
            user_agent=user_agent,
            success=False,
            error="rate_limited",
        )
        return {"success": True, "message": EMAIL_VERIFICATION_REQUEST_MESSAGE}

    if email_changed:
        cur.execute(
            """
            UPDATE users
            SET email = ?,
                email_verified_at = NULL,
                updated_at = ?
            WHERE user_id = ?
            """,
            (requested_email, now, user_id),
        )
        record_account_security_event(
            cur,
            event_type=SECURITY_EVENT_EMAIL_CHANGED,
            user_id=user_id,
            email_hash=email_hash,
            ip_hash=request_ip_hash,
            user_agent=user_agent,
            success=True,
        )

    email_message = _create_email_verification_token(
        cur,
        user_id=user_id,
        email=requested_email,
        request_ip_hash=request_ip_hash,
        user_agent=user_agent,
    )
    record_account_security_event(
        cur,
        event_type=SECURITY_EVENT_EMAIL_VERIFICATION_REQUESTED,
        user_id=user_id,
        email_hash=email_hash,
        ip_hash=request_ip_hash,
        user_agent=user_agent,
        success=True,
    )
    return {
        "success": True,
        "message": EMAIL_VERIFICATION_REQUEST_MESSAGE,
        "email": requested_email,
        "email_masked": mask_email(requested_email),
        "email_verified": False,
        "_email_message": email_message,
    }


def confirm_email_verification(cur, token: str) -> dict:
    raw_token = (token or "").strip()
    if not raw_token:
        raise AuthError("email verification token invalid", status_code=400)

    token_hash = hash_secret(raw_token, "email-verification")
    cur.execute(
        """
        SELECT evt.id, evt.user_id, evt.email, evt.expires_at, evt.used_at, u.disabled_at
        FROM email_verification_tokens evt
        JOIN users u ON u.user_id = evt.user_id
        WHERE evt.token_hash = ?
        LIMIT 1
        """,
        (token_hash,),
    )
    row = cur.fetchone()
    expires_at = _parse_dt(row[3]) if row else None
    if not row or row[4] or row[5] or not expires_at or expires_at <= datetime.now():
        raise AuthError("email verification token invalid", status_code=400)

    token_id, user_id, email = row[0], row[1], row[2]
    cur.execute(
        """
        SELECT user_id
        FROM users
        WHERE email = ? AND user_id <> ?
        LIMIT 1
        """,
        (email, user_id),
    )
    if cur.fetchone():
        raise AuthError("email verification token invalid", status_code=400)

    now = now_iso()
    cur.execute(
        """
        UPDATE users
        SET email = ?,
            email_verified_at = ?,
            updated_at = ?
        WHERE user_id = ?
        """,
        (email, now, now, user_id),
    )
    cur.execute(
        """
        UPDATE email_verification_tokens
        SET used_at = COALESCE(used_at, ?)
        WHERE id = ?
        """,
        (now, token_id),
    )
    record_account_security_event(
        cur,
        event_type=SECURITY_EVENT_EMAIL_VERIFIED,
        user_id=user_id,
        email_hash=hash_email_identifier(email),
        success=True,
    )
    return {
        "success": True,
        "message": EMAIL_VERIFICATION_SUCCESS_MESSAGE,
        "email": email,
        "email_verified_at": now,
    }


def change_password(
    cur,
    session_token: str | None,
    current_password: str,
    new_password: str,
    *,
    request_ip_hash: str = "",
    user_agent: str = "",
) -> dict:
    session = require_session(cur, session_token)
    user_id = session["user"]["user_id"]
    _validate_password(new_password)
    cur.execute(
        """
        SELECT password_hash, email
        FROM users
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row or not verify_password(current_password, row[0]):
        record_account_security_event(
            cur,
            event_type=SECURITY_EVENT_PASSWORD_CHANGED,
            user_id=user_id,
            email_hash=hash_email_identifier(row[1] if row else ""),
            ip_hash=request_ip_hash,
            user_agent=user_agent,
            success=False,
            error="invalid_current_password",
        )
        raise AuthError("invalid username or password", status_code=401)

    now = now_iso()
    cur.execute(
        """
        UPDATE users
        SET password_hash = ?,
            updated_at = ?
        WHERE user_id = ?
        """,
        (hash_password(new_password), now, user_id),
    )
    cur.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE user_id = ? AND revoked_at IS NULL
        """,
        (now, user_id),
    )
    revoked_sessions = cur.rowcount
    record_account_security_event(
        cur,
        event_type=SECURITY_EVENT_PASSWORD_CHANGED,
        user_id=user_id,
        email_hash=hash_email_identifier(row[1] or ""),
        ip_hash=request_ip_hash,
        user_agent=user_agent,
        success=True,
    )
    return {
        "success": True,
        "message": PASSWORD_CHANGED_MESSAGE,
        "revoked_sessions": revoked_sessions,
    }


def logout_all_sessions(
    cur,
    session_token: str | None,
    *,
    request_ip_hash: str = "",
    user_agent: str = "",
) -> dict:
    session = require_session(cur, session_token)
    user_id = session["user"]["user_id"]
    now = now_iso()
    cur.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE user_id = ? AND revoked_at IS NULL
        """,
        (now, user_id),
    )
    revoked_sessions = cur.rowcount
    record_account_security_event(
        cur,
        event_type=SECURITY_EVENT_LOGOUT_ALL,
        user_id=user_id,
        ip_hash=request_ip_hash,
        user_agent=user_agent,
        success=True,
    )
    return {
        "success": True,
        "message": LOGOUT_ALL_MESSAGE,
        "revoked_sessions": revoked_sessions,
    }


def require_session(cur, session_token: str | None) -> dict:
    session = authenticate_session(cur, session_token)
    if not session:
        raise AuthError("authentication required", status_code=401)
    return session


def require_admin_session(cur, session_token: str | None) -> dict:
    session = require_session(cur, session_token)
    if not session["user"].get("is_admin"):
        raise AuthError("admin access required", status_code=403)
    return session
