import logging

from fastapi import APIRouter, Depends, Header, Query, Request

from app.db import transaction
from app.errors import auth_error_response, json_error
from app.schemas import (
    AccountDeletionCancelRequest,
    AccountDeletionRequest,
    ComplaintCreateRequest,
    ConsentUpdateRequest,
)
from app.security import require_backend_token
from app.services.auth import AuthError, hash_account_ip, require_session
from app.services.compliance import (
    cancel_account_deletion,
    consent_values_from_request,
    create_complaint,
    deletion_request_status,
    export_account_data,
    get_user_consents,
    record_user_consents,
    request_account_deletion,
)


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_backend_token)],
)


def _request_ip_hash(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    client_host = request.client.host if request.client else ""
    return hash_account_ip(forwarded_for or client_host)


@router.get("/account/consents")
def account_consents(x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            session = require_session(cur, x_auth_session)
            payload = get_user_consents(cur, session["user"]["user_id"])
        return payload
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)


@router.post("/account/consents")
def grant_account_consents(
    req: ConsentUpdateRequest,
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            session = require_session(cur, x_auth_session)
            payload = record_user_consents(
                cur,
                user_id=session["user"]["user_id"],
                policy_version=req.policyVersion,
                values=consent_values_from_request(req),
                source="account_settings",
                ip_hash=_request_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
        return payload
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)


@router.get("/account/export")
def export_account(x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            session = require_session(cur, x_auth_session)
            payload = export_account_data(cur, session["user"]["user_id"])
        return payload
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("account_export_failed")
        return json_error(500, "account_export_failed")


@router.post("/account/deletion-request")
def create_deletion_request(
    req: AccountDeletionRequest,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            session = require_session(cur, x_auth_session)
            if session["user"]["is_admin"]:
                return json_error(400, "cannot_delete_admin")
            payload = request_account_deletion(
                cur,
                user_id=session["user"]["user_id"],
                confirm_text=req.confirm_text,
            )
        return payload
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except ValueError as exc:
        return json_error(400, str(exc))
    except Exception:
        logger.exception("account_deletion_request_failed")
        return json_error(500, "account_deletion_request_failed")


@router.post("/account/deletion-cancel")
def cancel_deletion_request(req: AccountDeletionCancelRequest):
    try:
        with transaction() as cur:
            return cancel_account_deletion(
                cur,
                request_id=req.request_id,
                cancellation_token=req.cancellation_token,
            )
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except ValueError as exc:
        return json_error(400, str(exc))
    except Exception:
        logger.exception("account_deletion_cancel_failed request_id=%s", req.request_id)
        return json_error(500, "account_deletion_cancel_failed")


@router.get("/account/deletion-status")
def get_deletion_status(
    request_id: str = Query(...),
    cancellation_token: str = Query(...),
):
    try:
        with transaction() as cur:
            return deletion_request_status(
                cur,
                request_id=request_id,
                cancellation_token=cancellation_token,
            )
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("account_deletion_status_failed request_id=%s", request_id)
        return json_error(500, "account_deletion_status_failed")


@router.post("/complaints")
def submit_complaint(
    req: ComplaintCreateRequest,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            session = require_session(cur, x_auth_session)
            complaint = create_complaint(
                cur,
                user_id=session["user"]["user_id"],
                category=req.category,
                content=req.content,
            )
        return {"success": True, "complaint": complaint}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except ValueError as exc:
        return json_error(400, str(exc))
    except Exception:
        logger.exception("complaint_submit_failed")
        return json_error(500, "complaint_submit_failed")
