import base64
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    AUTH_SECRET,
    SESSION_TTL_DAYS,
)
from app.utils import now_iso


logger = logging.getLogger(__name__)

PASSWORD_ITERATIONS = 210_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")


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


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _session_expiry() -> str:
    ttl_days = max(int(SESSION_TTL_DAYS or 7), 1)
    return (datetime.now() + timedelta(days=ttl_days)).isoformat()


def _public_user(row) -> dict:
    return {
        "user_id": row[0],
        "username": row[1],
        "is_admin": bool(row[2]),
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


def register_user(cur, username: str, password: str, invite_code: str) -> dict:
    username = _normalize_username(username)
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

    now = now_iso()
    user_id = f"user_{uuid.uuid4().hex}"
    cur.execute(
        """
        INSERT INTO users (
            user_id, username, password_hash, is_admin,
            created_at, updated_at
        )
        VALUES (?, ?, ?, 0, ?, ?)
        """,
        (user_id, username, password_hash, now, now),
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

    return {
        "user": {"user_id": user_id, "username": username, "is_admin": False},
        "registered_at": now,
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
