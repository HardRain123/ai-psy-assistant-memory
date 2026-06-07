import logging
from datetime import datetime, timedelta

from fastapi import APIRouter

from app.config import SESSION_MINUTES
from app.db import transaction
from app.errors import json_error, public_error
from app.services.session_tasks import (
    run_session_task_once,
    scan_expired_sessions_and_create_tasks,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/debug/session-tasks/scan")
def debug_scan_session_tasks():
    try:
        return scan_expired_sessions_and_create_tasks(limit=50)
    except Exception:
        logger.exception("debug_scan_session_tasks_failed")
        return json_error(500, "debug_operation_failed")


@router.get("/debug/session-tasks/{user_id}")
def debug_get_session_tasks(user_id: str):
    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT task_id, session_id, task_type, status, retry_count,
                       max_retries, last_error, scheduled_at, started_at,
                       finished_at, created_at, updated_at
                FROM session_task
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        tasks = [
            {
                "task_id": row[0],
                "session_id": row[1],
                "task_type": row[2],
                "status": row[3],
                "retry_count": row[4],
                "max_retries": row[5],
                "last_error": row[6],
                "scheduled_at": row[7],
                "started_at": row[8],
                "finished_at": row[9],
                "created_at": row[10],
                "updated_at": row[11],
            }
            for row in rows
        ]
        return {"user_id": user_id, "tasks": tasks}

    except Exception:
        logger.exception("debug_get_session_tasks_failed user_id=%s", user_id)
        return json_error(500, "debug_operation_failed")


@router.post("/debug/session-tasks/run-once")
def debug_run_session_tasks_once():
    try:
        return run_session_task_once(scan_limit=50, fetch_limit=10)
    except Exception:
        logger.exception("debug_run_session_tasks_once_failed")
        return json_error(500, "debug_operation_failed")


@router.get("/session/deleted/{user_id}")
def delete_session(user_id: str):
    try:
        with transaction() as cur:
            for table in [
                "session_messages",
                "session_summaries",
                "memories",
                "handoff_documents",
                "session_task",
                "session_task_history",
                "sessions",
            ]:
                cur.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))

        return {"success": True, "message": f"Deleted all session data for user {user_id}"}

    except Exception:
        logger.exception("debug_delete_session_failed user_id=%s", user_id)
        return public_error("debug_operation_failed")


@router.delete("/session-messages/{session_id}")
def delete_session_messages(session_id: str):
    try:
        with transaction() as cur:
            cur.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
        return {"success": True, "message": f"Deleted all messages for session {session_id}"}

    except Exception:
        logger.exception("debug_delete_session_messages_failed session_id=%s", session_id)
        return public_error("debug_operation_failed")


@router.post("/debug/session/mark-latest-ended-yesterday/{user_id}")
def mark_latest_session_ended_yesterday(user_id: str):
    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT id, session_id, started_at, ended_at, status
                FROM sessions
                WHERE user_id = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"success": False, "message": "没有找到该用户的 session。"}

            session_pk, public_session_id, old_started_at, old_ended_at, old_status = row
            yesterday = datetime.now() - timedelta(days=1)
            new_started_at = yesterday.replace(hour=10, minute=0, second=0, microsecond=0)
            new_ended_at = new_started_at + timedelta(minutes=SESSION_MINUTES)

            cur.execute(
                """
                UPDATE sessions
                SET started_at = ?,
                    ended_at = ?,
                    status = 'ended',
                    final_saved_at = ?,
                    auto_close_at = ?,
                    stage = 'ended',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_started_at.isoformat(),
                    new_ended_at.isoformat(),
                    new_ended_at.isoformat(),
                    new_ended_at.isoformat(),
                    datetime.now().isoformat(),
                    session_pk,
                ),
            )

        return {
            "success": True,
            "user_id": user_id,
            "session_id": public_session_id or session_pk,
            "old": {
                "started_at": old_started_at,
                "ended_at": old_ended_at,
                "status": old_status,
            },
            "new": {
                "started_at": new_started_at.isoformat(),
                "ended_at": new_ended_at.isoformat(),
                "status": "ended",
            },
            "message": "最近一次 session 已标记为昨天结束。",
        }

    except Exception:
        logger.exception("debug_mark_latest_session_ended_yesterday_failed user_id=%s", user_id)
        return public_error("debug_operation_failed")
