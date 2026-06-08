import logging
from datetime import datetime, timedelta

from fastapi import APIRouter

from app.db import transaction
from app.errors import json_error, public_error
from app.schemas import SaveSessionMessageRequest, SaveSessionSummaryRequest
from app.services.sessions import activate_session_if_pending
from app.utils import clean_text, detect_risk_level, now_iso, repair_mojibake_text


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
            if req.role == "user":
                activate_session_if_pending(cur, req.session_id, user_id=req.user_id)

            cur.execute(
                """
                SELECT role, content
                FROM session_messages
                WHERE user_id = ?
                  AND session_id = ?
                  AND created_at >= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    req.user_id,
                    req.session_id,
                    (datetime.now() - timedelta(seconds=30)).isoformat(),
                ),
            )
            recent_row = cur.fetchone()
            if recent_row and recent_row[0] == req.role and recent_row[1] == content:
                return {"success": True, "message": "duplicate message skipped", "risk_level": risk_level}

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
def get_session_transcript(session_id: str, user_id: str | None = None):
    try:
        with transaction() as cur:
            session_user_id = None
            public_session_id = session_id
            if user_id:
                cur.execute(
                    """
                    SELECT user_id, session_id
                    FROM sessions
                    WHERE id = ? OR session_id = ?
                    LIMIT 1
                    """,
                    (session_id, session_id),
                )
                session_row = cur.fetchone()
                if not session_row or session_row[0] != user_id:
                    return json_error(404, "session_not_found", "session not found")
                session_user_id = session_row[0]
                public_session_id = session_row[1] or session_id

            cur.execute(
                """
                SELECT role, content, risk_level, created_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (public_session_id,),
            )
            rows = cur.fetchall()

        messages = [
            {
                "role": row[0],
                "content": repair_mojibake_text(row[1]),
                "risk_level": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]
        transcript_text = "\n".join(
            [f"{'用户' if m['role'] == 'user' else '咨询师'}：{m['content']}" for m in messages]
        )
        return {
            "session_id": public_session_id,
            "user_id": session_user_id,
            "messages": messages,
            "transcript_text": transcript_text,
        }

    except Exception as exc:
        logger.exception("get_session_transcript_failed session_id=%s", session_id)
        return public_error("get_session_transcript_failed")


@router.get("/session-history/{user_id}")
def get_session_history(user_id: str, limit: int = 10):
    safe_limit = min(max(limit, 1), 50)
    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(s.session_id, s.id) AS public_session_id,
                    s.status,
                    s.stage,
                    s.started_at,
                    s.ended_at,
                    s.close_reason,
                    COUNT(m.id) AS message_count,
                    MIN(m.created_at) AS first_message_at,
                    MAX(m.created_at) AS last_message_at
                FROM sessions s
                JOIN session_messages m
                  ON m.session_id = COALESCE(s.session_id, s.id)
                 AND m.user_id = s.user_id
                WHERE s.user_id = ?
                GROUP BY
                    s.id,
                    s.session_id,
                    s.status,
                    s.stage,
                    s.started_at,
                    s.ended_at,
                    s.close_reason
                HAVING COUNT(m.id) > 0
                ORDER BY COALESCE(s.started_at, MAX(m.created_at)) DESC
                LIMIT ?
                """,
                (user_id, safe_limit),
            )
            rows = cur.fetchall()

        return {
            "user_id": user_id,
            "sessions": [
                {
                    "session_id": row[0],
                    "status": row[1],
                    "stage": row[2],
                    "started_at": row[3],
                    "ended_at": row[4],
                    "close_reason": row[5],
                    "message_count": row[6],
                    "first_message_at": row[7],
                    "last_message_at": row[8],
                }
                for row in rows
            ],
        }

    except Exception:
        logger.exception("get_session_history_failed user_id=%s", user_id)
        return public_error("get_session_history_failed")
