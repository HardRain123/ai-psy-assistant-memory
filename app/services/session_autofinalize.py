import logging
from datetime import datetime

from app.db import read_transaction, transaction
from app.services.dify_auto_finalize import DifyAutoFinalizeResult, request_dify_auto_finalize
from app.services.sessions import end_session_workflow


logger = logging.getLogger(__name__)


def _today_start_iso() -> str:
    today = datetime.now().date()
    return datetime.combine(today, datetime.min.time()).isoformat()


def _fetch_session_snapshot(user_id: str, session_id: str) -> dict | None:
    with read_transaction() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, started_at, ended_at, status,
                   final_saved_at, auto_close_at, summary, risk_level,
                   dify_conversation_id
            FROM sessions
            WHERE user_id = ? AND (id = ? OR session_id = ?)
            LIMIT 1
            """,
            (user_id, session_id, session_id),
        )
        row = cur.fetchone()
        if not row:
            return None

        public_session_id = row[1] or row[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM session_summaries
            WHERE user_id = ? AND session_id = ?
            """,
            (user_id, public_session_id),
        )
        summary_count = cur.fetchone()[0]

    return {
        "id": row[0],
        "session_id": public_session_id,
        "user_id": row[2],
        "started_at": row[3],
        "ended_at": row[4],
        "status": row[5],
        "final_saved_at": row[6],
        "auto_close_at": row[7],
        "summary": row[8],
        "risk_level": row[9],
        "dify_conversation_id": row[10] or "",
        "summary_count": summary_count,
    }


def find_stale_open_sessions(user_id: str, limit: int = 5) -> list[dict]:
    today_start = _today_start_iso()
    with read_transaction() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, started_at, dify_conversation_id
            FROM sessions
            WHERE user_id = ?
              AND status = 'open'
              AND final_saved_at IS NULL
              AND started_at < ?
            ORDER BY started_at ASC
            LIMIT ?
            """,
            (user_id, today_start, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "session_id": row[1] or row[0],
            "user_id": row[2],
            "started_at": row[3],
            "dify_conversation_id": row[4] or "",
        }
        for row in rows
    ]


def find_latest_auto_finalize_target(user_id: str) -> dict | None:
    today_start = _today_start_iso()
    with read_transaction() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, started_at, dify_conversation_id
            FROM sessions
            WHERE user_id = ?
              AND status = 'open'
              AND final_saved_at IS NULL
              AND started_at < ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id, today_start),
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                """
                SELECT id, session_id, user_id, started_at, dify_conversation_id
                FROM sessions
                WHERE user_id = ?
                  AND status = 'open'
                  AND final_saved_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()

    if not row:
        return None
    return {
        "id": row[0],
        "session_id": row[1] or row[0],
        "user_id": row[2],
        "started_at": row[3],
        "dify_conversation_id": row[4] or "",
    }


def auto_finalize_session_with_dify(
    *,
    user_id: str,
    session_id: str,
    reason: str,
    task_id: str | None = None,
    generate_handoff: bool = True,
) -> dict:
    before = _fetch_session_snapshot(user_id, session_id)
    if not before:
        raise RuntimeError("session not found")

    if before["final_saved_at"]:
        return {
            "session_id": before["session_id"],
            "user_id": before["user_id"],
            "already_finalized": True,
            "ended_at": before["ended_at"],
            "final_saved_at": before["final_saved_at"],
            "risk_level": before["risk_level"],
            "dify_auto_finalize": {
                "attempted": False,
                "success": False,
                "reason": "already_finalized",
            },
        }

    dify_result = DifyAutoFinalizeResult(attempted=False, success=False, reason="summary_already_exists")
    if not before["summary_count"]:
        dify_result = request_dify_auto_finalize(
            user_id=user_id,
            session_id=before["session_id"],
            conversation_id=before["dify_conversation_id"],
        )

    after_dify = _fetch_session_snapshot(user_id, before["session_id"])
    if after_dify and after_dify["final_saved_at"]:
        return {
            "session_id": after_dify["session_id"],
            "user_id": after_dify["user_id"],
            "already_finalized": True,
            "ended_at": after_dify["ended_at"],
            "final_saved_at": after_dify["final_saved_at"],
            "risk_level": after_dify["risk_level"],
            "dify_auto_finalize": dify_result.__dict__,
        }

    with transaction() as cur:
        result = end_session_workflow(
            cur,
            before["session_id"],
            user_id=user_id,
            reason=reason,
            task_id=task_id,
            generate_handoff=generate_handoff,
        )

    result["dify_auto_finalize"] = dify_result.__dict__
    logger.info(
        "session_auto_finalize_completed user_id=%s session_id=%s reason=%s dify_attempted=%s dify_success=%s",
        user_id,
        before["session_id"],
        reason,
        dify_result.attempted,
        dify_result.success,
    )
    return result


def auto_finalize_stale_sessions_for_user(user_id: str, reason: str, limit: int = 5) -> list[dict]:
    results = []
    for session in find_stale_open_sessions(user_id, limit=limit):
        results.append(
            auto_finalize_session_with_dify(
                user_id=user_id,
                session_id=session["session_id"],
                reason=reason,
            )
        )
    if results:
        logger.info("stale_sessions_auto_finalized user_id=%s count=%s", user_id, len(results))
    return results
