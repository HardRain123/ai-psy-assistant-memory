import logging
import uuid
from datetime import datetime, timedelta

from app.config import SESSION_MINUTES
from app.services.handoff import generate_handoff_document
from app.services.longitudinal import update_longitudinal_records_after_session
from app.services.quality import evaluate_session_quality, should_persist_memory
from app.utils import (
    bool_text,
    calc_stage,
    clean_text,
    detect_risk_level,
    highest_risk_level,
    now_iso,
    parse_dt,
    truncate_text,
)


logger = logging.getLogger(__name__)


ENDED_STATUSES = {"ended", "expired", "failed"}


def _today_bounds():
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    return (
        datetime.combine(today, datetime.min.time()).isoformat(),
        datetime.combine(tomorrow, datetime.min.time()).isoformat(),
    )


def ensure_user(cur, user_id: str):
    now = now_iso()
    cur.execute(
        """
        INSERT INTO users (user_id, created_at, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET updated_at = ?
        """,
        (user_id, now, now, now),
    )


def has_session_today(cur, user_id: str) -> bool:
    day_start, day_end = _today_bounds()
    cur.execute(
        """
        SELECT id
        FROM sessions
        WHERE user_id = ?
          AND (
            (started_at >= ? AND started_at < ?)
            OR (ended_at >= ? AND ended_at < ?)
          )
        LIMIT 1
        """,
        (user_id, day_start, day_end, day_start, day_end),
    )
    return cur.fetchone() is not None


def get_latest_session(cur, user_id: str):
    cur.execute(
        """
        SELECT id, session_id, user_id, started_at, ended_at, status,
               final_saved_at, auto_close_at, stage, summary, risk_level,
               is_low_content, summary_type, user_message_count, user_char_count
        FROM sessions
        WHERE user_id = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    return cur.fetchone()


def create_session(cur, user_id: str):
    ensure_user(cur, user_id)
    session_id = str(uuid.uuid4())
    started_at = datetime.now()
    started_at_str = started_at.isoformat()
    auto_close_at_str = (started_at + timedelta(minutes=SESSION_MINUTES)).isoformat()
    now = started_at_str
    stage = "trust"

    cur.execute(
        """
        INSERT INTO sessions (
            id, session_id, user_id, started_at, ended_at, status,
            auto_close_at, stage, risk_level, is_low_content, summary_type,
            user_message_count, user_char_count, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            session_id,
            user_id,
            started_at_str,
            None,
            "open",
            auto_close_at_str,
            stage,
            "none",
            0,
            "formal",
            0,
            0,
            now,
            now,
        ),
    )

    elapsed, remaining, current_stage = calc_stage(started_at)
    logger.info("session_created user_id=%s session_id=%s", user_id, session_id)

    return {
        "session_id": session_id,
        "status": "open",
        "started_at": started_at_str,
        "ended_at": None,
        "elapsed_minutes": elapsed,
        "remaining_minutes": remaining,
        "stage": current_stage,
        "session_stage": current_stage,
        "is_new_session": True,
        "is_new_session_str": bool_text(True),
        "can_continue": True,
        "can_start_new_session": False,
        "daily_limit_reached": False,
        "message": "可以开始今天的新咨询。",
        "final_saved": False,
        "risk_level": "none",
    }


def _fetch_session_for_update(cur, session_id: str, user_id: str | None = None):
    if user_id:
        cur.execute(
            """
            SELECT id, session_id, user_id, started_at, ended_at, status,
                   final_saved_at, auto_close_at, summary, risk_level,
                   is_low_content, summary_type, user_message_count, user_char_count
            FROM sessions
            WHERE (id = ? OR session_id = ?) AND user_id = ?
            LIMIT 1
            """,
            (session_id, session_id, user_id),
        )
    else:
        cur.execute(
            """
            SELECT id, session_id, user_id, started_at, ended_at, status,
                   final_saved_at, auto_close_at, summary, risk_level,
                   is_low_content, summary_type, user_message_count, user_char_count
            FROM sessions
            WHERE id = ? OR session_id = ?
            LIMIT 1
            """,
            (session_id, session_id),
        )
    return cur.fetchone()


def _fetch_messages(cur, session_id: str):
    cur.execute(
        """
        SELECT role, content, risk_level, created_at
        FROM session_messages
        WHERE session_id = ?
        ORDER BY id ASC
        LIMIT 80
        """,
        (session_id,),
    )
    return cur.fetchall()


def _fetch_existing_summary(cur, session_id: str):
    cur.execute(
        """
        SELECT summary, core_topics, next_focus, risk_level
        FROM session_summaries
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    )
    return cur.fetchone()


def _build_summary(messages: list, existing_summary: str | None) -> tuple[str, str, str]:
    if existing_summary:
        return clean_text(existing_summary), "", ""

    user_messages = [clean_text(row[1]) for row in messages if row[0] == "user" and row[1]]
    if not user_messages:
        return "本次咨询已结束，暂无足够对话内容生成详细总结。", "暂无明确主题", "下次先确认用户当前状态。"

    first = truncate_text(user_messages[0], 180)
    last = truncate_text(user_messages[-1], 180)
    summary = f"本次咨询中，用户主要表达为：{first}"
    if last and last != first:
        summary += f" 后续补充或变化为：{last}"
    return summary, first, "下次继续确认该困扰的触发情境、情绪变化和可执行的小行动。"


def _insert_summary_if_needed(
    cur,
    user_id: str,
    session_id: str,
    summary: str,
    core_topics: str,
    next_focus: str,
    risk_level: str,
):
    existing = _fetch_existing_summary(cur, session_id)
    if existing:
        return False

    now = now_iso()
    cur.execute(
        """
        INSERT INTO session_summaries (
            user_id, session_id, summary, core_topics, next_focus,
            risk_level, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, session_id, summary, core_topics, next_focus, risk_level, now, now),
    )
    return True


def _insert_memory_if_needed(
    cur,
    user_id: str,
    session_id: str,
    content: str,
    memory_type: str,
    importance: int,
):
    content = clean_text(content)
    allowed, _reason = should_persist_memory(content)
    if not allowed or content == "本次咨询已结束，暂无足够对话内容生成详细总结。":
        return False

    cur.execute(
        """
        SELECT id
        FROM memories
        WHERE user_id = ? AND session_id = ? AND content = ?
        LIMIT 1
        """,
        (user_id, session_id, content),
    )
    if cur.fetchone():
        return False

    now = now_iso()
    cur.execute(
        """
        INSERT INTO memories (
            user_id, session_id, content, memory_type, importance,
            source_type, evidence, confidence, is_hypothesis, should_persist,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            session_id,
            content,
            memory_type,
            importance,
            "auto_session_finalize",
            "derived from saved session summary",
            "medium",
            0,
            1,
            now,
            now,
        ),
    )
    return True


def insert_session_task_history(
    cur,
    task_id: str,
    user_id: str,
    session_id: str,
    task_type: str,
    status: str,
    result: str | None = None,
    error_message: str | None = None,
):
    cur.execute(
        """
        INSERT INTO session_task_history (
            task_id, user_id, session_id, task_type, status,
            result, message, error_message, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            user_id,
            session_id,
            task_type,
            status,
            result,
            result,
            error_message,
            now_iso(),
        ),
    )


def end_session_workflow(
    cur,
    session_id: str,
    user_id: str | None = None,
    reason: str = "auto_timeout",
    task_id: str | None = None,
    generate_handoff: bool = True,
) -> dict:
    row = _fetch_session_for_update(cur, session_id, user_id)
    if not row:
        raise RuntimeError("session not found")

    (
        session_pk,
        public_session_id,
        session_user_id,
        started_at,
        ended_at,
        status,
        final_saved_at,
        auto_close_at,
        stored_summary,
        stored_risk_level,
        stored_is_low_content,
        stored_summary_type,
        stored_user_message_count,
        stored_user_char_count,
    ) = row
    public_session_id = public_session_id or session_pk
    task_id = task_id or f"inline-{uuid.uuid4()}"

    if final_saved_at:
        handoff = None
        if generate_handoff:
            handoff = generate_handoff_document(cur, public_session_id, "markdown", regenerate=False)
        insert_session_task_history(
            cur,
            task_id,
            session_user_id,
            public_session_id,
            "auto_end_session",
            "success",
            "session already finalized",
        )
        return {
            "session_id": public_session_id,
            "user_id": session_user_id,
            "already_finalized": True,
            "ended_at": ended_at,
            "final_saved_at": final_saved_at,
            "handoff_document_id": handoff.get("document_id") if handoff else None,
        }

    messages = _fetch_messages(cur, public_session_id)
    quality = evaluate_session_quality(messages)
    existing_summary = _fetch_existing_summary(cur, public_session_id)
    existing_summary_text = existing_summary[0] if existing_summary else stored_summary
    message_risk = detect_risk_level("\n".join([row[1] for row in messages if row[1]]))
    summary_risk = existing_summary[3] if existing_summary else "none"
    row_risk = highest_risk_level(*[row[2] for row in messages])
    risk_level = highest_risk_level(stored_risk_level, summary_risk, row_risk, message_risk)

    now = now_iso()
    fallback_ended_at = (parse_dt(started_at) + timedelta(minutes=SESSION_MINUTES)).isoformat()
    scheduled_close_reasons = {
        "auto_timeout",
        "auto_timeout_task",
        "auto_timeout_status_check",
        "auto_previous_day_status_check",
    }
    if ended_at:
        ended_at_value = ended_at
    elif reason in scheduled_close_reasons:
        ended_at_value = auto_close_at or fallback_ended_at
    else:
        ended_at_value = now
    close_status = "ended"
    summary_type = "low_content" if quality.is_low_content else "formal"
    if quality.is_low_content:
        summary = "本次会话内容不足，未生成正式咨询总结。"
        core_topics = ""
        next_focus = ""
        summary_inserted = False
        memory_saved = False
    else:
        summary, core_topics, next_focus = _build_summary(messages, existing_summary_text)
        if existing_summary:
            core_topics = core_topics or clean_text(existing_summary[1] or "")
            next_focus = next_focus or clean_text(existing_summary[2] or "")
        summary_inserted = _insert_summary_if_needed(
            cur,
            session_user_id,
            public_session_id,
            summary,
            core_topics,
            next_focus,
            risk_level,
        )
        memory_saved = _insert_memory_if_needed(
            cur,
            session_user_id,
            public_session_id,
            truncate_text(summary, 500),
            "risk_note" if risk_level == "high" else "therapy_goal",
            3 if risk_level == "high" else 2,
        )

    longitudinal_updates = {"events": [], "care_plan_updated": False, "profile_updated": False}
    if not quality.is_low_content:
        longitudinal_updates = update_longitudinal_records_after_session(
            cur,
            user_id=session_user_id,
            session_id=public_session_id,
            messages=messages,
            summary=summary,
            core_topics=core_topics,
            next_focus=next_focus,
        )

    cur.execute(
        """
        UPDATE sessions
        SET status = ?,
            ended_at = ?,
            final_saved_at = ?,
            close_reason = ?,
            timeout_checked_at = ?,
            stage = 'ended',
            summary = ?,
            is_low_content = ?,
            summary_type = ?,
            user_message_count = ?,
            user_char_count = ?,
            risk_level = ?,
            updated_at = ?
        WHERE id = ? AND final_saved_at IS NULL
        """,
        (
            close_status,
            ended_at_value,
            now,
            reason,
            now,
            summary,
            1 if quality.is_low_content else 0,
            summary_type,
            quality.user_message_count,
            quality.user_char_count,
            risk_level,
            now,
            session_pk,
        ),
    )

    handoff = None
    if generate_handoff and not quality.is_low_content:
        handoff = generate_handoff_document(cur, public_session_id, "markdown", regenerate=False)

    history_result = (
        f"low_content_skipped reason={quality.reason}; summary_skipped=True; memory_skipped=True"
        if quality.is_low_content
        else "session finalized; summary/memory/handoff processed"
    )
    insert_session_task_history(
        cur,
        task_id,
        session_user_id,
        public_session_id,
        "auto_end_session",
        "success",
        history_result,
    )
    logger.info(
        "session_auto_ended user_id=%s session_id=%s reason=%s risk_level=%s",
        session_user_id,
        public_session_id,
        reason,
        risk_level,
    )

    return {
        "session_id": public_session_id,
        "user_id": session_user_id,
        "already_finalized": False,
        "ended_at": ended_at_value,
        "final_saved_at": now,
        "summary": summary,
        "summary_inserted": summary_inserted,
        "longitudinal_events": longitudinal_updates["events"],
        "care_plan_updated": longitudinal_updates["care_plan_updated"],
        "profile_updated": longitudinal_updates["profile_updated"],
        "is_low_content": quality.is_low_content,
        "summary_type": summary_type,
        "user_message_count": quality.user_message_count,
        "user_char_count": quality.user_char_count,
        "risk_level": risk_level,
        "memory_saved": memory_saved,
        "handoff_document_id": handoff.get("document_id") if handoff else None,
    }


def active_status_response(row) -> dict:
    (
        session_pk,
        public_session_id,
        user_id,
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
    ) = row
    elapsed, remaining, current_stage = calc_stage(parse_dt(started_at_str))
    return {
        "session_id": public_session_id or session_pk,
        "status": status,
        "started_at": started_at_str,
        "ended_at": ended_at_str,
        "elapsed_minutes": elapsed,
        "remaining_minutes": remaining,
        "stage": current_stage,
        "session_stage": current_stage,
        "is_new_session": False,
        "is_new_session_str": bool_text(False),
        "can_continue": True,
        "can_start_new_session": False,
        "daily_limit_reached": False,
        "message": "session active",
        "final_saved": bool(final_saved_at),
        "risk_level": risk_level or "none",
        "is_low_content": bool(is_low_content),
        "summary_type": summary_type or "formal",
        "user_message_count": user_message_count or 0,
        "user_char_count": user_char_count or 0,
    }


def ended_status_response(
    session_id: str,
    started_at: str,
    ended_at: str | None,
    final_saved_at: str | None,
    risk_level: str = "none",
    message: str = "今天的正式咨询已经结束，明天可以开始下一次咨询。",
    elapsed_minutes: float | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "status": "ended",
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_minutes": elapsed_minutes if elapsed_minutes is not None else SESSION_MINUTES,
        "remaining_minutes": 0,
        "stage": "ended",
        "session_stage": "ended",
        "is_new_session": False,
        "is_new_session_str": bool_text(False),
        "can_continue": False,
        "can_start_new_session": False,
        "daily_limit_reached": True,
        "message": message,
        "final_saved": bool(final_saved_at),
        "risk_level": risk_level or "none",
    }
