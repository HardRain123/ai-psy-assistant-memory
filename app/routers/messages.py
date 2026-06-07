import logging

from fastapi import APIRouter

from app.db import transaction
from app.errors import public_error
from app.schemas import SaveSessionMessageRequest, SaveSessionSummaryRequest
from app.utils import clean_text, detect_risk_level, now_iso


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/session-summary")
def save_session_summary(req: SaveSessionSummaryRequest):
    summary = clean_text(req.summary)
    if not summary:
        return {"success": False, "message": "empty summary skipped"}

    risk_level = req.risk_level or detect_risk_level(summary)
    now = now_iso()

    try:
        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO session_summaries (
                    user_id, session_id, summary, core_topics, next_focus,
                    risk_level, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.user_id,
                    req.session_id,
                    summary,
                    req.core_topics,
                    req.next_focus,
                    risk_level,
                    now,
                    now,
                ),
            )
            cur.execute(
                """
                UPDATE sessions
                SET summary = ?, risk_level = ?, updated_at = ?
                WHERE user_id = ? AND (id = ? OR session_id = ?)
                """,
                (summary, risk_level, now, req.user_id, req.session_id, req.session_id),
            )

        logger.info("session_summary_saved user_id=%s session_id=%s risk_level=%s", req.user_id, req.session_id, risk_level)
        return {"success": True, "message": "session summary saved", "risk_level": risk_level}

    except Exception as exc:
        logger.exception("save_session_summary_failed user_id=%s session_id=%s", req.user_id, req.session_id)
        return public_error("save_session_summary_failed")


@router.post("/session-message")
def save_session_message(req: SaveSessionMessageRequest):
    if req.role not in ["user", "assistant"]:
        return {"success": False, "message": "role must be user or assistant"}

    content = clean_text(req.content)
    if not content:
        return {"success": False, "message": "empty content skipped"}

    risk_level = detect_risk_level(content) if req.role == "user" else "none"
    now = now_iso()

    try:
        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO session_messages (
                    user_id, session_id, role, content, risk_level, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (req.user_id, req.session_id, req.role, content, risk_level, now),
            )
            if risk_level != "none":
                cur.execute(
                    """
                    UPDATE sessions
                    SET risk_level = ?, updated_at = ?
                    WHERE user_id = ? AND (id = ? OR session_id = ?)
                    """,
                    (risk_level, now, req.user_id, req.session_id, req.session_id),
                )

        logger.info(
            "session_message_saved user_id=%s session_id=%s role=%s risk_level=%s",
            req.user_id,
            req.session_id,
            req.role,
            risk_level,
        )
        return {"success": True, "message": "session message saved", "risk_level": risk_level}

    except Exception as exc:
        logger.exception("save_session_message_failed user_id=%s session_id=%s", req.user_id, req.session_id)
        return public_error("save_session_message_failed")


@router.get("/session-transcript/{session_id}")
def get_session_transcript(session_id: str):
    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT role, content, risk_level, created_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()

        messages = [
            {
                "role": row[0],
                "content": row[1],
                "risk_level": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]
        transcript_text = "\n".join(
            [f"{'用户' if m['role'] == 'user' else '咨询师'}：{m['content']}" for m in messages]
        )
        return {"session_id": session_id, "messages": messages, "transcript_text": transcript_text}

    except Exception as exc:
        logger.exception("get_session_transcript_failed session_id=%s", session_id)
        return public_error("get_session_transcript_failed")
