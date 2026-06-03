import logging

from fastapi import APIRouter

from app.db import transaction
from app.schemas import SaveMemoryRequest
from app.services.quality import should_persist_memory
from app.utils import clean_text, now_iso


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/memory/{user_id}")
def get_memory(user_id: str):
    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT content, created_at, session_id, memory_type, importance,
                       source_type, evidence, confidence, is_hypothesis, should_persist
                FROM memories
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 10
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        memories = [
            {
                "content": row[0],
                "created_at": row[1],
                "session_id": row[2] or "",
                "memory_type": row[3] or "general",
                "importance": row[4] or 1,
                "source_type": row[5] or "manual",
                "evidence": row[6] or "",
                "confidence": row[7] or "medium",
                "is_hypothesis": bool(row[8]),
                "should_persist": bool(row[9]),
            }
            for row in rows
        ]
        return {"user_id": user_id, "memories": memories}

    except Exception as exc:
        logger.exception("get_memory_failed user_id=%s", user_id)
        return {"success": False, "error": "get_memory_failed", "message": str(exc)}


@router.post("/memory")
def save_memory(req: SaveMemoryRequest):
    content = clean_text(req.memory)
    if not content:
        return {"success": False, "message": "empty memory skipped"}

    allowed, reason = should_persist_memory(content)
    if not allowed or not req.should_persist:
        return {
            "success": False,
            "skipped": True,
            "reason": reason if allowed else reason,
            "message": "memory skipped by quality rules",
        }

    session_id = req.session_id or ""
    memory_type = req.memory_type or "general"
    importance = max(min(req.importance, 5), 1)

    try:
        with transaction() as cur:
            cur.execute(
                """
                SELECT id
                FROM memories
                WHERE user_id = ? AND session_id = ? AND content = ?
                LIMIT 1
                """,
                (req.user_id, session_id, content),
            )
            if cur.fetchone():
                return {"success": True, "already_exists": True, "message": "memory already saved"}

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
                    req.user_id,
                    session_id,
                    content,
                    memory_type,
                    importance,
                    req.source_type or "manual",
                    req.evidence or "",
                    req.confidence or "medium",
                    1 if req.is_hypothesis else 0,
                    1 if req.should_persist else 0,
                    now,
                    now,
                ),
            )

        logger.info("memory_saved user_id=%s session_id=%s memory_type=%s", req.user_id, session_id, memory_type)
        return {"success": True, "message": "memory saved"}

    except Exception as exc:
        logger.exception("save_memory_failed user_id=%s", req.user_id)
        return {"success": False, "error": "save_memory_failed", "message": str(exc)}
