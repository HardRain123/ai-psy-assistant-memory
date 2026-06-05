from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.db import transaction
from app.schemas import (
    CreateInviteRequest,
    LoginRequest,
    RegisterRequest,
    RevokeInviteRequest,
)
from app.security import require_backend_token
from app.services.auth import (
    AuthError,
    authenticate_session,
    create_invite_code,
    list_invite_codes,
    login_user,
    logout_session,
    register_user,
    require_admin_session,
    revoke_invite_code,
)


router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_backend_token)],
)


def _raise_auth_error(exc: AuthError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/auth/register")
def register(req: RegisterRequest):
    try:
        with transaction() as cur:
            result = register_user(cur, req.username, req.password, req.inviteCode)
        return {"success": True, **result}
    except AuthError as exc:
        _raise_auth_error(exc)


@router.post("/auth/login")
def login(req: LoginRequest, request: Request):
    try:
        user_agent = request.headers.get("user-agent", "")
        with transaction() as cur:
            result = login_user(cur, req.username, req.password, user_agent=user_agent)
        return result
    except AuthError as exc:
        _raise_auth_error(exc)


@router.post("/auth/logout")
def logout(x_auth_session: str | None = Header(default=None)):
    with transaction() as cur:
        return logout_session(cur, x_auth_session)


@router.get("/auth/me")
def me(x_auth_session: str | None = Header(default=None)):
    with transaction() as cur:
        session = authenticate_session(cur, x_auth_session)

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
        _raise_auth_error(exc)


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
        _raise_auth_error(exc)


@router.delete("/admin/invites")
def revoke_invite(req: RevokeInviteRequest, x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            require_admin_session(cur, x_auth_session)
            result = revoke_invite_code(cur, req.invite_id)
        return result
    except AuthError as exc:
        _raise_auth_error(exc)
