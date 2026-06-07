import logging

from fastapi import APIRouter

from app.db import read_transaction
from app.errors import public_error
from app.services.screening import format_snapshot_for_context, get_current_snapshot


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/context/{user_id}")
def get_context(user_id: str):
    try:
        with read_transaction() as cur:
            cur.execute(
                """
                SELECT profile_memory, updated_at
                FROM user_profiles
                WHERE user_id = ?
                """,
                (user_id,),
            )
            profile_row = cur.fetchone()

            if profile_row:
                profile_memory = profile_row[0]
                profile_updated_at = profile_row[1]
            else:
                profile_memory = "暂无长期画像。"
                profile_updated_at = None

            cur.execute(
                """
                SELECT summary, core_topics, next_focus, created_at, risk_level
                FROM session_summaries
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 3
                """,
                (user_id,),
            )
            session_rows = cur.fetchall()

            session_summaries = []
            for row in session_rows:
                summary, core_topics, next_focus, created_at, risk_level = row
                session_summaries.append(
                    {
                        "summary": summary,
                        "core_topics": core_topics or "",
                        "next_focus": next_focus or "",
                        "risk_level": risk_level or "none",
                        "created_at": created_at,
                    }
                )

            cur.execute(
                """
                SELECT content, created_at, memory_type, importance
                FROM memories
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 10
                """,
                (user_id,),
            )
            memory_rows = cur.fetchall()

            recent_memory_items = [
                {
                    "content": row[0],
                    "created_at": row[1],
                    "memory_type": row[2] or "general",
                    "importance": row[3] or 1,
                }
                for row in memory_rows
                if row[0] and row[0].strip()
            ]

            screening_snapshot = get_current_snapshot(cur, user_id)

        if session_summaries:
            recent_session_summaries = "\n".join(
                [
                    f"- 咨询总结：{item['summary']}"
                    + (f"\n  核心主题：{item['core_topics']}" if item["core_topics"] else "")
                    + (f"\n  下次重点：{item['next_focus']}" if item["next_focus"] else "")
                    + (f"\n  风险等级：{item['risk_level']}" if item["risk_level"] != "none" else "")
                    for item in session_summaries
                    if item["summary"] and item["summary"].strip()
                ]
            )
        else:
            recent_session_summaries = "暂无咨询总结。"

        if recent_memory_items:
            recent_memories = "\n".join(
                [f"- [{item['memory_type']}] {item['content']}" for item in recent_memory_items]
            )
        else:
            recent_memories = "暂无近期细节记忆。"

        screening_context = format_snapshot_for_context(screening_snapshot)

        context_text = f"""
【长期画像】
{profile_memory}

【最近状态筛查】
{screening_context}

【最近咨询总结】
{recent_session_summaries}

【近期细节记忆】
{recent_memories}
""".strip()

        return {
            "user_id": user_id,
            "profile_memory": profile_memory,
            "profile_updated_at": profile_updated_at,
            "recent_screening": screening_context,
            "recent_session_summaries": recent_session_summaries,
            "recent_memories": recent_memories,
            "context_text": context_text,
            "raw": {
                "mental_state_snapshot": screening_snapshot,
                "session_summaries": session_summaries,
                "recent_memory_items": recent_memory_items,
            },
        }

    except Exception:
        logger.exception("get_context_failed user_id=%s", user_id)
        return public_error("get_context_failed")
