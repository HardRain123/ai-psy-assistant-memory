import logging

from fastapi import APIRouter, Depends, Header, Query, Request

from app.db import transaction
from app.errors import auth_error_response, json_error
from app.schemas import (
    LaunchControlUpdateRequest,
    SafetyAlertRetryRequest,
    SafetyIncidentActionRequest,
    SafetyIncidentCreateRequest,
    SafetyOperatorRoleRequest,
    SensitiveTranscriptAccessRequest,
)
from app.security import require_backend_token
from app.services.admin import hash_admin_ip
from app.services.auth import (
    AuthError,
    list_safety_operators,
    require_admin_session,
    require_safety_operator_session,
    set_safety_operator_role,
)
from app.services.compliance import record_compliance_audit
from app.services.safety import (
    apply_incident_action,
    create_or_merge_safety_incident,
    get_full_incident_transcript,
    get_safety_incident,
    list_safety_incidents,
    record_sensitive_access,
    retry_safety_alert,
    is_within_safety_coverage,
)
from app.services.launch_controls import get_launch_status, set_invite_pause


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_backend_token)],
)


def _operator(cur, session_token: str | None) -> dict:
    return require_safety_operator_session(cur, session_token)


def _ip_hash(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    client_host = request.client.host if request.client else ""
    return hash_admin_ip(forwarded_for or client_host)


@router.post("/safety/incidents")
def create_safety_incident(req: SafetyIncidentCreateRequest):
    try:
        with transaction() as cur:
            incident = create_or_merge_safety_incident(
                cur,
                user_id=req.user_id,
                session_id=req.session_id,
                source=req.source,
                source_risk_level=req.source_risk_level,
                final_risk_level=req.final_risk_level,
                immediate_action_required=req.immediate_action_required,
                risk_flags=req.risk_flags,
                reason=req.reason,
                source_evidence=req.source_evidence,
                trigger_message_id=req.trigger_message_id,
            )
        return {"success": True, "incident": incident}
    except Exception:
        logger.exception("safety_incident_create_failed user_id=%s", req.user_id)
        return json_error(500, "safety_incident_create_failed")


@router.get("/admin/safety/incidents")
def admin_list_safety_incidents(
    status: str = Query(default=""),
    risk_level: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=200),
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            _operator(cur, x_auth_session)
            incidents = list_safety_incidents(cur, status=status, risk_level=risk_level, limit=limit)
        return {"incidents": incidents}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("safety_incident_list_failed")
        return json_error(500, "safety_incident_list_failed")


@router.get("/admin/safety/overview")
def admin_safety_overview(x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            _operator(cur, x_auth_session)
            launch_status = get_launch_status(cur)
            cur.execute(
                """
                SELECT final_risk_level, status, COUNT(*)
                FROM safety_incidents
                GROUP BY final_risk_level, status
                """
            )
            queue_counts = [
                {"risk_level": row[0], "status": row[1], "count": row[2]}
                for row in cur.fetchall()
            ]
        return {
            "coverage_active": is_within_safety_coverage(),
            "coverage_notice": "工作日 09:00–18:00（中国时间）人工安全值守；非值守时段无人实时查看。",
            "launch_status": launch_status,
            "queue_counts": queue_counts,
        }
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("safety_overview_failed")
        return json_error(500, "safety_overview_failed")


@router.post("/admin/safety/invite-pause")
def admin_update_invite_pause(
    req: LaunchControlUpdateRequest,
    x_auth_session: str | None = Header(default=None),
):
    note = (req.note or "").strip()
    if len(note) < 8:
        return json_error(400, "launch_control_note_required")
    try:
        with transaction() as cur:
            session = _operator(cur, x_auth_session)
            status = set_invite_pause(
                cur,
                paused=req.paused,
                reason=note,
                metadata={"manual": True},
                actor_user_id=session["user"]["user_id"],
            )
        return {"success": True, "launch_status": status}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("launch_control_update_failed")
        return json_error(500, "launch_control_update_failed")


@router.get("/admin/safety/operators")
def admin_list_safety_operators(x_auth_session: str | None = Header(default=None)):
    try:
        with transaction() as cur:
            require_admin_session(cur, x_auth_session)
            operators = list_safety_operators(cur)
        return {"operators": operators}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)


@router.post("/admin/safety/operators")
def admin_update_safety_operator(
    req: SafetyOperatorRoleRequest,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            session = require_admin_session(cur, x_auth_session)
            result = set_safety_operator_role(
                cur,
                user_id=req.user_id,
                role=req.role,
                enabled=req.enabled,
                actor_user_id=session["user"]["user_id"],
            )
            record_compliance_audit(
                cur,
                action="safety_operator_role_updated",
                actor_user_id=session["user"]["user_id"],
                target_user_id=req.user_id,
                details={"role": req.role, "enabled": req.enabled},
            )
        return {"success": True, "operator": result}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("safety_operator_update_failed user_id=%s", req.user_id)
        return json_error(500, "safety_operator_update_failed")


@router.get("/admin/safety/incidents/{incident_id}")
def admin_get_safety_incident(
    incident_id: str,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            _operator(cur, x_auth_session)
            incident = get_safety_incident(cur, incident_id)
        if not incident:
            return json_error(404, "safety_incident_not_found")
        return {"incident": incident}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("safety_incident_get_failed incident_id=%s", incident_id)
        return json_error(500, "safety_incident_get_failed")


@router.post("/admin/safety/incidents/{incident_id}/actions")
def admin_update_safety_incident(
    incident_id: str,
    req: SafetyIncidentActionRequest,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            session = _operator(cur, x_auth_session)
            incident = apply_incident_action(
                cur,
                incident_id=incident_id,
                action=req.action,
                actor_user_id=session["user"]["user_id"],
                note=req.note,
                follow_up_at=req.follow_up_at,
            )
        return {"success": True, "incident": incident}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except LookupError:
        return json_error(404, "safety_incident_not_found")
    except ValueError:
        return json_error(400, "invalid_safety_action")
    except Exception:
        logger.exception("safety_incident_action_failed incident_id=%s", incident_id)
        return json_error(500, "safety_incident_action_failed")


@router.post("/admin/safety/incidents/{incident_id}/alert-retry")
def admin_retry_safety_alert(
    incident_id: str,
    req: SafetyAlertRetryRequest,
    x_auth_session: str | None = Header(default=None),
):
    try:
        with transaction() as cur:
            session = _operator(cur, x_auth_session)
            incident = retry_safety_alert(
                cur,
                incident_id=incident_id,
                actor_user_id=session["user"]["user_id"],
                note=req.note,
            )
        return {"success": True, "incident": incident}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except LookupError:
        return json_error(404, "safety_incident_not_found")
    except ValueError:
        return json_error(409, "safety_alert_retry_not_allowed")
    except Exception:
        logger.exception("safety_alert_retry_failed incident_id=%s", incident_id)
        return json_error(500, "safety_alert_retry_failed")


@router.post("/admin/safety/incidents/{incident_id}/full-transcript-access")
def admin_access_safety_transcript(
    incident_id: str,
    req: SensitiveTranscriptAccessRequest,
    request: Request,
    x_auth_session: str | None = Header(default=None),
):
    reason = (req.reason or "").strip()
    if len(reason) < 8:
        return json_error(400, "sensitive_access_reason_required")
    try:
        with transaction() as cur:
            session = _operator(cur, x_auth_session)
            incident = get_safety_incident(cur, incident_id)
            if not incident:
                return json_error(404, "safety_incident_not_found")
            record_sensitive_access(
                cur,
                actor_user_id=session["user"]["user_id"],
                target_user_id=incident["user_id"],
                resource_type="safety_incident_full_transcript",
                resource_id=incident_id,
                reason=reason,
                ip_hash=_ip_hash(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            transcript = get_full_incident_transcript(cur, incident=incident)
        return {"incident_id": incident_id, "transcript": transcript}
    except AuthError as exc:
        return auth_error_response(exc.status_code, exc.message)
    except Exception:
        logger.exception("safety_transcript_access_failed incident_id=%s", incident_id)
        return json_error(500, "safety_transcript_access_failed")
