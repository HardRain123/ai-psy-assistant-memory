import logging

from fastapi import APIRouter

from app.errors import public_error
from app.routers.care_plan import get_care_plan
from app.routers.context import get_context
from app.routers.messages import get_session_transcript, save_session_message
from app.routers.sessions import session_status
from app.schemas import DifyTurnPrepRequest, SaveSessionMessageRequest
from app.services.dify_auto_finalize import auto_finalize_target_from_query, is_auto_finalize_query
from app.services.session_autofinalize import find_latest_auto_finalize_target
from app.utils import clean_text


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/dify/turn-prep")
def dify_turn_prep(req: DifyTurnPrepRequest):
    """Aggregate the synchronous Dify pre-response HTTP calls into one backend round trip."""
    query = clean_text(req.query)
    if not query:
        return {"success": False, "message": "empty query skipped"}

    try:
        auto_finalize = bool(req.auto_finalize_session) or is_auto_finalize_query(query)
        if auto_finalize:
            target = None
            target_session_id = clean_text(req.target_session_id or "") or auto_finalize_target_from_query(query)
            if target_session_id:
                target = {"session_id": target_session_id, "started_at": None}
            else:
                target = find_latest_auto_finalize_target(req.user_id)
            if not target:
                return {
                    "success": False,
                    "message": "auto finalize target missing",
                    "auto_finalize_session": True,
                }

            session_id = str(target.get("session_id") or "").strip()
            context = get_context(req.user_id)
            transcript = get_session_transcript(session_id, user_id=req.user_id)
            care_plan = get_care_plan(req.user_id)

            transcript_text = str(transcript.get("transcript_text") or "")
            messages = transcript.get("messages") if isinstance(transcript, dict) else []
            if not isinstance(messages, list):
                messages = []

            return {
                "success": True,
                "user_id": req.user_id,
                "session_id": session_id,
                "status": "open",
                "started_at": target.get("started_at"),
                "ended_at": None,
                "elapsed_minutes": 50,
                "remaining_minutes": 0,
                "stage": "ending",
                "session_stage": "ending",
                "is_new_session": False,
                "is_new_session_str": "false",
                "can_continue": False,
                "can_start_new_session": False,
                "daily_limit_reached": False,
                "final_saved": False,
                "risk_level": "none",
                "message": "auto finalize session",
                "user_message_saved": False,
                "user_message_risk_level": "none",
                "context_text": context.get("context_text", ""),
                "profile_memory": context.get("profile_memory", ""),
                "recent_screening": context.get("recent_screening", ""),
                "recent_session_summaries": context.get("recent_session_summaries", ""),
                "recent_memories": context.get("recent_memories", ""),
                "transcript_text": transcript_text,
                "message_count": len(messages),
                "has_transcript": bool(transcript_text.strip()),
                "care_plan_exists": bool(care_plan.get("exists", False)),
                "plan_text": care_plan.get("plan_text", ""),
                "care_plan_updated_at": care_plan.get("updated_at"),
                "auto_finalize_session": True,
                "target_session_id": session_id,
                "session_status": {"status": "open", "session_id": session_id, "session_stage": "ending"},
                "message_save": {"success": False, "message": "auto finalize trigger not saved"},
                "context": context,
                "transcript": transcript,
                "care_plan": care_plan,
            }

        status = session_status(req.user_id)
        session_id = str(status.get("session_id") or "").strip()
        if not session_id:
            return {"success": False, "message": "session_id missing", "session_status": status}

        message_save = save_session_message(
            SaveSessionMessageRequest(
                user_id=req.user_id,
                session_id=session_id,
                role="user",
                content=query,
            )
        )
        if message_save.get("success"):
            status = session_status(req.user_id)

        context = get_context(req.user_id)
        transcript = get_session_transcript(session_id)
        care_plan = get_care_plan(req.user_id)

        transcript_text = str(transcript.get("transcript_text") or "")
        messages = transcript.get("messages") if isinstance(transcript, dict) else []
        if not isinstance(messages, list):
            messages = []

        return {
            "success": True,
            "user_id": req.user_id,
            "session_id": session_id,
            "status": status.get("status"),
            "started_at": status.get("started_at"),
            "ended_at": status.get("ended_at"),
            "elapsed_minutes": status.get("elapsed_minutes"),
            "remaining_minutes": status.get("remaining_minutes", 0),
            "stage": status.get("stage") or status.get("session_stage") or "",
            "session_stage": status.get("session_stage") or status.get("stage") or "",
            "is_new_session": bool(status.get("is_new_session", False)),
            "is_new_session_str": str(status.get("is_new_session_str", "false")),
            "can_continue": bool(status.get("can_continue", False)),
            "can_start_new_session": bool(status.get("can_start_new_session", False)),
            "daily_limit_reached": bool(status.get("daily_limit_reached", False)),
            "final_saved": bool(status.get("final_saved", False)),
            "risk_level": status.get("risk_level", "none"),
            "message": status.get("message", ""),
            "user_message_saved": bool(message_save.get("success", False)),
            "user_message_risk_level": message_save.get("risk_level", "none"),
            "context_text": context.get("context_text", ""),
            "profile_memory": context.get("profile_memory", ""),
            "recent_screening": context.get("recent_screening", ""),
            "recent_session_summaries": context.get("recent_session_summaries", ""),
            "recent_memories": context.get("recent_memories", ""),
            "transcript_text": transcript_text,
            "message_count": len(messages),
            "has_transcript": bool(transcript_text.strip()),
            "care_plan_exists": bool(care_plan.get("exists", False)),
            "plan_text": care_plan.get("plan_text", ""),
            "care_plan_updated_at": care_plan.get("updated_at"),
            "session_status": status,
            "message_save": message_save,
            "context": context,
            "transcript": transcript,
            "care_plan": care_plan,
        }

    except Exception:
        logger.exception("dify_turn_prep_failed user_id=%s", req.user_id)
        return public_error("dify_turn_prep_failed")
