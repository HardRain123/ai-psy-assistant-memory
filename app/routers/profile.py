import logging

from fastapi import APIRouter

from app.db import transaction
from app.schemas import SaveUserProfileRequest
from app.services.longitudinal import merge_profile_memory
from app.services.sessions import ensure_user
from app.utils import clean_text, now_iso


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/profile")
def save_user_profile(req: SaveUserProfileRequest):
    content = clean_text(req.profile_memory)
    if not content:
        return {"success": False, "message": "empty profile_memory skipped"}

    now = now_iso()

    try:
        with transaction() as cur:
            ensure_user(cur, req.user_id)
            cur.execute(
                """
                SELECT profile_memory
                FROM user_profiles
                WHERE user_id = ?
                LIMIT 1
                """,
                (req.user_id,),
            )
            row = cur.fetchone()
            content_to_save = merge_profile_memory(row[0] if row else "", content)
            cur.execute(
                """
                INSERT INTO user_profiles (user_id, profile_memory, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_memory = excluded.profile_memory,
                    updated_at = excluded.updated_at
                """,
                (req.user_id, content_to_save, now, now),
            )

        logger.info("user_profile_saved user_id=%s", req.user_id)
        return {"success": True, "user_id": req.user_id, "message": "user profile saved"}

    except Exception as exc:
        logger.exception("save_user_profile_failed user_id=%s", req.user_id)
        return {"success": False, "error": "save_user_profile_failed", "message": str(exc)}


@router.get("/profile/{user_id}")
def get_user_profile(user_id: str):
    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT user_id, profile_memory, updated_at
                FROM user_profiles
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = cur.fetchone()

        if not row:
            return {
                "exists": False,
                "user_id": user_id,
                "profile_memory": "",
                "message": "profile not found",
            }

        return {"exists": True, "user_id": row[0], "profile_memory": row[1], "updated_at": row[2]}

    except Exception as exc:
        logger.exception("get_user_profile_failed user_id=%s", user_id)
        return {"success": False, "error": "get_user_profile_failed", "message": str(exc)}
