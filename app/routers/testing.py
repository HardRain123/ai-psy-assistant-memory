from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.config import is_testing_mode
from app.db import transaction
from app.schemas import E2ETimeShiftRequest


router = APIRouter()

TEST_USER_PREFIX = "codex-e2e-test-user"


@router.delete("/test/e2e-data/{user_id}")
def delete_e2e_user_data(user_id: str):
    if not is_testing_mode():
        raise HTTPException(status_code=403, detail="test cleanup is disabled")

    if not user_id.startswith(TEST_USER_PREFIX):
        raise HTTPException(status_code=400, detail="only codex e2e test users can be cleaned")

    tables = [
        "session_messages",
        "session_summaries",
        "memories",
        "handoff_documents",
        "session_task",
        "session_task_history",
        "sessions",
        "user_profiles",
        "care_plans",
        "users",
    ]

    deleted = {}
    with transaction() as cur:
        for table in tables:
            cur.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            deleted[table] = max(cur.rowcount, 0)

    return {
        "success": True,
        "user_id": user_id,
        "deleted": deleted,
    }


@router.post("/test/e2e-time-shift/{user_id}")
def shift_latest_e2e_session_time(user_id: str, req: E2ETimeShiftRequest):
    if not is_testing_mode():
        raise HTTPException(status_code=403, detail="test time shift is disabled")

    if not user_id.startswith(TEST_USER_PREFIX):
        raise HTTPException(status_code=400, detail="only codex e2e test users can be shifted")

    days = max(min(req.days, 30), 1)

    with transaction() as cur:
        cur.execute(
            """
            SELECT id, session_id, started_at, ended_at, final_saved_at, auto_close_at
            FROM sessions
            WHERE user_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="session not found")

        session_pk, public_session_id, started_at, ended_at, final_saved_at, auto_close_at = row
        shifted = {
            "started_at": _shift_iso(started_at, days),
            "ended_at": _shift_iso(ended_at, days),
            "final_saved_at": _shift_iso(final_saved_at, days),
            "auto_close_at": _shift_iso(auto_close_at, days),
        }
        now = datetime.now().isoformat()

        cur.execute(
            """
            UPDATE sessions
            SET started_at = ?,
                ended_at = ?,
                final_saved_at = ?,
                auto_close_at = ?,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                shifted["started_at"],
                shifted["ended_at"],
                shifted["final_saved_at"],
                shifted["auto_close_at"],
                now,
                session_pk,
                user_id,
            ),
        )

    return {
        "success": True,
        "user_id": user_id,
        "session_id": public_session_id or session_pk,
        "days": days,
        "shifted": shifted,
    }


def _shift_iso(value: str | None, days: int) -> str | None:
    if not value:
        return None
    return (datetime.fromisoformat(value) - timedelta(days=days)).isoformat()
