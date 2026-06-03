from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.utils import clean_text, now_iso, truncate_text


@dataclass(frozen=True)
class EventRule:
    name: str
    hints: tuple[str, ...]
    min_hits: int = 1


EVENT_RULES: tuple[EventRule, ...] = (
    EventRule(
        "problem_map_created",
        ("没工作", "失业", "面试", "求职", "项目", "游戏", "自责", "同事", "拖", "压力"),
        min_hits=3,
    ),
    EventRule(
        "initial_plan_created",
        ("很小", "小动作", "试试", "5 分钟", "5分钟", "五分钟", "打开项目", "不保证", "可以试"),
        min_hits=2,
    ),
    EventRule(
        "execution_feedback_received",
        ("上次", "任务", "没做成", "没完成", "做到", "做到了", "打开了", "试了", "反馈"),
        min_hits=2,
    ),
    EventRule(
        "obstacle_identified",
        ("刷视频", "熬夜", "自责", "羞耻", "怕", "太重", "开始前", "紧张", "没用", "讲不清"),
        min_hits=1,
    ),
    EventRule(
        "plan_adjusted_or_downshifted",
        ("再小", "更小", "下调", "轻一点", "不需要打开", "只打开", "不写代码", "清一下", "换方向"),
        min_hits=1,
    ),
    EventRule(
        "partial_success_recognized",
        ("一半", "部分", "打开了", "3 分钟", "3分钟", "三分钟", "没那么自责", "算不算进步"),
        min_hits=1,
    ),
    EventRule(
        "continuous_action_recognized",
        ("这两天", "连续", "都有", "每天", "这周基本每天", "没有完全逃掉", "不像之前"),
        min_hits=1,
    ),
    EventRule(
        "plan_gently_upgraded",
        ("加一点", "多一点点", "很小一步", "项目问题", "面试回答", "别太重", "不要安排太满"),
        min_hits=1,
    ),
    EventRule(
        "stage_completion_recognized",
        ("总结", "这几次", "这周", "做到了什么", "阶段", "先结束", "交接总结"),
        min_hits=1,
    ),
    EventRule(
        "next_stage_plan_created",
        ("下一阶段", "接下来", "继续准备", "下一次", "下次", "怎么走"),
        min_hits=1,
    ),
)

CARE_PLAN_EVENTS = {
    "problem_map_created",
    "initial_plan_created",
    "execution_feedback_received",
    "obstacle_identified",
    "plan_adjusted_or_downshifted",
    "partial_success_recognized",
    "continuous_action_recognized",
    "plan_gently_upgraded",
    "stage_completion_recognized",
    "next_stage_plan_created",
}

PROFILE_EVENTS = {
    "problem_map_created",
    "execution_feedback_received",
    "obstacle_identified",
    "partial_success_recognized",
    "continuous_action_recognized",
    "stage_completion_recognized",
}

DEFAULT_CARE_PLAN = "暂无咨询计划表。"
DEFAULT_PROFILE = ""


def analyze_longitudinal_events(messages: list, summary: str = "", core_topics: str = "", next_focus: str = "") -> dict:
    user_text = "\n".join(clean_text(row[1]) for row in messages if row[0] == "user" and row[1])
    assistant_text = "\n".join(clean_text(row[1]) for row in messages if row[0] == "assistant" and row[1])
    combined = "\n".join([user_text, assistant_text, summary or "", core_topics or "", next_focus or ""])

    events = {}
    for rule in EVENT_RULES:
        hits = [hint for hint in rule.hints if hint in combined]
        if len(hits) >= rule.min_hits:
            events[rule.name] = {
                "hints": hits[:6],
                "source": _first_evidence(messages, rule.hints) or truncate_text(summary or core_topics or combined, 180),
            }

    return events


def merge_profile_memory(existing: str, incoming: str, *, source_label: str = "") -> str:
    return _merge_text(existing, incoming, default=DEFAULT_PROFILE, source_label=source_label, limit=2400)


def merge_care_plan(existing: str, incoming: str, *, source_label: str = "") -> str:
    return _merge_text(existing, incoming, default=DEFAULT_CARE_PLAN, source_label=source_label, limit=4000)


def update_longitudinal_records_after_session(
    cur,
    *,
    user_id: str,
    session_id: str,
    messages: list,
    summary: str,
    core_topics: str,
    next_focus: str,
) -> dict:
    events = analyze_longitudinal_events(messages, summary, core_topics, next_focus)
    if not events:
        return {"events": [], "care_plan_updated": False, "profile_updated": False}

    care_events = [name for name in events if name in CARE_PLAN_EVENTS]
    profile_events = [name for name in events if name in PROFILE_EVENTS]
    result = {
        "events": sorted(events),
        "care_plan_updated": False,
        "profile_updated": False,
    }

    if care_events:
        care_increment = _build_care_plan_increment(
            session_id=session_id,
            event_names=care_events,
            events=events,
            summary=summary,
            core_topics=core_topics,
            next_focus=next_focus,
        )
        result["care_plan_updated"] = _upsert_merged_text(
            cur,
            table="care_plans",
            text_column="plan_text",
            user_id=user_id,
            incoming=care_increment,
            default=DEFAULT_CARE_PLAN,
            limit=4000,
        )

    if profile_events:
        profile_increment = _build_profile_increment(
            session_id=session_id,
            event_names=profile_events,
            events=events,
            summary=summary,
            core_topics=core_topics,
            next_focus=next_focus,
        )
        result["profile_updated"] = _upsert_merged_text(
            cur,
            table="user_profiles",
            text_column="profile_memory",
            user_id=user_id,
            incoming=profile_increment,
            default=DEFAULT_PROFILE,
            limit=2400,
        )

    return result


def _merge_text(existing: str, incoming: str, *, default: str, source_label: str, limit: int) -> str:
    incoming = clean_text(incoming)
    existing = clean_text(existing)
    if not incoming:
        return existing
    if not existing or existing == default or existing in incoming:
        return incoming[:limit].rstrip()
    if incoming in existing:
        return existing[:limit].rstrip()

    label = clean_text(source_label)
    prefix = f"{label}：" if label else "增量更新："
    merged = f"{existing}\n\n{prefix}{incoming}"
    return _trim_sections(merged, limit)


def _upsert_merged_text(
    cur,
    *,
    table: str,
    text_column: str,
    user_id: str,
    incoming: str,
    default: str,
    limit: int,
) -> bool:
    cur.execute(f"SELECT {text_column} FROM {table} WHERE user_id = ? LIMIT 1", (user_id,))
    row = cur.fetchone()
    existing = row[0] if row else ""
    merged = _merge_text(existing, incoming, default=default, source_label="", limit=limit)
    if clean_text(existing) == clean_text(merged):
        return False

    now = now_iso()
    cur.execute(
        f"""
        INSERT INTO {table} (user_id, {text_column}, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            {text_column} = excluded.{text_column},
            updated_at = excluded.updated_at
        """,
        (user_id, merged, now, now),
    )
    return True


def _build_care_plan_increment(
    *,
    session_id: str,
    event_names: Iterable[str],
    events: dict,
    summary: str,
    core_topics: str,
    next_focus: str,
) -> str:
    event_text = "、".join(_event_label(name) for name in event_names)
    evidence = _event_evidence_line(event_names, events)
    plan_focus = next_focus or "下次从用户本次反馈到的阻碍、可承受动作和实际完成情况接续。"
    return "\n".join(
        [
            f"Session {session_id} 增量：",
            f"- 有效事件：{event_text}",
            f"- 本次证据：{evidence}",
            f"- 阶段性理解：{truncate_text(core_topics or summary, 260)}",
            f"- 计划修正：根据本次事件调整下一步，不重复不适合的旧计划；下次优先关注：{truncate_text(plan_focus, 220)}",
        ]
    )


def _build_profile_increment(
    *,
    session_id: str,
    event_names: Iterable[str],
    events: dict,
    summary: str,
    core_topics: str,
    next_focus: str,
) -> str:
    event_text = "、".join(_event_label(name) for name in event_names)
    evidence = _event_evidence_line(event_names, events)
    return "\n".join(
        [
            f"Session {session_id} 增量：",
            f"- 可接续画像事件：{event_text}",
            f"- 用户表达或稳定线索：{evidence}",
            f"- 下次可接续点：{truncate_text(next_focus or core_topics or summary, 220)}",
        ]
    )


def _event_evidence_line(event_names: Iterable[str], events: dict) -> str:
    evidence = []
    for name in event_names:
        source = clean_text(events.get(name, {}).get("source", ""))
        if source and source not in evidence:
            evidence.append(source)
    return truncate_text(" / ".join(evidence), 360)


def _first_evidence(messages: list, hints: tuple[str, ...]) -> str:
    for role, content, *_rest in messages:
        text = clean_text(content)
        if text and any(hint in text for hint in hints):
            return f"{'用户' if role == 'user' else '助手'}：{truncate_text(text, 180)}"
    return ""


def _event_label(name: str) -> str:
    labels = {
        "problem_map_created": "问题地图",
        "initial_plan_created": "初始计划",
        "execution_feedback_received": "执行反馈",
        "obstacle_identified": "具体阻碍",
        "plan_adjusted_or_downshifted": "计划调整/下调",
        "partial_success_recognized": "部分完成",
        "continuous_action_recognized": "连续行动",
        "plan_gently_upgraded": "温和加量",
        "stage_completion_recognized": "阶段完成",
        "next_stage_plan_created": "下一阶段计划",
    }
    return labels.get(name, name)


def _trim_sections(text: str, limit: int) -> str:
    text = clean_text(text).replace(" 增量更新：Session", "\n\n增量更新：Session")
    if len(text) <= limit:
        return text
    return text[-limit:].lstrip()
