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

MESSAGE_SYNC_STATUSES = {"pending", "streaming", "complete", "error"}
ASSISTANT_DEDUPE_WINDOW_SECONDS = 5 * 60
ASSISTANT_TURN_INFER_SECONDS = 15 * 60


def _clean_optional(value: str | None) -> str:
    return clean_text(value or "")


def _safe_sync_status(value: str | None) -> str:
    status = clean_text(value or "complete").lower()
    return status if status in MESSAGE_SYNC_STATUSES else "complete"


def _update_session_conversation(cur, user_id: str, session_id: str, conversation_id: str, now: str):
    if not conversation_id:
        return
    cur.execute(
        """
        UPDATE sessions
        SET dify_conversation_id = ?,
            updated_at = ?
        WHERE user_id = ? AND (id = ? OR session_id = ?)
        """,
        (conversation_id, now, user_id, session_id, session_id),
    )


def _find_existing_message(cur, user_id: str, session_id: str, role: str, turn_id: str, external_message_id: str):
    if external_message_id:
        cur.execute(
            """
            SELECT id, content, sync_status, turn_id, external_message_id
            FROM session_messages
            WHERE user_id = ?
              AND session_id = ?
              AND role = ?
              AND external_message_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, session_id, role, external_message_id),
        )
        row = cur.fetchone()
        if row:
            return row

    if turn_id:
        cur.execute(
            """
            SELECT id, content, sync_status, turn_id, external_message_id
            FROM session_messages
            WHERE user_id = ?
              AND session_id = ?
              AND role = ?
              AND turn_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, session_id, role, turn_id),
        )
        return cur.fetchone()

    return None


def _find_latest_user_turn_id(cur, user_id: str, session_id: str) -> str:
    cur.execute(
        """
        SELECT turn_id
        FROM session_messages
        WHERE user_id = ?
          AND session_id = ?
          AND role = 'user'
          AND turn_id IS NOT NULL
          AND turn_id != ''
          AND created_at >= ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            user_id,
            session_id,
            (datetime.now() - timedelta(seconds=ASSISTANT_TURN_INFER_SECONDS)).isoformat(),
        ),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else ""


def _messages_overlap(a: str, b: str) -> bool:
    left = clean_text(a)
    right = clean_text(b)
    if not left or not right:
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def _merged_message(existing: dict, incoming: dict) -> dict:
    existing_content = clean_text(str(existing.get("content") or ""))
    incoming_content = clean_text(str(incoming.get("content") or ""))
    use_incoming_content = len(incoming_content) >= len(existing_content)
    merged = dict(incoming if use_incoming_content else existing)
    source = existing if use_incoming_content else incoming

    merged["content"] = incoming_content if use_incoming_content else existing_content
    merged["turn_id"] = merged.get("turn_id") or source.get("turn_id") or ""
    merged["external_message_id"] = merged.get("external_message_id") or source.get("external_message_id") or ""
    if existing.get("sync_status") == "complete" or incoming.get("sync_status") == "complete":
        merged["sync_status"] = "complete"
    else:
        merged["sync_status"] = merged.get("sync_status") or source.get("sync_status") or "complete"
    merged["created_at"] = existing.get("created_at") or incoming.get("created_at")
    merged["updated_at"] = incoming.get("updated_at") or existing.get("updated_at") or merged.get("created_at")
    return merged


def _coalesce_streaming_prefix_messages(messages: list[dict]) -> list[dict]:
    coalesced: list[dict] = []
    for message in messages:
        if not coalesced:
            coalesced.append(message)
            continue

        previous = coalesced[-1]
        if previous.get("role") != "assistant" or message.get("role") != "assistant":
            coalesced.append(message)
            continue

        previous_content = clean_text(str(previous.get("content") or ""))
        current_content = clean_text(str(message.get("content") or ""))
        same_turn = bool(previous.get("turn_id") and previous.get("turn_id") == message.get("turn_id"))
        legacy_prefix = not previous.get("turn_id") and not message.get("turn_id")
        assistant_overlap = _messages_overlap(previous_content, current_content)

        if (same_turn or legacy_prefix or assistant_overlap) and current_content == previous_content:
            coalesced[-1] = _merged_message(previous, message)
            continue
        if (same_turn or legacy_prefix or assistant_overlap) and current_content.startswith(previous_content):
            coalesced[-1] = _merged_message(previous, message)
            continue
        if (same_turn or legacy_prefix or assistant_overlap) and previous_content.startswith(current_content):
            coalesced[-1] = _merged_message(previous, message)
            continue

        coalesced.append(message)
    return coalesced


def _find_recent_overlapping_assistant(cur, user_id: str, session_id: str, content: str):
    cur.execute(
        """
        SELECT id, content, sync_status, turn_id, external_message_id
        FROM session_messages
        WHERE user_id = ?
          AND session_id = ?
          AND role = 'assistant'
          AND created_at >= ?
        ORDER BY id DESC
        LIMIT 6
        """,
        (
            user_id,
            session_id,
            (datetime.now() - timedelta(seconds=ASSISTANT_DEDUPE_WINDOW_SECONDS)).isoformat(),
        ),
    )
    for row in cur.fetchall():
        if _messages_overlap(row[1], content):
            return row
    return None


def _update_existing_message(
    cur,
    *,
    message_id: int,
    content: str,
    risk_level: str,
    sync_status: str,
    turn_id: str,
    external_message_id: str,
    now: str,
):
    cur.execute(
        """
        UPDATE session_messages
        SET content = ?,
            risk_level = ?,
            sync_status = ?,
            turn_id = ?,
            external_message_id = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            content,
            risk_level,
            sync_status,
            turn_id or None,
            external_message_id or None,
            now,
            message_id,
        ),
    )


def _delete_recent_overlapping_assistant_duplicates(cur, user_id: str, session_id: str, keep_id: int, content: str):
    cur.execute(
        """
        SELECT id, content
        FROM session_messages
        WHERE user_id = ?
          AND session_id = ?
          AND role = 'assistant'
          AND id != ?
          AND created_at >= ?
        ORDER BY id DESC
        LIMIT 8
        """,
        (
            user_id,
            session_id,
            keep_id,
            (datetime.now() - timedelta(seconds=ASSISTANT_DEDUPE_WINDOW_SECONDS)).isoformat(),
        ),
    )
    duplicate_ids = [row[0] for row in cur.fetchall() if _messages_overlap(row[1], content)]
    for duplicate_id in duplicate_ids:
        cur.execute("DELETE FROM session_messages WHERE id = ?", (duplicate_id,))


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
                SELECT id
                FROM session_summaries
                WHERE user_id = ? AND session_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (req.user_id, req.session_id),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    UPDATE session_summaries
                    SET summary = ?,
                        core_topics = ?,
                        next_focus = ?,
                        risk_level = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        summary,
                        req.core_topics,
                        req.next_focus,
                        risk_level,
                        now,
                        existing[0],
                    ),
                )
            else:
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
        return {
            "success": True,
            "message": "session summary saved",
            "risk_level": risk_level,
            "updated_existing": bool(existing),
        }

    except Exception as exc:
        logger.exception("save_session_summary_failed user_id=%s session_id=%s", req.user_id, req.session_id)
        return public_error("save_session_summary_failed")


@router.post("/session-message")
def save_session_message(req: SaveSessionMessageRequest):
    if req.role not in ["user", "assistant"]:
        return {"success": False, "message": "role must be user or assistant"}

    content = clean_text(req.content)
    turn_id = _clean_optional(req.turn_id)
    external_message_id = _clean_optional(req.external_message_id)
    sync_status = _safe_sync_status(req.sync_status)
    dify_conversation_id = _clean_optional(req.dify_conversation_id)
    now = now_iso()

    if not content:
        if dify_conversation_id:
            try:
                with transaction() as cur:
                    _update_session_conversation(cur, req.user_id, req.session_id, dify_conversation_id, now)
                return {"success": True, "message": "conversation id saved", "risk_level": "none"}
            except Exception:
                logger.exception("save_session_conversation_failed user_id=%s session_id=%s", req.user_id, req.session_id)
                return public_error("save_session_message_failed")
        return {"success": False, "message": "empty content skipped"}

    risk_level = detect_risk_level(content) if req.role == "user" else "none"
    try:
        with transaction() as cur:
            if req.role == "user":
                activate_session_if_pending(cur, req.session_id, user_id=req.user_id)
            _update_session_conversation(cur, req.user_id, req.session_id, dify_conversation_id, now)
            if req.role == "assistant" and not turn_id:
                turn_id = _find_latest_user_turn_id(cur, req.user_id, req.session_id)

            should_upsert = bool(turn_id or external_message_id)

            if should_upsert:
                existing_row = _find_existing_message(
                    cur,
                    req.user_id,
                    req.session_id,
                    req.role,
                    turn_id,
                    external_message_id,
                )
                if not existing_row and req.role == "assistant":
                    existing_row = _find_recent_overlapping_assistant(cur, req.user_id, req.session_id, content)
                if existing_row:
                    message_id, existing_content, existing_status, existing_turn_id, existing_external_id = existing_row
                    final_status = "complete" if sync_status == "complete" or existing_status == "complete" else sync_status
                    final_content = content
                    if existing_status == "complete" and sync_status != "complete":
                        final_content = existing_content
                    elif sync_status != "complete" and len(existing_content or "") > len(content):
                        final_content = existing_content

                    final_turn_id = turn_id or existing_turn_id or ""
                    final_external_id = external_message_id or existing_external_id or ""
                    _update_existing_message(
                        cur,
                        message_id=message_id,
                        content=final_content,
                        risk_level=risk_level,
                        sync_status=final_status,
                        turn_id=final_turn_id,
                        external_message_id=final_external_id,
                        now=now,
                    )
                    if req.role == "assistant":
                        _delete_recent_overlapping_assistant_duplicates(
                            cur,
                            req.user_id,
                            req.session_id,
                            message_id,
                            final_content,
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
                    return {
                        "success": True,
                        "message": "message updated",
                        "risk_level": risk_level,
                        "sync_status": final_status,
                        "turn_id": final_turn_id,
                        "external_message_id": final_external_id,
                    }

            if not should_upsert:
                if req.role == "assistant":
                    existing_row = _find_recent_overlapping_assistant(cur, req.user_id, req.session_id, content)
                    if existing_row:
                        message_id, existing_content, existing_status, existing_turn_id, existing_external_id = existing_row
                        final_content = content if len(content) >= len(existing_content or "") else existing_content
                        final_status = "complete" if sync_status == "complete" or existing_status == "complete" else sync_status
                        _update_existing_message(
                            cur,
                            message_id=message_id,
                            content=final_content,
                            risk_level=risk_level,
                            sync_status=final_status,
                            turn_id=existing_turn_id or "",
                            external_message_id=existing_external_id or "",
                            now=now,
                        )
                        _delete_recent_overlapping_assistant_duplicates(
                            cur,
                            req.user_id,
                            req.session_id,
                            message_id,
                            final_content,
                        )
                        return {
                            "success": True,
                            "message": "duplicate assistant message merged",
                            "risk_level": risk_level,
                            "sync_status": final_status,
                            "turn_id": existing_turn_id or "",
                            "external_message_id": existing_external_id or "",
                        }

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
                    user_id, session_id, turn_id, external_message_id, role, content,
                    risk_level, sync_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.user_id,
                    req.session_id,
                    turn_id or None,
                    external_message_id or None,
                    req.role,
                    content,
                    risk_level,
                    sync_status,
                    now,
                    now,
                ),
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
        return {
            "success": True,
            "message": "session message saved",
            "risk_level": risk_level,
            "sync_status": sync_status,
            "turn_id": turn_id,
            "external_message_id": external_message_id,
        }

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
                SELECT role, content, risk_level, created_at,
                       turn_id, external_message_id, sync_status, updated_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (public_session_id,),
            )
            rows = cur.fetchall()

        messages = _coalesce_streaming_prefix_messages([
            {
                "role": row[0],
                "content": repair_mojibake_text(row[1]),
                "risk_level": row[2],
                "created_at": row[3],
                "turn_id": row[4] or "",
                "external_message_id": row[5] or "",
                "sync_status": row[6] or "complete",
                "updated_at": row[7] or row[3],
            }
            for row in rows
        ])
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
