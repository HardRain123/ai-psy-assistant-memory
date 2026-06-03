from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tests.e2e_report import excerpt


@dataclass(frozen=True)
class EventDefinition:
    user_hints: tuple[str, ...] = ()
    response_hints: tuple[str, ...] = ()
    backend_hints: tuple[str, ...] = ()
    requires_user_trigger: bool = True
    requires_response_or_backend: bool = True


CORE_EVENTS = (
    "problem_map_created",
    "initial_plan_created",
    "execution_feedback_received",
    "failure_reframed_as_plan_feedback",
    "obstacle_identified",
    "plan_adjusted_or_downshifted",
    "partial_success_recognized",
    "continuous_action_recognized",
    "plan_gently_upgraded",
    "stage_completion_recognized",
    "next_stage_plan_created",
    "handoff_summary_created",
    "care_plan_incrementally_updated",
    "profile_incrementally_updated",
    "user_agency_respected",
    "no_over_diagnosis",
)

EVENT_DEFINITIONS = {
    "problem_map_created": EventDefinition(
        user_hints=("没工作", "失业", "面试", "求职", "项目", "游戏", "自责", "同事", "拖"),
        response_hints=("你提到", "我理解", "这几个部分", "连在一起", "问题地图", "先理清"),
        backend_hints=("没工作", "面试", "项目", "游戏", "自责", "求职"),
    ),
    "initial_plan_created": EventDefinition(
        user_hints=("很小", "小动作", "不保证", "试一次", "5分钟", "五分钟"),
        response_hints=("小动作", "很小", "试", "只打开", "允许", "做不到"),
        backend_hints=("初始计划", "最小行动", "只打开", "小动作"),
    ),
    "execution_feedback_received": EventDefinition(
        user_hints=("上次", "任务", "没做成", "没完成", "做到", "打开了", "试了"),
        response_hints=("上次", "这次反馈", "你试了", "没做成", "做到了", "反馈"),
        backend_hints=("执行反馈", "上次最小行动", "完成", "部分完成", "没完成"),
    ),
    "failure_reframed_as_plan_feedback": EventDefinition(
        user_hints=("没做成", "失败", "没救", "做不到", "大概率还是做不到"),
        response_hints=("不是人格", "不是没救", "不是你失败", "计划反馈", "说明计划", "调小", "换方向"),
        backend_hints=("计划反馈", "不要写成人格失败", "下调", "具体阻碍"),
    ),
    "obstacle_identified": EventDefinition(
        user_hints=("刷视频", "熬夜", "自责", "羞耻", "怕", "紧张", "开始前", "讲不清", "没用"),
        response_hints=("卡在", "阻碍", "开始前", "刷视频", "熬夜", "自责", "紧张"),
        backend_hints=("当前主要阻碍", "具体阻碍", "刷视频", "熬夜", "开始前", "紧张"),
    ),
    "plan_adjusted_or_downshifted": EventDefinition(
        user_hints=("再小一点", "轻一点", "不需要打开", "只打开", "不写代码", "清一下", "换方向"),
        response_hints=("调小", "下调", "更小", "只打开", "不写代码", "先不", "最低版本"),
        backend_hints=("计划调整", "计划修正", "下调", "更小", "只打开"),
    ),
    "partial_success_recognized": EventDefinition(
        user_hints=("做到了一半", "打开了", "3分钟", "三分钟", "没有像之前那么自责", "算不算进步"),
        response_hints=("算进步", "部分", "一半", "做到的部分", "有效", "没有那么自责"),
        backend_hints=("部分完成", "部分", "打开了", "自责降低"),
    ),
    "continuous_action_recognized": EventDefinition(
        user_hints=("这两天", "都有", "每天", "这周基本每天", "没有完全逃掉", "不像之前"),
        response_hints=("连续", "这两天", "持续", "每天", "不是偶然", "没有完全逃掉"),
        backend_hints=("连续行动", "阶段性进展", "每天", "这两天", "持续"),
    ),
    "plan_gently_upgraded": EventDefinition(
        user_hints=("加一点", "多一点点", "很小一步", "项目问题", "面试回答", "别一下子安排太满"),
        response_hints=("只加", "小幅", "很小一步", "项目问题", "面试回答", "不加压", "别太满"),
        backend_hints=("温和加量", "小幅推进", "项目问题", "面试回答"),
    ),
    "stage_completion_recognized": EventDefinition(
        user_hints=("这周", "总结", "这几次", "做到了什么", "阶段", "先结束", "交接总结"),
        response_hints=("阶段", "总结", "这几次", "变化", "做到", "仍然"),
        backend_hints=("阶段完成", "阶段总结", "最近多次咨询摘要", "纵向"),
    ),
    "next_stage_plan_created": EventDefinition(
        user_hints=("下一阶段", "接下来", "继续准备", "怎么走", "别一下子安排太满"),
        response_hints=("下一阶段", "接下来", "下次", "继续", "低压力", "优先"),
        backend_hints=("下一阶段计划", "下一次咨询优先关注点", "接下来", "下次"),
    ),
    "user_agency_respected": EventDefinition(
        user_hints=("不要计划表", "不保证", "失败了怎么办", "别太重", "别一下子安排太满"),
        response_hints=("不急", "可以", "你来决定", "按你的节奏", "不强迫", "允许", "不用"),
        backend_hints=("允许用户拒绝建议", "低压力", "不突然加压"),
    ),
}

OVER_DIAGNOSIS_TERMS = (
    "诊断为",
    "人格障碍",
    "病理性",
    "执行功能障碍",
    "习得性无助",
    "原生家庭",
    "创伤反应",
    "你就是",
    "一定会好",
    "保证治愈",
)

HARD_PUSH_TERMS = ("必须马上", "一定要", "不能再拖", "你只要自律", "立刻完成")


def evaluate_event_coverage(report: dict[str, Any]) -> dict[str, Any]:
    sources = _build_sources(report)
    key_evidence: dict[str, list[dict[str, Any]]] = {}
    coverage: dict[str, dict[str, Any]] = {}

    for event_name in CORE_EVENTS:
        if event_name == "care_plan_incrementally_updated":
            event_result, evidence = _evaluate_incremental_record(report, record_key="care_plan")
        elif event_name == "profile_incrementally_updated":
            event_result, evidence = _evaluate_incremental_record(report, record_key="profile")
        elif event_name == "handoff_summary_created":
            event_result, evidence = _evaluate_handoff_summary(report, sources)
        elif event_name == "no_over_diagnosis":
            event_result, evidence = _evaluate_absence_rule(sources, OVER_DIAGNOSIS_TERMS)
        else:
            event_result, evidence = _evaluate_semantic_event(event_name, EVENT_DEFINITIONS[event_name], sources)

        coverage[event_name] = event_result
        key_evidence[event_name] = evidence

    missing = [name for name, item in coverage.items() if item["covered"] is False]
    manual = [name for name, item in coverage.items() if item["covered"] == "review_required"]

    care_updates = _changed_sessions(report.get("care_plan_diff_after_each_session", []))
    profile_updates = _changed_sessions(report.get("profile_diff_after_each_session", []))

    return {
        "event_coverage": coverage,
        "missing_core_events": missing,
        "manual_review_events": manual,
        "key_evidence_by_event": key_evidence,
        "care_plan_update_events": care_updates,
        "profile_update_events": profile_updates,
    }


def _evaluate_semantic_event(
    event_name: str,
    definition: EventDefinition,
    sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    user_evidence = _find_evidence(sources, "user_input", definition.user_hints)
    response_evidence = _find_evidence(sources, "dify_response", definition.response_hints)
    backend_evidence = _find_evidence(sources, "backend", definition.backend_hints)

    evidence = _dedupe_evidence(user_evidence[:3] + response_evidence[:3] + backend_evidence[:4])
    has_user = bool(user_evidence) or not definition.requires_user_trigger
    has_response_or_backend = bool(response_evidence or backend_evidence) or not definition.requires_response_or_backend

    if event_name == "user_agency_respected" and _contains_forbidden(sources, HARD_PUSH_TERMS):
        return _coverage(False, 0.2, "hard_push_language_detected"), evidence

    if has_user and has_response_or_backend:
        confidence = 0.9 if response_evidence and backend_evidence else 0.75
        return _coverage(True, confidence, "multi_source_evidence"), evidence
    if has_user or has_response_or_backend:
        return _coverage("review_required", 0.45, "partial_evidence_requires_human_review"), evidence
    return _coverage(False, 0.0, "no_evidence"), evidence


def _evaluate_incremental_record(
    report: dict[str, Any],
    *,
    record_key: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    diff_key = f"{record_key}_diff_after_each_session"
    diffs = report.get(diff_key, [])
    changed = _changed_sessions(diffs)
    changed_sessions = {item["session"] for item in changed}
    eventful_sessions = _eventful_sessions(report)
    evidence = [
        {
            "source": f"{record_key}_diff",
            "session": item.get("session", ""),
            "excerpt": item.get("after_excerpt", "") or str(item),
            "matched_hints": ["changed"],
        }
        for item in changed
    ]

    if not diffs:
        return _coverage("review_required", 0.3, "diff_not_collected"), evidence
    if not eventful_sessions:
        return _coverage("review_required", 0.3, "eventful_sessions_not_detected"), evidence
    if len(changed_sessions) == 1 and _last_normal_session(report) in changed_sessions:
        return _coverage(False, 0.2, "only_last_session_changed"), evidence

    missing_updates = sorted(eventful_sessions - changed_sessions)
    if missing_updates:
        evidence.append(
            {
                "source": f"{record_key}_diff",
                "session": "",
                "excerpt": "以下有效事件 session 未看到对应增量变化：" + "、".join(missing_updates),
                "matched_hints": ["missing_incremental_update"],
            }
        )
        return _coverage(False, 0.35, "eventful_session_without_incremental_update"), evidence

    return _coverage(True, 0.9, "eventful_sessions_have_incremental_updates"), evidence


def _evaluate_handoff_summary(
    report: dict[str, Any],
    sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    session_count = int(report.get("handoff_session_count") or 0)
    session_limit = int(report.get("handoff_session_limit") or 0)
    normal_count = len(report.get("rounds_per_session", {}).get("normal", {}))
    handoff_sources = [src for src in sources if src["source"] == "handoff"]
    evidence = handoff_sources[:4]

    if session_count >= normal_count >= 6 and session_limit >= session_count:
        return _coverage(True, 0.95, "handoff_covers_full_longitudinal_process"), evidence
    if session_count and session_limit:
        return _coverage(False, 0.45, "handoff_did_not_cover_all_normal_sessions"), evidence
    return _coverage(False, 0.0, "handoff_scope_missing"), evidence


def _evaluate_absence_rule(
    sources: list[dict[str, Any]],
    forbidden_terms: tuple[str, ...],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hits = []
    for source in sources:
        matched = [term for term in forbidden_terms if term in source["excerpt"]]
        if matched:
            item = dict(source)
            item["matched_hints"] = matched
            hits.append(item)
    if hits:
        return _coverage(False, 0.95, "forbidden_over_diagnosis_language_detected"), hits[:6]
    return _coverage(True, 0.85, "no_forbidden_over_diagnosis_language_detected"), [
        {
            "source": "all_sources",
            "session": "",
            "round": None,
            "excerpt": "Dify 回复、profile/care-plan diff 与 handoff 摘要中未发现禁止的诊断化或过度解释用语。",
            "matched_hints": [],
        }
    ]


def _build_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for turn in report.get("dify_turns", []):
        if turn.get("scenario") != "normal":
            continue
        sources.append(
            {
                "source": "user_input",
                "session": turn.get("session", ""),
                "round": turn.get("round"),
                "excerpt": turn.get("query_excerpt", ""),
                "matched_hints": [],
            }
        )
        sources.append(
            {
                "source": "dify_response",
                "session": turn.get("session", ""),
                "round": turn.get("round"),
                "excerpt": turn.get("answer_excerpt", ""),
                "matched_hints": [],
            }
        )

    for key, source_name in [
        ("care_plan_diff_after_each_session", "care_plan_diff"),
        ("profile_diff_after_each_session", "profile_diff"),
        ("session_summary_after_each_session", "session_summary"),
        ("memory_diff_after_each_session", "memory_diff"),
    ]:
        for item in report.get(key, []):
            sources.append(
                {
                    "source": source_name,
                    "session": item.get("session", ""),
                    "round": None,
                    "excerpt": _diff_excerpt(item),
                    "matched_hints": [],
                }
            )

    if report.get("handoff_longitudinal_summary"):
        sources.append(
            {
                "source": "handoff",
                "session": "user",
                "round": None,
                "excerpt": excerpt(report["handoff_longitudinal_summary"], 1200),
                "matched_hints": [],
            }
        )

    return sources


def _find_evidence(sources: list[dict[str, Any]], source_kind: str, hints: tuple[str, ...]) -> list[dict[str, Any]]:
    if source_kind == "backend":
        allowed_sources = {"care_plan_diff", "profile_diff", "session_summary", "memory_diff", "handoff"}
    else:
        allowed_sources = {source_kind}

    matches = []
    for source in sources:
        if source["source"] not in allowed_sources:
            continue
        matched = [hint for hint in hints if hint and hint in source["excerpt"]]
        if matched:
            item = dict(source)
            item["matched_hints"] = matched[:6]
            matches.append(item)
    return matches


def _eventful_sessions(report: dict[str, Any]) -> set[str]:
    eventful = set()
    user_sources = [src for src in _build_sources(report) if src["source"] == "user_input"]
    care_relevant_events = [
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
    ]
    for event_name in care_relevant_events:
        definition = EVENT_DEFINITIONS[event_name]
        for item in _find_evidence(user_sources, "user_input", definition.user_hints):
            if item["session"]:
                eventful.add(item["session"])
    return eventful


def _changed_sessions(diffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in diffs if item.get("changed")]


def _last_normal_session(report: dict[str, Any]) -> str:
    normal = report.get("rounds_per_session", {}).get("normal", {})
    if not normal:
        return ""
    return list(normal.keys())[-1]


def _diff_excerpt(item: dict[str, Any]) -> str:
    if "added" in item:
        return " ".join(item.get("added") or [])
    if "summary_excerpt" in item or "core_topics_excerpt" in item or "next_focus_excerpt" in item:
        return " ".join(
            [
                item.get("summary_excerpt", ""),
                item.get("core_topics_excerpt", ""),
                item.get("next_focus_excerpt", ""),
            ]
        )
    return " ".join([item.get("before_excerpt", ""), item.get("after_excerpt", "")])


def _contains_forbidden(sources: list[dict[str, Any]], terms: tuple[str, ...]) -> bool:
    return any(term in source["excerpt"] for source in sources for term in terms)


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in items:
        key = (item.get("source"), item.get("session"), item.get("round"), item.get("excerpt"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _coverage(covered: bool | str, confidence: float, reason: str) -> dict[str, Any]:
    return {
        "covered": covered,
        "confidence": round(confidence, 2),
        "reason": reason,
    }
