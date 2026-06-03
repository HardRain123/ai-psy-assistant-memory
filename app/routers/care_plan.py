import logging

from fastapi import APIRouter

from app.db import transaction
from app.schemas import SaveCarePlanRequest
from app.services.longitudinal import merge_care_plan
from app.services.sessions import ensure_user
from app.utils import clean_text, now_iso


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/care-plan/{user_id}")
def get_care_plan(user_id: str):
    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT plan_text, updated_at
                FROM care_plans
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = cur.fetchone()

        if not row:
            return {
                "exists": False,
                "user_id": user_id,
                "plan_text": "暂无咨询计划表。",
                "updated_at": None,
            }

        return {"exists": True, "user_id": user_id, "plan_text": row[0], "updated_at": row[1]}

    except Exception as exc:
        logger.exception("get_care_plan_failed user_id=%s", user_id)
        return {"success": False, "error": "get_care_plan_failed", "message": str(exc)}


@router.post("/care-plan")
def save_care_plan(req: SaveCarePlanRequest):
    content = clean_text(req.plan_text)
    if not content:
        return {"success": False, "message": "empty care plan skipped"}

    now = now_iso()

    try:
        with transaction() as cur:
            ensure_user(cur, req.user_id)
            cur.execute(
                """
                SELECT plan_text
                FROM care_plans
                WHERE user_id = ?
                LIMIT 1
                """,
                (req.user_id,),
            )
            row = cur.fetchone()
            content_to_save = merge_care_plan(row[0] if row else "", content)
            cur.execute(
                """
                INSERT INTO care_plans (user_id, plan_text, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    plan_text = excluded.plan_text,
                    updated_at = excluded.updated_at
                """,
                (req.user_id, content_to_save, now, now),
            )

        logger.info("care_plan_saved user_id=%s", req.user_id)
        return {"success": True, "user_id": req.user_id, "message": "care plan saved"}

    except Exception as exc:
        logger.exception("save_care_plan_failed user_id=%s", req.user_id)
        return {"success": False, "error": "save_care_plan_failed", "message": str(exc)}
