import logging
import os
import time
import uuid
from datetime import datetime

from app.config import TASK_SCAN_INTERVAL_SECONDS
from app.db import db_lock, get_conn
from app.services.session_autofinalize import auto_finalize_session_with_dify
from app.services.sessions import insert_session_task_history
from app.utils import now_iso


logger = logging.getLogger(__name__)


def create_session_task_if_needed(cur, user_id: str, session_id: str, task_type: str):
    task_id = str(uuid.uuid4())
    now = now_iso()

    cur.execute(
        """
        SELECT task_id
        FROM session_task
        WHERE session_id = ? AND task_type = ?
        LIMIT 1
        """,
        (session_id, task_type),
    )
    existing = cur.fetchone()
    if existing:
        return None

    cur.execute(
        """
        INSERT INTO session_task (
            task_id, session_id, user_id, task_type, status,
            retry_count, max_retries, scheduled_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            session_id,
            user_id,
            task_type,
            "pending",
            0,
            3,
            now,
            now,
            now,
        ),
    )
    return task_id


def scan_expired_sessions_and_create_tasks(limit: int = 20):
    with db_lock:
        conn = get_conn()
        try:
            cur = conn.cursor()
            now = now_iso()

            today_start = datetime.combine(datetime.now().date(), datetime.min.time()).isoformat()
            cur.execute(
                """
                SELECT id, session_id, user_id
                FROM sessions
                WHERE status = 'open'
                  AND (
                    (auto_close_at IS NOT NULL AND auto_close_at <= ?)
                    OR started_at < ?
                  )
                ORDER BY auto_close_at ASC
                LIMIT ?
                """,
                (now, today_start, limit),
            )
            rows = cur.fetchall()

            created_tasks = 0
            for session_pk, public_session_id, user_id in rows:
                task_id = create_session_task_if_needed(
                    cur,
                    user_id,
                    public_session_id or session_pk,
                    "auto_end_session",
                )
                if task_id:
                    created_tasks += 1

            conn.commit()
            logger.info(
                "session_task_scan expired_sessions=%s created_tasks=%s",
                len(rows),
                created_tasks,
            )
            return {"expired_sessions": len(rows), "created_tasks": created_tasks}

        except Exception:
            conn.rollback()
            logger.exception("session_task_scan_failed")
            raise

        finally:
            conn.close()


def fetch_pending_tasks(limit: int = 5):
    with db_lock:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT task_id, user_id, session_id, task_type, retry_count, max_retries
                FROM session_task
                WHERE status = 'pending'
                  AND retry_count < max_retries
                ORDER BY scheduled_at ASC, created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()

            tasks = []
            now = now_iso()
            for row in rows:
                task_id, user_id, session_id, task_type, retry_count, max_retries = row
                cur.execute(
                    """
                    UPDATE session_task
                    SET status = 'running',
                        started_at = ?,
                        updated_at = ?
                    WHERE task_id = ? AND status = 'pending'
                    """,
                    (now, now, task_id),
                )
                if cur.rowcount == 1:
                    tasks.append(
                        {
                            "task_id": task_id,
                            "user_id": user_id,
                            "session_id": session_id,
                            "task_type": task_type,
                            "retry_count": retry_count,
                            "max_retries": max_retries,
                        }
                    )

            conn.commit()
            return tasks

        except Exception:
            conn.rollback()
            logger.exception("fetch_pending_tasks_failed")
            raise

        finally:
            conn.close()


def complete_task(cur, task: dict, result: str):
    now = now_iso()
    cur.execute(
        """
        UPDATE session_task
        SET status = 'success',
            last_error = NULL,
            finished_at = ?,
            updated_at = ?
        WHERE task_id = ?
        """,
        (now, now, task["task_id"]),
    )
    insert_session_task_history(
        cur,
        task["task_id"],
        task["user_id"],
        task["session_id"],
        task["task_type"],
        "success",
        result,
    )


def run_task(task: dict):
    if task["task_type"] == "auto_end_session":
        result = auto_finalize_session_with_dify(
            user_id=task["user_id"],
            session_id=task["session_id"],
            reason="auto_timeout_task",
            task_id=task["task_id"],
        )
        with db_lock:
            conn = get_conn()
            try:
                cur = conn.cursor()
                complete_task(
                    cur,
                    task,
                    f"auto_end_session completed handoff={result.get('handoff_document_id')}",
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        return

    with db_lock:
        conn = get_conn()
        try:
            cur = conn.cursor()
            complete_task(cur, task, "task type reserved for future worker")

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()


def mark_task_failed(task: dict, error: Exception):
    error_message = str(error)
    with db_lock:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT retry_count, max_retries
                FROM session_task
                WHERE task_id = ?
                """,
                (task["task_id"],),
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return

            retry_count, max_retries = row
            new_retry_count = retry_count + 1
            new_status = "failed" if new_retry_count >= max_retries else "pending"
            now = now_iso()
            cur.execute(
                """
                UPDATE session_task
                SET status = ?,
                    retry_count = ?,
                    last_error = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (new_status, new_retry_count, error_message, now, now, task["task_id"]),
            )
            insert_session_task_history(
                cur,
                task["task_id"],
                task["user_id"],
                task["session_id"],
                task["task_type"],
                new_status,
                "task failed",
                error_message,
            )
            conn.commit()

        except Exception:
            conn.rollback()
            logger.exception("mark_task_failed_failed task_id=%s", task["task_id"])
            raise

        finally:
            conn.close()


def run_session_task_once(scan_limit: int = 20, fetch_limit: int = 5):
    scan_result = scan_expired_sessions_and_create_tasks(limit=scan_limit)
    tasks = fetch_pending_tasks(limit=fetch_limit)
    results = []

    for task in tasks:
        try:
            run_task(task)
            results.append(
                {
                    "task_id": task["task_id"],
                    "session_id": task["session_id"],
                    "task_type": task["task_type"],
                    "status": "success",
                }
            )
        except Exception as exc:
            mark_task_failed(task, exc)
            results.append(
                {
                    "task_id": task["task_id"],
                    "session_id": task["session_id"],
                    "task_type": task["task_type"],
                    "status": "failed",
                    "error": "session_task_failed",
                }
            )

    return {"scan": scan_result, "claimed_tasks": len(tasks), "results": results}


def task_worker_loop():
    worker_id = f"worker-{os.getpid()}"
    logger.info("task_worker_started worker_id=%s interval_seconds=%s", worker_id, TASK_SCAN_INTERVAL_SECONDS)
    while True:
        time.sleep(max(TASK_SCAN_INTERVAL_SECONDS, 5))
        try:
            run_session_task_once(scan_limit=20, fetch_limit=5)
        except Exception as exc:
            logger.exception("task_worker_iteration_failed error=%s", exc)
