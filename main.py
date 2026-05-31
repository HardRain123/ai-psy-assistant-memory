from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
from datetime import datetime, timedelta
import uuid
from typing import Optional


app = FastAPI()

DB = "data.db"
SESSION_MINUTES = 50


# ======================
# 数据库初始化
# ======================
class SaveSessionMessageRequest(BaseModel):
    user_id: str
    session_id: str
    role: str
    content: str


class SaveUserProfileRequest(BaseModel):
    user_id: str
    profile_memory: str


class SaveCarePlanRequest(BaseModel):
    user_id: str
    plan_text: str


class SaveSessionSummaryRequest(BaseModel):
    user_id: str
    session_id: str
    summary: str
    core_topics: str = ""
    next_focus: str = ""


class FinalizeSessionRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # 长期记忆表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # 咨询 session 表
    # status: open / ended
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        final_saved_at TEXT,
        status TEXT NOT NULL DEFAULT 'open'
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS session_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        summary TEXT NOT NULL,
        core_topics TEXT,
        next_focus TEXT,
        created_at TEXT NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        profile_memory TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS session_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS care_plans (
        user_id TEXT PRIMARY KEY,
        plan_text TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


init_db()


# ======================
# Pydantic Model
# ======================


class SaveMemoryRequest(BaseModel):
    user_id: str
    memory: str


# ======================
# 工具函数
# ======================


def calc_stage(started_at: datetime):
    """
    根据 started_at 计算当前咨询阶段。
    0-5分钟：opening
    5-40分钟：exploring
    40-48分钟：closing
    48-50分钟：ending
    50分钟后：ended
    """
    now = datetime.now()
    elapsed = (now - started_at).total_seconds() / 60
    remaining = SESSION_MINUTES - elapsed

    if elapsed < 5:
        stage = "opening"
    elif elapsed < 48:
        stage = "exploring"
    elif elapsed < 50:
        stage = "closing"
    else:
        stage = "ended"

    return round(elapsed, 2), round(max(remaining, 0), 2), stage


def has_session_today(cur, user_id: str) -> bool:
    today = datetime.now().date().isoformat()

    cur.execute(
        """
        SELECT id
        FROM sessions
        WHERE user_id = ?
          AND (
            DATE(started_at) = ?
            OR DATE(ended_at) = ?
          )
        LIMIT 1
        """,
        (user_id, today, today),
    )

    return cur.fetchone() is not None


def create_session(cur, user_id: str):
    """
    创建一次新的咨询 session。
    注意：这里只负责创建，不负责 conn.commit()
    """
    session_id = str(uuid.uuid4())
    started_at = datetime.now()
    started_at_str = started_at.isoformat()

    cur.execute(
        """
        INSERT INTO sessions (id, user_id, started_at, ended_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, user_id, started_at_str, None, "open"),
    )

    elapsed, remaining, stage = calc_stage(started_at)

    return {
        "session_id": session_id,
        "started_at": started_at_str,
        "ended_at": None,
        "status": "open",
        "elapsed_minutes": elapsed,
        "remaining_minutes": remaining,
        "stage": stage,
        "is_new_session": True,
        "is_new_session_str": bool_text(True),
        "can_continue": True,
        "can_start_new_session": False,
        "daily_limit_reached": False,
        "message": "new session created",
        "final_saved": False,
    }


# ======================
# 健康检查
# ======================


@app.get("/health")
def health():
    return {"status": "ok"}


# ======================
# 长期记忆接口
# ======================


@app.get("/memory/{user_id}")
def get_memory(user_id: str):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT content, created_at
        FROM memories
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (user_id,),
    )

    rows = cur.fetchall()
    conn.close()

    memories = [{"content": row[0], "created_at": row[1]} for row in rows]

    return {"user_id": user_id, "memories": memories}


@app.post("/memory")
def save_memory(req: SaveMemoryRequest):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO memories (user_id, content, created_at)
        VALUES (?, ?, ?)
        """,
        (req.user_id, req.memory, datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()

    return {"success": True, "message": "memory saved"}


# ======================
# 咨询 Session 状态接口
# ======================


@app.get("/session/status/{user_id}")
def session_status(user_id: str):
    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, started_at, ended_at, status,final_saved_at
            FROM sessions
            WHERE user_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()

        if not row:
            result = create_session(cur, user_id)
            conn.commit()
            return {
                **result,
                "message": "可以开始今天的新咨询。",
            }

        session_id, started_at_str, ended_at_str, status, final_saved_at = row
        final_saved = bool(final_saved_at)
        # 最近 session 已结束
        if status == "ended":
            today = datetime.now().date()

            started_today = datetime.fromisoformat(started_at_str).date() == today

            ended_today = False
            if ended_at_str:
                ended_today = datetime.fromisoformat(ended_at_str).date() == today

            is_today = started_today or ended_today

            # 今天已经结束，不能再开
            if is_today:
                return {
                    "session_id": session_id,
                    "started_at": started_at_str,
                    "ended_at": ended_at_str,
                    "status": "ended",
                    "stage": "ended",
                    "session_stage": "ended",
                    "elapsed_minutes": SESSION_MINUTES,
                    "remaining_minutes": 0,
                    "is_new_session": False,
                    "is_new_session_str": bool_text(False),
                    "can_continue": False,
                    "can_start_new_session": False,
                    "daily_limit_reached": True,
                    "message": "今天的正式咨询已经结束，明天可以开始下一次咨询。",
                    "final_saved": final_saved,
                }

            result = create_session(cur, user_id)
            conn.commit()
            return {
                **result,
                "message": "可以开始今天的新咨询。",
            }

        # 最近 session 是 open：计算时间
        started_at = datetime.fromisoformat(started_at_str)
        elapsed, remaining, stage = calc_stage(started_at)

        # 超过 50 分钟，自动结束，但不创建新的
        if stage == "ended":
            ended_at = datetime.now().isoformat()

            cur.execute(
                """
                UPDATE sessions
                SET status = ?, ended_at = ?
                WHERE id = ?
                """,
                ("ended", ended_at, session_id),
            )
            conn.commit()

            return {
                "session_id": session_id,
                "started_at": started_at_str,
                "ended_at": ended_at,
                "status": "ended",
                "stage": "ended",
                "session_stage": "ended",
                "elapsed_minutes": elapsed,
                "remaining_minutes": 0,
                "is_new_session": False,
                "is_new_session_str": bool_text(False),
                "can_continue": False,
                "can_start_new_session": False,
                "daily_limit_reached": True,
                "final_saved": final_saved,
                "message": "本次 50 分钟咨询已经结束，明天可以开始下一次咨询。",
            }

        # 未超时，继续
        return {
            "session_id": session_id,
            "started_at": started_at_str,
            "ended_at": ended_at_str,
            "status": "open",
            "stage": stage,
            "session_stage": stage,
            "elapsed_minutes": elapsed,
            "remaining_minutes": remaining,
            "is_new_session": False,
            "is_new_session_str": bool_text(False),
            "can_continue": True,
            "can_start_new_session": False,
            "final_saved": final_saved,
            "daily_limit_reached": False,
            "message": "session active",
        }

    except Exception as e:
        return {"error": str(e)}

    finally:
        if conn:
            conn.close()


# ======================
# 开始新咨询接口
# ======================


@app.post("/session/start/{user_id}")
def start_session(user_id: str):
    """
    用户明确点击/表达“开始新的咨询”时调用。

    规则：
    1. 今天已经有过 session：不允许再开
    2. 今天没有 session：创建新的 open session
    """
    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        # 今天已经有过咨询，不允许再开
        if has_session_today(cur, user_id):
            return {
                "success": False,
                "can_continue": False,
                "can_start_new_session": False,
                "daily_limit_reached": True,
                "message": "今天已经进行过一次正式咨询，明天可以开始下一次。",
            }

        # 保险处理：把历史 open session 结束掉
        # 正常情况下不会出现，但避免异常数据
        cur.execute(
            """
            UPDATE sessions
            SET status = 'ended', ended_at = ?
            WHERE user_id = ? AND status = 'open'
            """,
            (datetime.now().isoformat(), user_id),
        )

        result = create_session(cur, user_id)
        conn.commit()

        return {"success": True, **result}

    except Exception as e:
        return {"error": str(e)}

    finally:
        if conn:
            conn.close()


@app.post("/session/finalize")
def finalize_session(req: FinalizeSessionRequest):
    """
    标记一次咨询已经完成最终保存。

    注意：
    - 这个接口应该放在 session summary / profile / care_plan 都保存成功之后调用。
    - 它是幂等的：同一个 session 调用多次，不会重复改变 final_saved_at。
    """

    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        if req.session_id:
            cur.execute(
                """
                SELECT id, user_id, started_at, ended_at, status, final_saved_at
                FROM sessions
                WHERE id = ? AND user_id = ?
                LIMIT 1
                """,
                (req.session_id, req.user_id),
            )
        else:
            cur.execute(
                """
                SELECT id, user_id, started_at, ended_at, status, final_saved_at
                FROM sessions
                WHERE user_id = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (req.user_id,),
            )

        row = cur.fetchone()

        if not row:
            return {
                "success": False,
                "message": "session not found",
                "final_saved": False,
            }

        session_id, user_id, started_at, ended_at, status, final_saved_at = row

        if final_saved_at:
            return {
                "success": True,
                "already_finalized": True,
                "user_id": user_id,
                "session_id": session_id,
                "status": status,
                "ended_at": ended_at,
                "final_saved": True,
                "final_saved_at": final_saved_at,
                "message": "session already finalized",
            }

        now = datetime.now().isoformat()
        new_ended_at = ended_at or now

        cur.execute(
            """
            UPDATE sessions
            SET status = ?, ended_at = ?, final_saved_at = ?
            WHERE id = ? AND user_id = ? AND final_saved_at IS NULL
            """,
            ("ended", new_ended_at, now, session_id, user_id),
        )

        conn.commit()

        return {
            "success": True,
            "already_finalized": False,
            "user_id": user_id,
            "session_id": session_id,
            "status": "ended",
            "ended_at": new_ended_at,
            "final_saved": True,
            "final_saved_at": now,
            "message": "session finalized",
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {
            "success": False,
            "error": str(e),
            "final_saved": False,
        }

    finally:
        if conn:
            conn.close()


@app.get("/context/{user_id}")
def get_context(user_id: str):
    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        # 1. 读取用户长期画像
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

        # 2. 读取最近 3 次完整咨询总结
        cur.execute(
            """
            SELECT summary, core_topics, next_focus, created_at
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
            summary, core_topics, next_focus, created_at = row

            item = {
                "summary": summary,
                "core_topics": core_topics or "",
                "next_focus": next_focus or "",
                "created_at": created_at,
            }
            session_summaries.append(item)

        if session_summaries:
            recent_session_summaries = "\n".join(
                [
                    f"- 咨询总结：{item['summary']}"
                    + (
                        f"\n  核心主题：{item['core_topics']}"
                        if item["core_topics"]
                        else ""
                    )
                    + (
                        f"\n  下次重点：{item['next_focus']}"
                        if item["next_focus"]
                        else ""
                    )
                    for item in session_summaries
                    if item["summary"] and item["summary"].strip()
                ]
            )
        else:
            recent_session_summaries = "暂无咨询总结。"

        # 3. 读取最近 10 条细节记忆
        cur.execute(
            """
            SELECT content, created_at
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
            }
            for row in memory_rows
            if row[0] and row[0].strip()
        ]

        if recent_memory_items:
            recent_memories = "\n".join(
                [f"- {item['content']}" for item in recent_memory_items]
            )
        else:
            recent_memories = "暂无近期细节记忆。"

        # 4. 拼接给 Dify 使用的上下文文本
        context_text = f"""
        【长期画像】
        {profile_memory}

        【最近咨询总结】
        {recent_session_summaries}

        【近期细节记忆】
        {recent_memories}
        """.strip()

        return {
            "user_id": user_id,
            "profile_memory": profile_memory,
            "profile_updated_at": profile_updated_at,
            "recent_session_summaries": recent_session_summaries,
            "recent_memories": recent_memories,
            "context_text": context_text,
            "raw": {
                "session_summaries": session_summaries,
                "recent_memory_items": recent_memory_items,
            },
        }

    except Exception as e:
        return {"error": str(e)}

    finally:
        if conn:
            conn.close()


@app.get("/session/deleted/{user_id}")
def delete_session(user_id: str):
    """
    删除用户的所有 session 和 memories。
    仅用于测试和调试。
    """
    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        # 删除 session
        cur.execute(
            """
            DELETE FROM sessions
            WHERE user_id = ?
            """,
            (user_id,),
        )

        # 删除 memories
        cur.execute(
            """
            DELETE FROM memories
            WHERE user_id = ?
            """,
            (user_id,),
        )

        conn.commit()

        return {
            "success": True,
            "message": f"Deleted all sessions and memories for user {user_id}",
        }

    except Exception as e:
        return {"error": str(e)}

    finally:
        if conn:
            conn.close()


def bool_text(value):
    return "true" if value else "false"


@app.post("/session-summary")
def save_session_summary(req: SaveSessionSummaryRequest):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO session_summaries (
            user_id, session_id, summary, core_topics, next_focus, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            req.user_id,
            req.session_id,
            req.summary,
            req.core_topics,
            req.next_focus,
            datetime.now().isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    return {"success": True, "message": "session summary saved"}


@app.post("/session-message")
def save_session_message(req: SaveSessionMessageRequest):
    if req.role not in ["user", "assistant"]:
        return {"success": False, "message": "role must be user or assistant"}

    if not req.content or not req.content.strip():
        return {"success": False, "message": "empty content skipped"}

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO session_messages (
            user_id, session_id, role, content, created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            req.user_id,
            req.session_id,
            req.role,
            req.content.strip(),
            datetime.now().isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    return {"success": True, "message": "session message saved"}


@app.get("/session-transcript/{session_id}")
def get_session_transcript(session_id: str):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT role, content, created_at
        FROM session_messages
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    )

    rows = cur.fetchall()
    conn.close()

    messages = [
        {"role": row[0], "content": row[1], "created_at": row[2]} for row in rows
    ]

    transcript_text = "\n".join(
        [
            f"{'用户' if m['role'] == 'user' else '咨询师'}：{m['content']}"
            for m in messages
        ]
    )

    return {
        "session_id": session_id,
        "messages": messages,
        "transcript_text": transcript_text,
    }


@app.delete("/session-messages/{session_id}")
def delete_session_messages(session_id: str):
    """
    删除指定 session 的所有消息。
    仅用于测试和调试。
    """
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM session_messages
        WHERE session_id = ?
        """,
        (session_id,),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": f"Deleted all messages for session {session_id}",
    }


@app.post("/debug/session/mark-latest-ended-yesterday/{user_id}")
def mark_latest_session_ended_yesterday(user_id: str):
    """
    测试用接口：
    把某个用户最近一次 session 改成“昨天已经结束”。
    用于测试：今天再次进入时是否会创建新 session。
    """

    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, started_at, ended_at, status
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

        session_id, old_started_at, old_ended_at, old_status = row

        yesterday = datetime.now() - timedelta(days=1)

        new_started_at = yesterday.replace(hour=10, minute=0, second=0, microsecond=0)
        new_ended_at = new_started_at + timedelta(minutes=SESSION_MINUTES)

        cur.execute(
            """
            UPDATE sessions
            SET started_at = ?, ended_at = ?, status = ?
            WHERE id = ?
            """,
            (new_started_at.isoformat(), new_ended_at.isoformat(), "ended", session_id),
        )

        conn.commit()

        return {
            "success": True,
            "user_id": user_id,
            "session_id": session_id,
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
            "message": "最近一次 session 已标记为昨天已结束。",
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {"success": False, "error": str(e)}

    finally:
        if conn:
            conn.close()


class SaveUserProfileRequest(BaseModel):
    user_id: str
    profile_memory: str


@app.post("/profile")
def save_user_profile(req: SaveUserProfileRequest):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO user_profiles (user_id, profile_memory, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            profile_memory = excluded.profile_memory,
            updated_at = excluded.updated_at
        """,
        (req.user_id, req.profile_memory.strip(), datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()

    return {"success": True, "message": "user profile saved"}


@app.post("/profile")
def save_user_profile(req: SaveUserProfileRequest):
    """
    保存或更新用户长期画像。
    如果 user_id 已存在，则覆盖更新 profile_memory。
    如果 user_id 不存在，则新建。
    """

    content = req.profile_memory.strip()

    if not content:
        return {"success": False, "message": "empty profile_memory skipped"}

    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO user_profiles (user_id, profile_memory, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                profile_memory = excluded.profile_memory,
                updated_at = excluded.updated_at
            """,
            (req.user_id, content, datetime.now().isoformat()),
        )

        conn.commit()

        return {
            "success": True,
            "user_id": req.user_id,
            "message": "user profile saved",
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {"success": False, "error": str(e)}

    finally:
        if conn:
            conn.close()


@app.get("/profile/{user_id}")
def get_user_profile(user_id: str):
    conn = None

    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

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

        return {
            "exists": True,
            "user_id": row[0],
            "profile_memory": row[1],
            "updated_at": row[2],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        if conn:
            conn.close()


@app.get("/care-plan/{user_id}")
def get_care_plan(user_id: str):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT plan_text, updated_at
        FROM care_plans
        WHERE user_id = ?
        """,
        (user_id,),
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        return {
            "exists": False,
            "user_id": user_id,
            "plan_text": "暂无咨询计划表。",
            "updated_at": None,
        }

    return {
        "exists": True,
        "user_id": user_id,
        "plan_text": row[0],
        "updated_at": row[1],
    }


@app.post("/care-plan")
def save_care_plan(req: SaveCarePlanRequest):
    content = req.plan_text.strip()

    if not content:
        return {
            "success": False,
            "message": "empty care plan skipped",
        }

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO care_plans (user_id, plan_text, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            plan_text = excluded.plan_text,
            updated_at = excluded.updated_at
        """,
        (req.user_id, content, datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "user_id": req.user_id,
        "message": "care plan saved",
    }
