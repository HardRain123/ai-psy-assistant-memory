import logging

from fastapi import APIRouter, Depends, Header, Query, Request

from app.db import transaction
from app.errors import AUTH_ERROR_CODES, auth_error_response, json_error
from app.security import require_backend_token
from app.services.admin import (
    AUDIT_ACTION_CLEAR_USER_CONVERSATION_HISTORY,
    AUDIT_ACTION_DISABLE_USER,
    AUDIT_ACTION_EXPORT_USER,
    AdminUserError,
    clear_user_conversation_history,
    disable_user_account,
    export_user_data,
    hash_admin_ip,
    list_admin_users,
    record_admin_audit,
)
from app.services.auth import AuthError, require_admin_session
from app.services.sessions import reset_latest_session_to_yesterday


router = APIRouter(
    prefix="/internal/admin",
    dependencies=[Depends(require_backend_token)],
)
logger = logging.getLogger(__name__)


def _request_ip_hash(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    client_host = request.client.host if request.client else ""
    return hash_admin_ip(forwarded_for or client_host)


def _write_admin_audit(
    *,
    request: Request,
    action: str,
    actor_user_id: str | None,
    target_user_id: str | None,
    success: bool,
    error: str | None = None,
) -> None:
    try:
        with transaction() as cur:
            record_admin_audit(
                cur,
                action=action,
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                success=success,
                error=error,
                ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("x-forwarded-user-agent")
                or request.headers.get("user-agent", ""),
            )
    except Exception:
        logger.exception("admin_audit_log_failed action=%s target_user_id=%s", action, target_user_id)


def _auth_error_code(message: str) -> str:
    return AUTH_ERROR_CODES.get(message, "invalid_request")


@router.get("/users")
def get_users(
    q: str = Query(default="", max_length=100),
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            require_admin_session(cur, x_auth_session)
            users = list_admin_users(cur, search=q)
        return {"users": users}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("admin_user_list_failed")
        return json_error(500, "admin_user_list_failed")


@router.post("/self/session/reset-to-yesterday")
def reset_self_session_to_yesterday(x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            session = require_admin_session(cur, x_auth_session)
            user_id = session["user"]["user_id"]
            payload = reset_latest_session_to_yesterday(cur, user_id)
            if not payload:
                return json_error(404, "session_not_found", "session not found")
        return payload
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("admin_self_session_reset_failed")
        return json_error(500, "admin_self_session_reset_failed")


@router.get("/users/{user_id}/export")
def export_user(
    user_id: str,
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    actor_user_id = None
    try:
        with transaction() as cur:
            session = require_admin_session(cur, x_auth_session)
            actor_user_id = session["user"]["user_id"]
            payload = export_user_data(cur, user_id)
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_EXPORT_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=True,
        )
        return payload
    except AuthError as exc:
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_EXPORT_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error=_auth_error_code(exc.message),
        )
        return auth_error_response(exc.status_code, exc.message)
    except AdminUserError as exc:
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_EXPORT_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error=exc.error,
        )
        return json_error(exc.status_code, exc.error)
    except Exception:
        logger.exception("admin_user_export_failed user_id=%s", user_id)
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_EXPORT_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error="admin_user_export_failed",
        )
        return json_error(500, "admin_user_export_failed")


@router.post("/users/{user_id}/disable")
def disable_user(
    user_id: str,
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    actor_user_id = None
    try:
        with transaction() as cur:
            session = require_admin_session(cur, x_auth_session)
            actor_user_id = session["user"]["user_id"]
            payload = disable_user_account(
                cur,
                target_user_id=user_id,
                actor_user_id=actor_user_id,
            )
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_DISABLE_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=True,
        )
        return payload
    except AuthError as exc:
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_DISABLE_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error=_auth_error_code(exc.message),
        )
        return auth_error_response(exc.status_code, exc.message)
    except AdminUserError as exc:
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_DISABLE_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error=exc.error,
        )
        return json_error(exc.status_code, exc.error)
    except Exception:
        logger.exception("admin_user_disable_failed user_id=%s", user_id)
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_DISABLE_USER,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error="admin_user_disable_failed",
        )
        return json_error(500, "admin_user_disable_failed")


@router.delete("/users/{user_id}/conversation-history")
def clear_conversation_history(
    user_id: str,
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    actor_user_id = None
    try:
        with transaction() as cur:
            session = require_admin_session(cur, x_auth_session)
            actor_user_id = session["user"]["user_id"]
            payload = clear_user_conversation_history(cur, user_id)
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_CLEAR_USER_CONVERSATION_HISTORY,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=True,
        )
        return payload
    except AuthError as exc:
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_CLEAR_USER_CONVERSATION_HISTORY,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error=_auth_error_code(exc.message),
        )
        return auth_error_response(exc.status_code, exc.message)
    except AdminUserError as exc:
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_CLEAR_USER_CONVERSATION_HISTORY,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error=exc.error,
        )
        return json_error(exc.status_code, exc.error)
    except Exception:
        logger.exception("admin_user_conversation_history_clear_failed user_id=%s", user_id)
        _write_admin_audit(
            request=request,
            action=AUDIT_ACTION_CLEAR_USER_CONVERSATION_HISTORY,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            success=False,
            error="admin_user_conversation_history_clear_failed",
        )
        return json_error(500, "admin_user_conversation_history_clear_failed")
