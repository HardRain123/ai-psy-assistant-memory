import json
import os
from datetime import datetime

from app.services.auth import hash_secret, mask_email
from app.utils import now_iso


AUDIT_ACTION_EXPORT_USER = "admin_user_export"
AUDIT_ACTION_DISABLE_USER = "admin_user_disable"
AUDIT_ACTION_CLEAR_USER_CONVERSATION_HISTORY = "admin_user_conversation_history_clear"
SENSITIVE_ENV_NAMES = (
    "BACKEND_SHARED_TOKEN",
    "DIFY_API_KEY",
    "AUTH_SECRET",
    "ADMIN_PASSWORD",
)
SENSITIVE_AUDIT_TERMS = (
    "password",
    "token",
    "invite",
    "key",
    "secret",
    "dify",
    "backend_shared",
)


class AdminUserError(Exception):
    def __init__(self, error: str, status_code: int = 400):
        super().__init__(error)
        self.error = error
        self.status_code = status_code


def _dt_sort_value(value: str | None) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min


def _parse_handoff_content(document_format: str, content: str):
    if document_format == "json":
        try:
            return json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return content
    return content


def _redact_sensitive_text(value: str) -> str:
    redacted = value
    for name in SENSITIVE_ENV_NAMES:
        redacted = redacted.replace(name, "[已脱敏]")
        secret_value = os.getenv(name, "")
        if secret_value and len(secret_value) >= 4:
            redacted = redacted.replace(secret_value, "[已脱敏]")
    return redacted


def _redact_sensitive_values(value):
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_sensitive_values(item) for key, item in value.items()}
    return value


def _sanitize_audit_user_agent(value: str) -> str:
    redacted = _redact_sensitive_text(value or "")
    lowered = redacted.lower()
    if any(term in lowered for term in SENSITIVE_AUDIT_TERMS):
        return "[已脱敏]"
    return redacted


def hash_admin_ip(ip_address: str | None) -> str:
    normalized = (ip_address or "").strip()
    if not normalized:
        return ""
    return hash_secret(normalized[:120], "admin-audit-ip")


def record_admin_audit(
    cur,
    *,
    action: str,
    actor_user_id: str | None,
    target_user_id: str | None,
    success: bool,
    error: str | None = None,
    ip_hash: str = "",
    user_agent: str = "",
) -> None:
    cur.execute(
        """
        INSERT INTO admin_audit_logs (
            action, actor_user_id, target_user_id, success,
            error, ip_hash, user_agent, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action,
            actor_user_id,
            target_user_id,
            1 if success else 0,
            _redact_sensitive_text(error or "")[:120] if error else None,
            ip_hash[:128],
            _sanitize_audit_user_agent(user_agent)[:300],
            now_iso(),
        ),
    )


def list_admin_users(cur, search: str = "", limit: int = 200) -> list[dict]:
    search = (search or "").strip().lower()
    params: tuple = ()
    where = ""
    if search:
        where = """
        WHERE LOWER(COALESCE(u.username, '')) LIKE ?
           OR LOWER(u.user_id) LIKE ?
        """
        like = f"%{search}%"
        params = (like, like)

    cur.execute(
        f"""
        SELECT u.user_id, u.username, u.email, u.email_verified_at,
               u.is_admin, u.last_login_at, u.disabled_at, u.created_at, u.updated_at,
               (SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.user_id),
               (SELECT COUNT(*) FROM session_messages m WHERE m.user_id = u.user_id),
               (SELECT COUNT(*) FROM memories mem WHERE mem.user_id = u.user_id),
               (SELECT COUNT(*) FROM handoff_documents h WHERE h.user_id = u.user_id)
        FROM users u
        {where}
        ORDER BY u.created_at DESC
        LIMIT ?
        """,
        params + (limit,),
    )
    users = []
    for row in cur.fetchall():
        is_admin = bool(row[4])
        disabled_at = row[6]
        users.append(
            {
                "user_id": row[0],
                "username": row[1] or row[0],
                "email_masked": mask_email(row[2]),
                "has_email": bool(row[2]),
                "email_verified_at": row[3],
                "email_verified": bool(row[3]),
                "is_admin": is_admin,
                "disabled_at": disabled_at,
                "status": "disabled" if disabled_at else "admin" if is_admin else "active",
                "last_login_at": row[5],
                "created_at": row[7],
                "updated_at": row[8],
                "counts": {
                    "sessions": row[9] or 0,
                    "messages": row[10] or 0,
                    "memories": row[11] or 0,
                    "handoff_documents": row[12] or 0,
                },
            }
        )
    return users


def _get_public_user(cur, user_id: str) -> dict:
    cur.execute(
        """
        SELECT user_id, username, email, email_verified_at, is_admin,
               last_login_at, disabled_at, created_at, updated_at
        FROM users
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        raise AdminUserError("user_not_found", status_code=404)
    return {
        "user_id": row[0],
        "username": row[1] or row[0],
        "email_masked": mask_email(row[2]),
        "has_email": bool(row[2]),
        "email_verified_at": row[3],
        "email_verified": bool(row[3]),
        "is_admin": bool(row[4]),
        "last_login_at": row[5],
        "disabled_at": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "status": "disabled" if row[6] else "admin" if row[4] else "active",
    }


def _get_profile(cur, user_id: str) -> dict | None:
    cur.execute(
        """
        SELECT user_id, profile_memory, created_at, updated_at
        FROM user_profiles
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "user_id": row[0],
        "profile_memory": row[1],
        "created_at": row[2],
        "updated_at": row[3],
    }


def _get_care_plan(cur, user_id: str) -> dict | None:
    cur.execute(
        """
        SELECT user_id, plan_text, created_at, updated_at
        FROM care_plans
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "user_id": row[0],
        "plan_text": row[1],
        "created_at": row[2],
        "updated_at": row[3],
    }


def _get_sessions(cur, user_id: str) -> list[dict]:
    cur.execute(
        """
        SELECT id, session_id, user_id, started_at, ended_at, final_saved_at,
               status, auto_close_at, close_reason, timeout_checked_at, stage,
               summary, is_low_content, summary_type, user_message_count,
               user_char_count, risk_level, created_at, updated_at
        FROM sessions
        WHERE user_id = ?
        ORDER BY started_at ASC
        """,
        (user_id,),
    )
    return [
        {
            "id": row[0],
            "session_id": row[1] or row[0],
            "user_id": row[2],
            "started_at": row[3],
            "ended_at": row[4],
            "final_saved_at": row[5],
            "status": row[6],
            "auto_close_at": row[7],
            "close_reason": row[8],
            "timeout_checked_at": row[9],
            "stage": row[10],
            "summary": row[11],
            "is_low_content": bool(row[12]),
            "summary_type": row[13],
            "user_message_count": row[14] or 0,
            "user_char_count": row[15] or 0,
            "risk_level": row[16] or "none",
            "created_at": row[17],
            "updated_at": row[18],
        }
        for row in cur.fetchall()
    ]


def _get_messages(cur, user_id: str) -> list[dict]:
    cur.execute(
        """
        SELECT id, user_id, session_id, role, content, risk_level, created_at
        FROM session_messages
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (user_id,),
    )
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "session_id": row[2],
            "role": row[3],
            "content": row[4],
            "risk_level": row[5] or "none",
            "created_at": row[6],
        }
        for row in cur.fetchall()
    ]


def _get_memories(cur, user_id: str) -> list[dict]:
    cur.execute(
        """
        SELECT id, user_id, session_id, content, memory_type, importance,
               source_type, evidence, confidence, is_hypothesis, should_persist,
               created_at, updated_at
        FROM memories
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (user_id,),
    )
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "session_id": row[2] or "",
            "content": row[3],
            "memory_type": row[4] or "general",
            "importance": row[5] or 1,
            "source_type": row[6] or "manual",
            "evidence": row[7] or "",
            "confidence": row[8] or "medium",
            "is_hypothesis": bool(row[9]),
            "should_persist": bool(row[10]),
            "created_at": row[11],
            "updated_at": row[12],
        }
        for row in cur.fetchall()
    ]


def _get_summaries(cur, user_id: str) -> list[dict]:
    cur.execute(
        """
        SELECT id, user_id, session_id, summary, core_topics, next_focus,
               risk_level, created_at, updated_at
        FROM session_summaries
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (user_id,),
    )
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "session_id": row[2],
            "summary": row[3],
            "core_topics": row[4] or "",
            "next_focus": row[5] or "",
            "risk_level": row[6] or "none",
            "created_at": row[7],
            "updated_at": row[8],
        }
        for row in cur.fetchall()
    ]


def _get_handoff_documents(cur, user_id: str) -> list[dict]:
    cur.execute(
        """
        SELECT document_id, user_id, session_id, title, format, content,
               generated_by, is_low_content, content_quality, generated_reason,
               source_session_count, created_at, updated_at
        FROM handoff_documents
        WHERE user_id = ?
        ORDER BY created_at ASC
        """,
        (user_id,),
    )
    return [
        {
            "document_id": row[0],
            "user_id": row[1],
            "session_id": row[2],
            "title": row[3],
            "format": row[4],
            "content": _parse_handoff_content(row[4], row[5]),
            "generated_by": row[6],
            "is_low_content": bool(row[7]),
            "content_quality": row[8],
            "generated_reason": row[9],
            "source_session_count": row[10] or 1,
            "created_at": row[11],
            "updated_at": row[12],
        }
        for row in cur.fetchall()
    ]


def export_user_data(cur, user_id: str) -> dict:
    user = _get_public_user(cur, user_id)
    profile = _get_profile(cur, user_id)
    care_plan = _get_care_plan(cur, user_id)
    sessions = _get_sessions(cur, user_id)
    messages = _get_messages(cur, user_id)
    memories = _get_memories(cur, user_id)
    summaries = _get_summaries(cur, user_id)
    handoff_documents = _get_handoff_documents(cur, user_id)
    timeline_values = [
        *(item.get("updated_at") or item.get("created_at") for item in sessions),
        *(item.get("created_at") for item in messages),
        *(item.get("updated_at") or item.get("created_at") for item in memories),
        *(item.get("updated_at") or item.get("created_at") for item in summaries),
        *(item.get("updated_at") or item.get("created_at") for item in handoff_documents),
    ]
    last_activity_at = max((_dt_sort_value(value) for value in timeline_values), default=datetime.min)
    last_activity = None if last_activity_at == datetime.min else last_activity_at.isoformat()

    payload = {
        "exported_at": now_iso(),
        "user": {**user, "last_activity_at": last_activity},
        "profile": profile,
        "care_plan": care_plan,
        "sessions": sessions,
        "messages": messages,
        "memories": memories,
        "summaries": summaries,
        "handoff_documents": handoff_documents,
        "counts": {
            "profile": 1 if profile else 0,
            "care_plan": 1 if care_plan else 0,
            "sessions": len(sessions),
            "messages": len(messages),
            "memories": len(memories),
            "summaries": len(summaries),
            "handoff_documents": len(handoff_documents),
        },
        "redactions": [
            "已排除 password、token、hash、key、secret 类敏感字段，包括密码凭据、登录会话校验值、邀请码校验值、后端共享令牌和外部服务密钥。"
        ],
    }
    return _redact_sensitive_values(payload)


def clear_user_conversation_history(cur, target_user_id: str) -> dict:
    user = _get_public_user(cur, target_user_id)
    tables = (
        "session_messages",
        "session_summaries",
        "memories",
        "user_profiles",
        "care_plans",
        "handoff_documents",
        "session_task_history",
        "session_task",
        "sessions",
    )
    deleted = {}
    for table in tables:
        cur.execute(f"DELETE FROM {table} WHERE user_id = ?", (target_user_id,))
        deleted[table] = max(cur.rowcount, 0)

    return {
        "success": True,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
        },
        "deleted": deleted,
        "total_deleted": sum(deleted.values()),
    }


def disable_user_account(cur, target_user_id: str, actor_user_id: str) -> dict:
    if target_user_id == actor_user_id:
        raise AdminUserError("cannot_disable_self", status_code=400)

    cur.execute(
        """
        SELECT user_id, username, is_admin, disabled_at
        FROM users
        WHERE user_id = ?
        LIMIT 1
        """,
        (target_user_id,),
    )
    row = cur.fetchone()
    if not row:
        raise AdminUserError("user_not_found", status_code=404)
    if bool(row[2]):
        raise AdminUserError("cannot_disable_admin", status_code=400)

    now = now_iso()
    disabled_at = row[3] or now
    cur.execute(
        """
        UPDATE users
        SET disabled_at = COALESCE(disabled_at, ?),
            updated_at = ?
        WHERE user_id = ?
        """,
        (now, now, target_user_id),
    )
    cur.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE user_id = ? AND revoked_at IS NULL
        """,
        (now, target_user_id),
    )
    revoked_sessions = cur.rowcount

    return {
        "success": True,
        "user": {
            "user_id": row[0],
            "username": row[1] or row[0],
            "is_admin": False,
            "disabled_at": disabled_at,
            "status": "disabled",
        },
        "disabled_at": disabled_at,
        "already_disabled": bool(row[3]),
        "revoked_sessions": revoked_sessions,
    }
