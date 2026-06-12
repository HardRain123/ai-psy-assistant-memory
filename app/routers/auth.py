import logging

from fastapi import APIRouter, Depends, Header, Query, Request

from app.db import read_transaction, transaction
from app.errors import auth_error_response, json_error
from app.schemas import (
    ChangePasswordRequest,
    CreateInviteRequest,
    EmailVerificationConfirmRequest,
    EmailVerificationRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    RevokeInviteRequest,
)
from app.security import require_backend_token
from app.services.auth import (
    AuthError,
    authenticate_session,
    change_password,
    confirm_email_verification,
    create_invite_code,
    dispatch_prepared_email,
    EMAIL_VERIFICATION_REQUEST_MESSAGE,
    EMAIL_VERIFICATION_SUCCESS_MESSAGE,
    get_account,
    hash_account_ip,
    list_invite_codes,
    login_user,
    logout_all_sessions,
    logout_session,
    PASSWORD_RESET_REQUEST_MESSAGE,
    register_user,
    require_admin_session,
    request_email_verification,
    request_password_reset,
    reset_password_with_token,
    revoke_invite_code,
)
from app.services.compliance import (
    consent_values_from_request,
    record_user_consents,
    validate_required_consents,
)


router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_backend_token)],
)
logger = logging.getLogger(__name__)


def _raise_auth_error(exc: AuthError):
    return auth_error_response(exc.status_code, exc.message)


def _request_ip_hash(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    client_host = request.client.host if request.client else ""
    return hash_account_ip(forwarded_for or client_host)


@router.post("/auth/register")
def register(req: RegisterRequest, request: Request):
    email_message = None
    try:
        with transaction() as cur:
            consent_values = consent_values_from_request(req)
            validate_required_consents(req.policyVersion, consent_values)
            result = register_user(
                cur,
                req.username,
                req.email,
                req.password,
                req.inviteCode,
                request_ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            record_user_consents(
                cur,
                user_id=result["user"]["user_id"],
                policy_version=req.policyVersion,
                values=consent_values,
                source="registration",
                ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            email_message = result.pop("_email_message", None)
        dispatch_prepared_email(email_message)
        return {"success": True, **result}
    except AuthError as exc:
        return _raise_auth_error(exc)


@router.post("/auth/login")
def login(req: LoginRequest, request: Request):
    try:
        user_agent = request.headers.get("user-agent", "")
        with transaction() as cur:
            result = login_user(cur, req.username, req.password, user_agent=user_agent)
        return result
    except AuthError as exc:
        return _raise_auth_error(exc)


@router.post("/auth/logout")
def logout(x_auth_session: str | None = Header(default=None)):
    with transaction() as cur:
        return logout_session(cur, x_auth_session)


@router.post("/auth/password-reset/request")
def password_reset_request(req: PasswordResetRequest, request: Request):
    email_message = None
    try:
        with transaction() as cur:
            result = request_password_reset(
                cur,
                req.email,
                request_ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            email_message = result.pop("_email_message", None)
    except Exception as exc:
        logger.warning("password_reset_request_failed error_type=%s", type(exc).__name__)

    dispatch_prepared_email(email_message)
    return {"success": True, "message": PASSWORD_RESET_REQUEST_MESSAGE}


@router.post("/auth/password-reset/confirm")
def password_reset_confirm(req: PasswordResetConfirmRequest):
    try:
        with transaction() as cur:
            result = reset_password_with_token(cur, req.token, req.new_password)
        return {"success": True, "message": result["message"]}
    except AuthError as exc:
        return _raise_auth_error(exc)
    except Exception as exc:
        logger.warning("password_reset_confirm_failed error_type=%s", type(exc).__name__)
        return json_error(500, "password_reset_confirm_failed")


@router.get("/auth/account")
def account(x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            return {"success": True, "account": get_account(cur, x_auth_session)}
    except AuthError as exc:
        return _raise_auth_error(exc)
    except Exception as exc:
        logger.warning("account_get_failed error_type=%s", type(exc).__name__)
        return json_error(500, "backend_unavailable")


@router.post("/auth/email/request-verification")
def email_verification_request(
    req: EmailVerificationRequest,
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    email_message = None
    try:
        with transaction() as cur:
            result = request_email_verification(
                cur,
                x_auth_session,
                req.email,
                request_ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            email_message = result.pop("_email_message", None)
        dispatch_prepared_email(email_message)
        return result
    except AuthError as exc:
        return _raise_auth_error(exc)
    except Exception as exc:
        logger.warning("email_verification_request_failed error_type=%s", type(exc).__name__)
        return {"success": True, "message": EMAIL_VERIFICATION_REQUEST_MESSAGE}


@router.post("/auth/email/confirm")
def email_verification_confirm(req: EmailVerificationConfirmRequest):
    try:
        with transaction() as cur:
            return confirm_email_verification(cur, req.token)
    except AuthError as exc:
        return _raise_auth_error(exc)
    except Exception as exc:
        logger.warning("email_verification_confirm_failed error_type=%s", type(exc).__name__)
        return json_error(500, "email_verification_failed")


@router.post("/auth/change-password")
def change_account_password(
    req: ChangePasswordRequest,
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            return change_password(
                cur,
                x_auth_session,
                req.current_password,
                req.new_password,
                request_ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
    except AuthError as exc:
        return _raise_auth_error(exc)
    except Exception as exc:
        logger.warning("change_password_failed error_type=%s", type(exc).__name__)
        return json_error(500, "change_password_failed")


@router.post("/auth/logout-all")
def logout_all(
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            return logout_all_sessions(
                cur,
                x_auth_session,
                request_ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
    except AuthError as exc:
        return _raise_auth_error(exc)
    except Exception as exc:
        logger.warning("logout_all_failed error_type=%s", type(exc).__name__)
        return json_error(500, "logout_all_failed")


@router.get("/auth/me")
def me(
    x_auth_session: str | None = Header(default=None),
    rolling: bool = Query(default=False),
):
    context = transaction if rolling else read_transaction
    with context() as cur:
        session = authenticate_session(cur, x_auth_session, rolling=rolling)

    if not session:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "user": session["user"],
        "expires_at": session["expires_at"],
    }


@router.get("/admin/invites")
def get_invites(x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            require_admin_session(cur, x_auth_session)
            invites = list_invite_codes(cur)
        return {"invites": invites}
    except AuthError as exc:
        return _raise_auth_error(exc)


@router.post("/admin/invites")
def create_invite(req: CreateInviteRequest, x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            session = require_admin_session(cur, x_auth_session)
            invite = create_invite_code(
                cur,
                created_by_user_id=session["user"]["user_id"],
                note=req.note,
                expires_at=req.expires_at,
            )
        return {"success": True, "invite": invite}
    except AuthError as exc:
        return _raise_auth_error(exc)


@router.delete("/admin/invites")
def revoke_invite(req: RevokeInviteRequest, x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            require_admin_session(cur, x_auth_session)
            result = revoke_invite_code(cur, req.invite_id)
        return result
    except AuthError as exc:
        return _raise_auth_error(exc)
