import json
import uuid
from datetime import datetime

from app.services.quality import build_quality_plan
from app.utils import (
    clean_text,
    detect_risk_level,
    highest_risk_level,
    now_iso,
    truncate_text,
)


SUPPORTED_HANDOFF_FORMATS = {"markdown", "json"}
DEFAULT_USER_HANDOFF_SESSION_LIMIT = 10


def _minutes_between(started_at: str, ended_at: str | None) -> float:
    if not started_at or not ended_at:
        return 0
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at)
    except ValueError:
        return 0
    return round(max((end - start).total_seconds() / 60, 0), 2)


def _fetch_session(cur, session_id: str):
    cur.execute(
        """
        SELECT id, session_id, user_id, started_at, ended_at, status,
               stage, summary, risk_level, is_low_content, summary_type,
               user_message_count, user_char_count
        FROM sessions
        WHERE id = ? OR session_id = ?
        LIMIT 1
        """,
        (session_id, session_id),
    )
    return cur.fetchone()


def _fetch_summary(cur, session_id: str):
    cur.execute(
        """
        SELECT summary, core_topics, next_focus, risk_level, created_at
        FROM session_summaries
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
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


def _fetch_memories(cur, session_id: str):
    cur.execute(
        """
        SELECT content, memory_type, importance, created_at
        FROM memories
        WHERE session_id = ?
        ORDER BY importance DESC, id DESC
        LIMIT 10
        """,
        (session_id,),
    )
    return cur.fetchall()


def build_handoff_payload(cur, session_id: str) -> dict:
    session = _fetch_session(cur, session_id)
    if not session:
        raise RuntimeError("session not found")

    (
        session_pk,
        public_session_id,
        user_id,
        started_at,
        ended_at,
        status,
        stage,
        session_summary,
        session_risk_level,
        is_low_content,
        summary_type,
        stored_user_message_count,
        stored_user_char_count,
    ) = session
    session_id_value = public_session_id or session_pk

    summary_row = _fetch_summary(cur, session_id_value)
    messages = _fetch_messages(cur, session_id_value)
    memories = _fetch_memories(cur, session_id_value)

    user_messages = [row for row in messages if row[0] == "user"]
    assistant_messages = [row for row in messages if row[0] == "assistant"]
    first_user_text = truncate_text(user_messages[0][1], 260) if user_messages else ""
    user_quotes = [truncate_text(row[1], 80) for row in user_messages[:3]]
    all_text = "\n".join([row[1] for row in messages if row[1]])

    summary = clean_text(session_summary or "")
    core_topics = ""
    next_focus = ""
    summary_risk_level = "none"
    if summary_row:
        summary = summary or clean_text(summary_row[0])
        core_topics = clean_text(summary_row[1] or "")
        next_focus = clean_text(summary_row[2] or "")
        summary_risk_level = summary_row[3] or "none"

    message_risk = detect_risk_level(all_text)
    row_risk = highest_risk_level(*[row[2] for row in messages])
    risk_level = highest_risk_level(session_risk_level, summary_risk_level, row_risk, message_risk)
    risk_statement = (
        "检测到高危表达，建议尽快转人工复核并提供危机支持资源。"
        if risk_level == "high"
        else "本次未发现明确自伤/自杀表达。"
    )

    memory_candidates = [
        {
            "content": row[0],
            "memory_type": row[1],
            "importance": row[2],
            "reason": "已保存为长期记忆候选。",
            "should_save": True,
            "source_session_id": session_id_value,
            "evidence_type": "fact",
        }
        for row in memories
    ]
    if not memory_candidates and summary and not is_low_content:
        memory_candidates.append(
            {
                "content": truncate_text(summary, 260),
                "memory_type": "therapy_goal",
                "importance": 2,
                "reason": "来自本次咨询总结，可用于下次跟进。",
                "should_save": True,
                "source_session_id": session_id_value,
                "evidence_type": "fact",
            }
        )
    if is_low_content:
        memory_candidates.append(
            {
                "content": "本次为低内容会话，不建议写入长期记忆。",
                "memory_type": "quality_note",
                "importance": 1,
                "reason": "用户有效输入不足，不能作为咨询判断依据。",
                "should_save": False,
                "source_session_id": session_id_value,
                "evidence_type": "fact",
            }
        )

    facts = []
    if first_user_text:
        facts.append(f"用户开场或关键表达：{first_user_text}")
    facts.append(f"记录到用户有效消息 {len(user_messages)} 条，助手消息 {len(assistant_messages)} 条。")
    if core_topics:
        facts.append(f"已保存核心主题：{core_topics}")

    hypotheses = []
    if summary and not is_low_content:
        hypotheses.append("可能需要继续验证用户困扰与现实任务之间的关系。")
    if not hypotheses:
        hypotheses.append("暂无足够材料形成假设。")

    psychological_plan = [
        "先稳定咨询关系，减少过细追问。",
        "允许用户表达“不想做这个建议”，不把拒绝解释成人格问题。",
        "识别游戏切换、项目卡住、疲劳和自责之间的关系。",
    ]
    action_plan = [
        "今天只要求一个 25 分钟项目块。",
        "记录第一次打开游戏前正在做什么。",
        "不要求戒游戏，不要求立刻达到 8 小时。",
    ]

    quality_plan = build_quality_plan()
    return {
        "title": "咨询交接文档",
        "is_low_content": bool(is_low_content),
        "summary_type": summary_type or ("low_content" if is_low_content else "formal"),
        "basic_info": {
            "user_id": user_id,
            "session_id": session_id_value,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_minutes": _minutes_between(started_at, ended_at),
            "status": status,
            "session_stage": stage or "ended",
        },
        "session_validity": {
            "is_low_content": bool(is_low_content),
            "user_message_count": stored_user_message_count or len(user_messages),
            "user_char_count": stored_user_char_count or sum(len(row[1]) for row in user_messages),
            "has_specific_concern": bool(core_topics or summary),
            "formal_summary_generated": bool(summary_row) and not bool(is_low_content),
            "memory_written": bool(memories) and not bool(is_low_content),
            "note": "本次为低内容会话，不作为咨询判断依据。" if is_low_content else "本次有足够内容生成正式交接摘要。",
        },
        "facts": facts,
        "user_quotes": user_quotes,
        "stage_understanding": {
            "text": summary or "暂无正式总结。",
            "caution": "这是阶段性理解，不是医学诊断。",
        },
        "hypotheses": hypotheses,
        "current_goals": {
            "psychological": "减少自责，修复咨询关系，识别压力触发点。",
            "practical": "围绕项目推进、游戏切换、专注时长或现实压力制定小步骤。",
        },
        "relationship_preferences": {
            "observed": "如果用户表达烦躁或质疑，应减少追问密度，先确认希望的交流方式。",
            "avoid": "避免把质疑上升为防御、人格或深层动机判断。",
        },
        "topic": {
            "main_concern": core_topics or truncate_text(summary, 220) or "暂无明确主题总结。",
            "initial_expression": first_user_text or "暂无用户开场表达记录。",
            "core_issue": core_topics or "需要在后续咨询中继续澄清。",
        },
        "emotion_observation": {
            "main_emotions": "需结合原始咨询上下文由后续咨询师复核。",
            "intensity": "未量化",
            "changes": "暂无稳定趋势记录。",
            "avoidance_or_anxiety": "未自动判定；建议人工复核。",
        },
        "background": {
            "related_context": truncate_text(summary, 300) or "暂无可提炼背景。",
            "privacy_note": "仅保留对咨询连续性有帮助的信息。",
        },
        "process": {
            "guidance": "系统根据已保存摘要与消息生成结构化交接草稿。",
            "responses": f"记录到用户消息 {len(user_messages)} 条，助手消息 {len(assistant_messages)} 条。",
            "resistance_or_silence": "未自动判定；建议人工复核。",
            "stage_reached": stage or "ended",
        },
        "risk_assessment": {
            "risk_level": risk_level,
            "statement": risk_statement,
            "needs_next_review": risk_level in {"medium", "high"} or not bool(is_low_content),
            "suggested_action": (
                "优先转人工咨询师或危机干预资源。"
                if risk_level == "high"
                else "按普通咨询连续性处理，仍需保留风险复核意识。"
            ),
        },
        "understanding": {
            "current_understanding": summary or "暂无咨询总结。",
            "possible_patterns": "禁止写成医学诊断；后续仅作为假设继续验证。",
            "questions_to_verify": next_focus or "下次继续澄清主要困扰、可行动目标和支持资源。",
        },
        "assigned_tasks": {
            "exercises": "暂无明确记录。",
            "accepted": "未知",
            "follow_up": next_focus or "下次咨询开始时回访本次核心议题。",
        },
        "next_session_suggestions": {
            "start_from": next_focus or core_topics or "先确认用户当前状态与本次咨询后的变化。",
            "questions": "继续追问情绪变化、具体触发情境、已尝试的应对方式。",
            "avoid": "避免医学诊断式表达，避免夸大风险。",
            "strategy": "支持性倾听、情绪稳定、阶段性总结和小行动计划。",
        },
        "psychological_plan": psychological_plan,
        "action_plan": action_plan,
        "long_term_memory_candidates": memory_candidates,
        "human_counselor_notes": {
            "priority": risk_statement,
            "sensitive_language": "避免使用诊断、评判或承诺疗效的表达。",
            "communication_style": "温和、具体、允许用户保留节奏。",
        },
        "safety_notice": "本系统是心理支持/情绪陪伴/自助反思工具，不是医疗诊断，不能替代专业心理咨询、精神科医生或紧急救援。",
    }


def render_handoff_markdown(payload: dict) -> str:
    info = payload["basic_info"]
    risk = payload["risk_assessment"]
    next_session = payload["next_session_suggestions"]
    memories = payload["long_term_memory_candidates"]
    validity = payload["session_validity"]

    fact_lines = "\n".join([f"- {item}" for item in payload["facts"]]) or "- 暂无可确认事实。"
    quote_lines = "\n".join([f"- “{item}”" for item in payload["user_quotes"]]) or "- 暂无关键原话摘录。"
    hypothesis_lines = "\n".join([f"- {item}" for item in payload["hypotheses"]]) or "- 暂无待验证假设。"
    psychological_lines = "\n".join([f"- {item}" for item in payload["psychological_plan"]])
    action_lines = "\n".join([f"- {item}" for item in payload["action_plan"]])
    memory_lines = "\n".join(
        [
            f"- 建议保存：{item['should_save']}；[{item['memory_type']}] {item['content']}；"
            f"证据：{item['evidence_type']} / {item['source_session_id']}；原因：{item['reason']}"
            for item in memories
        ]
    ) or "- 暂无明确长期记忆候选。"

    return f"""# 咨询交接文档

## 1. 基本信息
- 用户 ID：{info['user_id']}
- session_id：{info['session_id']}
- 咨询开始时间：{info['started_at']}
- 咨询结束时间：{info['ended_at'] or '尚未记录'}
- 咨询时长：{info['duration_minutes']} 分钟
- 当前会话状态：{info['status']}

## 2. 本次会话有效性
- 是否低内容会话：{validity['is_low_content']}
- 用户有效输入数量：{validity['user_message_count']}
- 用户总字数：{validity['user_char_count']}
- 是否有具体困扰：{validity['has_specific_concern']}
- 是否生成正式总结：{validity['formal_summary_generated']}
- 是否写入长期记忆：{validity['memory_written']}
- 说明：{validity['note']}

## 3. 主要事实观察
{fact_lines}

## 4. 用户原话摘录
{quote_lines}

## 5. 阶段性理解
- {payload['stage_understanding']['text']}
- 谨慎说明：{payload['stage_understanding']['caution']}

## 6. 当前困扰与现实目标
- 心理线：{payload['current_goals']['psychological']}
- 行动线：{payload['current_goals']['practical']}

## 7. 咨询关系与互动偏好
- 观察：{payload['relationship_preferences']['observed']}
- 避免：{payload['relationship_preferences']['avoid']}

## 8. 风险评估
- 风险等级：{risk['risk_level']}
- 风险情况：{risk['statement']}
- 下次是否需要复核：{risk['needs_next_review']}
- 建议处理：{risk['suggested_action']}

## 9. 心理线计划
{psychological_lines}

## 10. 行动线计划
{action_lines}

## 11. 下次咨询建议
- 建议从哪里开始：{next_session['start_from']}
- 建议继续追问：{next_session['questions']}
- 建议避免：{next_session['avoid']}
- 建议策略：{next_session['strategy']}

## 12. 长期记忆候选
{memory_lines}

## 待验证假设
{hypothesis_lines}

> {payload['safety_notice']}
"""


def render_handoff_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_user_handoff_payload(cur, user_id: str, session_limit: int = DEFAULT_USER_HANDOFF_SESSION_LIMIT) -> dict:
    session_limit = max(1, min(int(session_limit or DEFAULT_USER_HANDOFF_SESSION_LIMIT), 100))
    quality_plan = build_quality_plan()

    cur.execute(
        """
        SELECT profile_memory, updated_at
        FROM user_profiles
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    profile = cur.fetchone()

    cur.execute(
        """
        SELECT plan_text, updated_at
        FROM care_plans
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    care_plan = cur.fetchone()

    cur.execute(
        """
        SELECT id, session_id, started_at, ended_at, status, summary, risk_level
        FROM sessions
        WHERE user_id = ?
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (user_id, session_limit),
    )
    sessions = cur.fetchall()

    session_ids = [row[1] or row[0] for row in sessions]
    summaries = []
    memories = []
    latest_messages = []
    if session_ids:
        placeholders = ",".join(["?"] * len(session_ids))
        cur.execute(
            f"""
            SELECT session_id, summary, core_topics, next_focus, risk_level, created_at
            FROM session_summaries
            WHERE session_id IN ({placeholders})
            ORDER BY created_at DESC
            """,
            tuple(session_ids),
        )
        summaries = cur.fetchall()

        cur.execute(
            f"""
            SELECT session_id, content, memory_type, importance, created_at
            FROM memories
            WHERE user_id = ? AND (session_id IN ({placeholders}) OR session_id = '')
            ORDER BY importance DESC, created_at DESC
            LIMIT 20
            """,
            (user_id, *session_ids),
        )
        memories = cur.fetchall()

        cur.execute(
            f"""
            SELECT session_id, role, content, risk_level, created_at
            FROM session_messages
            WHERE session_id IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT 30
            """,
            tuple(session_ids),
        )
        latest_messages = cur.fetchall()

    summary_by_session = {}
    for session_id, summary, core_topics, next_focus, risk_level, created_at in summaries:
        summary_by_session.setdefault(
            session_id,
            {
                "summary": summary,
                "core_topics": core_topics or "",
                "next_focus": next_focus or "",
                "risk_level": risk_level or "none",
                "created_at": created_at,
            },
        )

    session_items = []
    all_risk_levels = []
    for row in sessions:
        session_pk, public_session_id, started_at, ended_at, status, session_summary, risk_level = row
        session_id = public_session_id or session_pk
        summary = summary_by_session.get(session_id, {})
        all_risk_levels.append(risk_level or "none")
        all_risk_levels.append(summary.get("risk_level", "none"))
        session_items.append(
            {
                "session_id": session_id,
                "started_at": started_at,
                "ended_at": ended_at,
                "status": status,
                "duration_minutes": _minutes_between(started_at, ended_at),
                "summary": clean_text(summary.get("summary") or session_summary or ""),
                "core_topics": clean_text(summary.get("core_topics") or ""),
                "next_focus": clean_text(summary.get("next_focus") or ""),
                "risk_level": highest_risk_level(risk_level, summary.get("risk_level", "none")),
            }
        )

    user_text = "\n".join([row[2] for row in latest_messages if row[1] == "user" and row[2]])
    message_risk = detect_risk_level(user_text)
    risk_level = highest_risk_level(message_risk, *all_risk_levels)

    memory_items = [
        {
            "session_id": row[0] or "",
            "content": row[1],
            "memory_type": row[2] or "general",
            "importance": row[3] or 1,
            "created_at": row[4],
        }
        for row in memories
    ]

    message_items = [
        {
            "session_id": row[0],
            "role": row[1],
            "content": truncate_text(row[2], 180),
            "risk_level": row[3] or "none",
            "created_at": row[4],
        }
        for row in latest_messages
    ]

    return {
        "title": "用户咨询交接文档",
        "user_id": user_id,
        "generated_at": now_iso(),
        "scope": {
            "type": "user",
            "session_count": len(session_items),
            "session_limit": session_limit,
            "note": "按用户维度汇总最近多次咨询、长期记忆和计划表，不复制完整聊天记录。",
        },
        "profile": {
            "profile_memory": profile[0] if profile else "暂无长期画像。",
            "updated_at": profile[1] if profile else None,
        },
        "care_plan": {
            "plan_text": care_plan[0] if care_plan else "暂无咨询计划表。",
            "updated_at": care_plan[1] if care_plan else None,
        },
        "sessions": session_items,
        "long_term_memories": memory_items,
        "recent_message_clues": message_items,
        "risk_assessment": {
            "risk_level": risk_level,
            "statement": (
                "历史记录中检测到高危表达或高风险标记，建议咨询师优先人工复核。"
                if risk_level == "high"
                else "最近记录中未发现明确自伤/自杀表达；仍建议接手时常规复核风险。"
            ),
        },
        "handoff_notes": {
            "priority": "先确认用户当前状态、最近一次咨询后的变化，以及是否有紧急风险。",
            "continuity": "结合长期画像、计划表和最近多次咨询总结继续跟进，不要只依据单次开场表达判断。",
            "privacy": "本文档是结构化交接摘要，不应作为完整聊天记录外发。",
        },
        "long_term_plan": {
            "phase_1": "稳定咨询关系：少解释、少追问、每轮最多一个问题，用户烦躁时先修复关系。",
            "phase_2": "识别行为链：观察等待 Codex、代码卡住、疲劳、焦虑、不知道下一步时是否切到游戏。",
            "phase_3": "微行动实验：不要求戒游戏，只在自动切换前插入停 1 秒、数 5 下或记录动作。",
            "phase_4": "现实行动计划：建立可持续项目推进节奏。",
            "psychological_line": quality_plan["psychological_line"],
            "action_line": quality_plan["action_line"],
            "metrics": quality_plan["metrics"],
        },
        "safety_notice": "本系统是心理支持/情绪陪伴/自助反思工具，不是医疗诊断，不能替代专业心理咨询、精神科医生或紧急救援。",
    }


def render_user_handoff_markdown(payload: dict) -> str:
    session_lines = "\n".join(
        [
            f"- session_id `{item['session_id']}`：{item['started_at']} 至 {item['ended_at'] or '未记录'}，"
            f"状态 {item['status']}，风险 {item['risk_level']}。\n"
            f"  摘要：{item['summary'] or '暂无摘要'}\n"
            f"  核心主题：{item['core_topics'] or '暂无记录'}\n"
            f"  下次重点：{item['next_focus'] or '暂无记录'}"
            for item in payload["sessions"]
        ]
    ) or "- 暂无 session 记录。"

    memory_lines = "\n".join(
        [
            f"- [{item['memory_type']}] {item['content']}（重要性：{item['importance']}，session：{item['session_id'] or '全局'}）"
            for item in payload["long_term_memories"]
        ]
    ) or "- 暂无长期记忆。"

    clue_lines = "\n".join(
        [
            f"- {item['created_at']} `{item['session_id']}` {item['role']}：{item['content']}"
            for item in payload["recent_message_clues"]
        ]
    ) or "- 暂无最近消息线索。"
    plan = payload["long_term_plan"]
    psychological_lines = "\n".join([f"- {item}" for item in plan["psychological_line"]])
    action_lines = "\n".join([f"- {item}" for item in plan["action_line"]])
    metric_lines = "\n".join([f"- {item}" for item in plan["metrics"]])

    return f"""# 用户咨询交接文档

## 1. 基本信息
- 用户 ID：{payload['user_id']}
- 生成时间：{payload['generated_at']}
- 汇总范围：最近 {payload['scope']['session_count']} 次 session（上限 {payload['scope']['session_limit']} 次）
- 范围说明：{payload['scope']['note']}

## 2. 长期画像
- 更新时间：{payload['profile']['updated_at'] or '暂无'}

{payload['profile']['profile_memory']}

## 3. 咨询计划表
- 更新时间：{payload['care_plan']['updated_at'] or '暂无'}

{payload['care_plan']['plan_text']}

## 4. 最近多次咨询摘要
{session_lines}

## 5. 长期记忆与持续议题
{memory_lines}

## 6. 最近消息线索
{clue_lines}

## 7. 风险评估
- 风险等级：{payload['risk_assessment']['risk_level']}
- 风险说明：{payload['risk_assessment']['statement']}

## 8. 给接手咨询师的建议
- 优先确认：{payload['handoff_notes']['priority']}
- 连续性建议：{payload['handoff_notes']['continuity']}
- 隐私边界：{payload['handoff_notes']['privacy']}

## 9. 长期计划：心理线 + 行动线
- 阶段 1：{plan['phase_1']}
- 阶段 2：{plan['phase_2']}
- 阶段 3：{plan['phase_3']}
- 阶段 4：{plan['phase_4']}

### 心理线
{psychological_lines}

### 行动线
{action_lines}

### 可验证指标
{metric_lines}

> {payload['safety_notice']}
"""


def render_user_handoff_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_user_handoff_document(
    cur,
    user_id: str,
    document_format: str = "markdown",
    session_limit: int = DEFAULT_USER_HANDOFF_SESSION_LIMIT,
) -> dict:
    document_format = (document_format or "markdown").lower()
    if document_format not in SUPPORTED_HANDOFF_FORMATS:
        raise RuntimeError("only markdown and json handoff formats are supported in MVP")

    payload = build_user_handoff_payload(cur, user_id, session_limit=session_limit)
    content = (
        render_user_handoff_json(payload)
        if document_format == "json"
        else render_user_handoff_markdown(payload)
    )
    return {
        "document_id": f"user-{user_id}-{payload['generated_at']}",
        "session_id": f"user:{user_id}",
        "user_id": user_id,
        "title": payload["title"],
        "format": document_format,
        "content": json.loads(content) if document_format == "json" else content,
        "download_url": f"/handoff/export/user/{user_id}?format={document_format}&session_limit={payload['scope']['session_limit']}",
        "file_path": None,
        "generated_by": "system_user_handoff",
        "created_at": payload["generated_at"],
        "updated_at": payload["generated_at"],
    }


def _render_payload(payload: dict, document_format: str) -> str:
    if document_format == "markdown":
        return render_handoff_markdown(payload)
    if document_format == "json":
        return render_handoff_json(payload)
    raise RuntimeError("unsupported handoff format")


def _document_response(row) -> dict:
    (
        document_id,
        user_id,
        session_id,
        title,
        document_format,
        content,
        file_path,
        generated_by,
        created_at,
        updated_at,
    ) = row

    parsed_content = content
    if document_format == "json":
        try:
            parsed_content = json.loads(content)
        except json.JSONDecodeError:
            parsed_content = content

    return {
        "document_id": document_id,
        "session_id": session_id,
        "user_id": user_id,
        "title": title,
        "format": document_format,
        "content": parsed_content,
        "download_url": f"/handoff/export/{document_id}",
        "file_path": file_path,
        "generated_by": generated_by,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def generate_handoff_document(
    cur,
    session_id: str,
    document_format: str = "markdown",
    regenerate: bool = False,
    include_low_content: bool = False,
    generated_by: str = "system",
) -> dict:
    document_format = (document_format or "markdown").lower()
    if document_format not in SUPPORTED_HANDOFF_FORMATS:
        raise RuntimeError("only markdown and json handoff formats are supported in MVP")

    cur.execute(
        """
        SELECT document_id, user_id, session_id, title, format, content,
               file_path, generated_by, created_at, updated_at
        FROM handoff_documents
        WHERE session_id = ? AND format = ? AND generated_by = ?
        LIMIT 1
        """,
        (session_id, document_format, generated_by),
    )
    existing = cur.fetchone()

    if existing and not regenerate:
        return _document_response(existing)

    payload = build_handoff_payload(cur, session_id)
    if payload.get("is_low_content") and not include_low_content:
        return {
            "generated": False,
            "reason": "low_content_session",
            "message": "本次会话内容不足，未生成正式咨询交接文档。",
            "session_id": payload["basic_info"]["session_id"],
            "user_id": payload["basic_info"]["user_id"],
            "format": document_format,
            "is_low_content": True,
            "content_quality": "low_content",
        }

    content = _render_payload(payload, document_format)
    now = now_iso()

    if existing:
        document_id = existing[0]
        cur.execute(
            """
            UPDATE handoff_documents
            SET title = ?,
                content = ?,
                file_path = NULL,
                is_low_content = ?,
                content_quality = ?,
                generated_reason = ?,
                source_session_count = 1,
                updated_at = ?
            WHERE document_id = ?
            """,
            (
                payload["title"],
                content,
                1 if payload.get("is_low_content") else 0,
                payload.get("summary_type", "formal"),
                "manual_regenerate" if regenerate else "session_handoff",
                now,
                document_id,
            ),
        )
    else:
        document_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO handoff_documents (
                document_id, user_id, session_id, title, format, content,
                file_path, generated_by, is_low_content, content_quality,
                generated_reason, source_session_count, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                payload["basic_info"]["user_id"],
                payload["basic_info"]["session_id"],
                payload["title"],
                document_format,
                content,
                None,
                generated_by,
                1 if payload.get("is_low_content") else 0,
                payload.get("summary_type", "formal"),
                "manual_regenerate" if regenerate else "session_handoff",
                1,
                now,
                now,
            ),
        )

    return get_handoff_document(cur, document_id)


def get_handoff_document(cur, document_id: str) -> dict | None:
    cur.execute(
        """
        SELECT document_id, user_id, session_id, title, format, content,
               file_path, generated_by, created_at, updated_at
        FROM handoff_documents
        WHERE document_id = ?
        LIMIT 1
        """,
        (document_id,),
    )
    row = cur.fetchone()
    return _document_response(row) if row else None


def list_handoff_documents_for_session(cur, session_id: str) -> list[dict]:
    cur.execute(
        """
        SELECT document_id, user_id, session_id, title, format, content,
               file_path, generated_by, created_at, updated_at
        FROM handoff_documents
        WHERE session_id = ?
        ORDER BY created_at DESC
        """,
        (session_id,),
    )
    return [_document_response(row) for row in cur.fetchall()]


def list_handoff_documents_for_user(
    cur,
    user_id: str,
    document_format: str | None = None,
    limit: int = 20,
) -> list[dict]:
    if document_format:
        cur.execute(
            """
            SELECT document_id, user_id, session_id, title, format, content,
                   file_path, generated_by, created_at, updated_at
            FROM handoff_documents
            WHERE user_id = ? AND format = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, document_format.lower(), limit),
        )
    else:
        cur.execute(
            """
            SELECT document_id, user_id, session_id, title, format, content,
                   file_path, generated_by, created_at, updated_at
            FROM handoff_documents
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
    return [_document_response(row) for row in cur.fetchall()]


def get_latest_handoff_document_for_user(
    cur,
    user_id: str,
    document_format: str | None = None,
) -> dict | None:
    documents = list_handoff_documents_for_user(
        cur,
        user_id=user_id,
        document_format=document_format,
        limit=1,
    )
    return documents[0] if documents else None
