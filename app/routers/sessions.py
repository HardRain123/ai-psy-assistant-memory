import logging
from datetime import datetime

from fastapi import APIRouter

from app.db import read_transaction, transaction
from app.errors import public_error
from app.schemas import FinalizeSessionRequest
from app.services.sessions import (
    ENDED_STATUSES,
    PENDING_STATUS,
    activate_latest_pending_session,
    active_status_response,
    create_pending_session,
    create_session,
    end_session_workflow,
    ended_status_response,
    get_latest_session,
    has_session_today,
)
from app.services.session_autofinalize import (
    auto_finalize_session_with_dify,
    auto_finalize_stale_sessions_for_user,
)
from app.utils import bool_text, calc_stage, parse_dt


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/session/status/{user_id}")
def session_status(user_id: str):
    try:
        auto_finalize_stale_sessions_for_user(user_id, reason="auto_previous_day_status_check")

        with read_transaction() as cur:
            row = get_latest_session(cur, user_id)

        if not row:
            with transaction() as cur:
                return create_pending_session(cur, user_id)

        (
            session_pk,
            public_session_id,
            _user_id,
            started_at_str,
            ended_at_str,
            status,
            final_saved_at,
            auto_close_at,
            stage,
            summary,
            risk_level,
            is_low_content,
            summary_type,
            user_message_count,
            user_char_count,
            _dify_conversation_id,
        ) = row
        session_id = public_session_id or session_pk

        if status == PENDING_STATUS:
            return active_status_response(row)

        if status in ENDED_STATUSES:
            with read_transaction() as cur:
                if has_session_today(cur, user_id):
                    return ended_status_response(
                        session_id=session_id,
                        started_at=started_at_str,
                        ended_at=ended_at_str,
                        final_saved_at=final_saved_at,
                        risk_level=risk_level,
                    )
            with transaction() as cur:
                return create_pending_session(cur, user_id)

        started_at = parse_dt(started_at_str)
        today = datetime.now().date()
        elapsed, remaining, current_stage = calc_stage(started_at)
        auto_close_reached = bool(auto_close_at and parse_dt(auto_close_at) <= datetime.now())

        if started_at.date() < today:
            auto_finalize_session_with_dify(
                user_id=user_id,
                session_id=session_id,
                reason="auto_previous_day_status_check",
            )
            logger.info("previous_day_session_closed user_id=%s session_id=%s", user_id, session_id)
            with transaction() as cur:
                return create_pending_session(cur, user_id)

        if current_stage == "ended" or auto_close_reached:
            result = auto_finalize_session_with_dify(
                user_id=user_id,
                session_id=session_id,
                reason="auto_timeout_status_check",
            )
            return ended_status_response(
                session_id=session_id,
                started_at=started_at_str,
                ended_at=result["ended_at"],
                final_saved_at=result["final_saved_at"],
                risk_level=result.get("risk_level", risk_level),
                message="本次 50 分钟咨询已经结束，明天可以开始下一次咨询。",
                elapsed_minutes=elapsed,
            )

        return active_status_response(row)

    except Exception as exc:
        logger.exception("session_status_failed user_id=%s", user_id)
        return public_error("session_status_failed")


@router.post("/session/start/{user_id}")
def start_session(user_id: str):
    try:
        auto_finalize_stale_sessions_for_user(user_id, reason="auto_close_before_manual_start")

        with transaction() as cur:
            if has_session_today(cur, user_id):
                return {
                    "success": False,
                    "can_continue": False,
                    "can_start_new_session": False,
                    "daily_limit_reached": True,
                    "message": "今天已经进行过一次正式咨询，明天可以开始下一次。",
                }

            pending_result = activate_latest_pending_session(cur, user_id)
            if pending_result:
                return {"success": True, **pending_result}

            cur.execute(
                """
                SELECT id, session_id
                FROM sessions
                WHERE user_id = ? AND status = 'open'
                ORDER BY started_at ASC
                """,
                (user_id,),
            )
            for session_pk, public_session_id in cur.fetchall():
                end_session_workflow(
                    cur,
                    public_session_id or session_pk,
                    user_id=user_id,
                    reason="auto_close_before_manual_start",
                )

            result = create_session(cur, user_id)
            return {"success": True, **result}

    except Exception as exc:
        logger.exception("start_session_failed user_id=%s", user_id)
        return public_error("start_session_failed")


@router.post("/session/finalize")
def finalize_session(req: FinalizeSessionRequest):
    try:
        with transaction() as cur:
            if req.session_id:
                session_id = req.session_id
            else:
                row = get_latest_session(cur, req.user_id)
                if not row:
                    return {
                        "success": False,
                        "message": "session not found",
                        "final_saved": False,
                    }
                session_id = row[1] or row[0]

            result = end_session_workflow(
                cur,
                session_id,
                user_id=req.user_id,
                reason="manual_finalize",
            )

            return {
                "success": True,
                "already_finalized": result["already_finalized"],
                "user_id": result["user_id"],
                "session_id": result["session_id"],
                "status": "ended",
                "ended_at": result["ended_at"],
                "final_saved": True,
                "final_saved_at": result["final_saved_at"],
                "handoff_document_id": result.get("handoff_document_id"),
                "longitudinal_events": result.get("longitudinal_events", []),
                "care_plan_updated": result.get("care_plan_updated", False),
                "profile_updated": result.get("profile_updated", False),
                "is_low_content": result.get("is_low_content", False),
                "summary_type": result.get("summary_type", "formal"),
                "message": "session finalized",
            }

    except Exception as exc:
        logger.exception("finalize_session_failed user_id=%s", req.user_id)
        return public_error("finalize_session_failed", final_saved=False)
