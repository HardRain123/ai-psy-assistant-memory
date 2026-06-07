from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.utils import now_iso


DISCLAIMER = "本结果仅为症状筛查提示，不是医疗诊断，不能替代精神科医生或心理咨询师评估。"


@dataclass(frozen=True)
class ScreeningOption:
    value: int
    label: str


@dataclass(frozen=True)
class ScreeningInstrument:
    code: str
    title: str
    subtitle: str
    score_type: str
    min_value: int
    max_value: int
    options: tuple[ScreeningOption, ...]
    questions: tuple[str, ...]


STANDARD_OPTIONS = (
    ScreeningOption(0, "完全没有"),
    ScreeningOption(1, "有几天"),
    ScreeningOption(2, "一半以上天数"),
    ScreeningOption(3, "几乎每天"),
)

ASRM_OPTIONS = (
    ScreeningOption(0, "没有"),
    ScreeningOption(1, "轻微"),
    ScreeningOption(2, "中等"),
    ScreeningOption(3, "明显"),
    ScreeningOption(4, "非常明显"),
)

DES_OPTIONS = tuple(ScreeningOption(value, f"{value}%") for value in range(0, 101, 10))


def _supplement_options(labels: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    return tuple({"value": index, "label": label} for index, label in enumerate(labels))


SUPPLEMENTAL_MODULES: tuple[dict[str, Any], ...] = (
    {
        "code": "stage",
        "title": "阶段补充模块",
        "subtitle": "用于判断当前风险阶段，不用于诊断。",
        "trigger": {"type": "after_core_complete"},
        "questions": (
            {
                "code": "duration",
                "prompt": "这组困扰大致持续了多久？",
                "options": _supplement_options(("少于 2 周", "2-4 周", "1-3 个月", "超过 3 个月")),
            },
            {
                "code": "recent_change",
                "prompt": "最近一周整体变化更接近哪一种？",
                "options": _supplement_options(("明显缓解", "基本稳定", "有所加重", "明显加重")),
            },
            {
                "code": "sleep_change",
                "prompt": "睡眠相对平时的变化如何？",
                "options": _supplement_options(("无明显变化", "轻度变差", "明显紊乱", "显著减少且精力不降")),
            },
            {
                "code": "functioning",
                "prompt": "这些状态对日常功能的影响程度如何？",
                "options": _supplement_options(("几乎不影响", "轻度影响", "明显影响", "难以维持日常安排")),
            },
            {
                "code": "work_social",
                "prompt": "工作/学习、社交或家庭互动受影响的范围如何？",
                "options": _supplement_options(("无明显影响", "单一方面受影响", "两个方面受影响", "多方面明显受影响")),
            },
            {
                "code": "recurrent",
                "prompt": "过去是否出现过类似阶段性波动？",
                "options": _supplement_options(("首次或不确定", "偶尔出现过", "反复出现过", "近期反复且间隔变短")),
            },
        ),
    },
    {
        "code": "safety",
        "title": "安全补充模块",
        "subtitle": "当 PHQ-9 第 9 题阳性时出现，用于判断当前安全风险。",
        "trigger": {"type": "phq9_item_9_positive"},
        "questions": (
            {
                "code": "current_thought",
                "prompt": "现在或今天是否仍有死亡或伤害自己的想法？",
                "options": _supplement_options(("没有", "偶尔闪过", "反复出现", "强烈或难以摆脱")),
            },
            {
                "code": "plan",
                "prompt": "是否有具体方式、时间或计划？",
                "options": _supplement_options(("没有", "模糊想过", "已有具体方式", "近期可能实施")),
            },
            {
                "code": "means",
                "prompt": "是否已经接触到或准备了可能伤害自己的工具/条件？",
                "options": _supplement_options(("没有", "可能接触到", "已经准备或难以远离")),
            },
            {
                "code": "support",
                "prompt": "此刻身边支持和安全承诺如何？",
                "options": _supplement_options(("有人陪伴且愿意求助", "能联系支持但尚未联系", "独处或难以承诺安全")),
            },
        ),
    },
    {
        "code": "mania",
        "title": "躁狂补充模块",
        "subtitle": "当 ASRM 升高时出现，关注睡眠减少、冲动行为和现实检验。",
        "trigger": {"type": "asrm_score_at_least", "score": 6},
        "questions": (
            {
                "code": "reduced_sleep_need",
                "prompt": "睡眠明显减少但仍觉得精力充沛的程度如何？",
                "options": _supplement_options(("没有", "轻微", "明显", "连续数天明显")),
            },
            {
                "code": "impulsive_behavior",
                "prompt": "消费、冒险、性冲动或重大决定是否明显增加？",
                "options": _supplement_options(("没有", "轻微", "明显", "可能造成严重后果")),
            },
            {
                "code": "activity_increase",
                "prompt": "活动量、社交、工作/学习推进是否异常增加？",
                "options": _supplement_options(("没有", "轻微", "明显", "难以停下来")),
            },
            {
                "code": "reality_testing",
                "prompt": "是否出现不寻常的确信、被害感、特殊能力感或感知异常？",
                "options": _supplement_options(("没有", "轻微", "明显", "明显影响现实判断")),
            },
        ),
    },
    {
        "code": "anxiety",
        "title": "焦虑细分补充模块",
        "subtitle": "当 GAD-7 中高分时出现，区分担忧、惊恐、回避和躯体紧张。",
        "trigger": {"type": "gad7_score_at_least", "score": 10},
        "questions": (
            {
                "code": "generalized_worry",
                "prompt": "对多类事情持续担忧、难以控制的程度如何？",
                "options": _supplement_options(("没有", "轻微", "明显", "几乎持续存在")),
            },
            {
                "code": "panic_like",
                "prompt": "是否出现突发强烈恐惧、心慌、窒息感或失控感？",
                "options": _supplement_options(("没有", "偶尔", "多次出现", "频繁且害怕再次发作")),
            },
            {
                "code": "avoidance",
                "prompt": "是否因为焦虑而回避场景、人际或任务？",
                "options": _supplement_options(("没有", "轻微", "明显", "严重限制生活")),
            },
            {
                "code": "somatic_tension",
                "prompt": "肌肉紧张、胃肠不适、出汗、颤抖等躯体紧张如何？",
                "options": _supplement_options(("没有", "轻微", "明显", "持续且影响功能")),
            },
        ),
    },
    {
        "code": "dissociation",
        "title": "解离补充模块",
        "subtitle": "当 DES-II 升高时出现，关注现实感、记忆断片和功能影响。",
        "trigger": {"type": "des2_score_at_least", "score": 30},
        "questions": (
            {
                "code": "derealization",
                "prompt": "现实感变弱、世界像隔着一层或像梦境的程度如何？",
                "options": _supplement_options(("没有", "轻微", "明显", "频繁或强烈")),
            },
            {
                "code": "amnesia",
                "prompt": "记忆断片、想不起自己做过什么的情况如何？",
                "options": _supplement_options(("没有", "轻微", "明显", "造成现实后果")),
            },
            {
                "code": "identity_experience",
                "prompt": "身份感、身体归属感或“像不同的人”的体验如何？",
                "options": _supplement_options(("没有", "轻微", "明显", "强烈且困扰")),
            },
            {
                "code": "functional_impact",
                "prompt": "这些体验对学习、工作、人际或安全感的影响如何？",
                "options": _supplement_options(("几乎不影响", "轻度影响", "明显影响", "难以维持日常")),
            },
        ),
    },
)
SUPPLEMENTAL_MODULE_BY_CODE = {item["code"]: item for item in SUPPLEMENTAL_MODULES}


INSTRUMENTS: dict[str, ScreeningInstrument] = {
    "phq9": ScreeningInstrument(
        code="phq9",
        title="PHQ-9 抑郁症状筛查",
        subtitle="回顾过去两周，这些情况困扰你的频率。",
        score_type="sum",
        min_value=0,
        max_value=3,
        options=STANDARD_OPTIONS,
        questions=(
            "做事时提不起劲或没有兴趣",
            "感到心情低落、沮丧或绝望",
            "入睡困难、睡不安稳或睡眠过多",
            "感觉疲倦或没有活力",
            "食欲不振或吃太多",
            "觉得自己很糟，或觉得自己失败、让自己或家人失望",
            "对事物专注困难，例如阅读或看电视",
            "动作或说话速度慢到别人可能注意到，或相反地坐立不安、动来动去",
            "想到自己不如死了好，或以某种方式伤害自己",
        ),
    ),
    "gad7": ScreeningInstrument(
        code="gad7",
        title="GAD-7 焦虑症状筛查",
        subtitle="回顾过去两周，这些情况困扰你的频率。",
        score_type="sum",
        min_value=0,
        max_value=3,
        options=STANDARD_OPTIONS,
        questions=(
            "感到紧张、焦虑或坐立不安",
            "无法停止或控制担忧",
            "对各种事情担忧过多",
            "很难放松下来",
            "坐立不安，以至于难以安静坐着",
            "变得容易烦恼或易怒",
            "感到好像会有可怕的事情发生",
        ),
    ),
    "asrm": ScreeningInstrument(
        code="asrm",
        title="ASRM 躁狂/轻躁狂风险筛查",
        subtitle="回顾过去一周，你相对平时的状态变化。",
        score_type="sum",
        min_value=0,
        max_value=4,
        options=ASRM_OPTIONS,
        questions=(
            "情绪比平时更高涨、兴奋或自信",
            "自我感觉比平时更好，或觉得自己能力特别强",
            "睡眠需求减少，但仍觉得精力充沛",
            "说话比平时更多、更快，或别人难以插话",
            "活动量、社交、工作、学习或冒险行为明显增加",
        ),
    ),
    "des2": ScreeningInstrument(
        code="des2",
        title="DES-II 解离症状筛查",
        subtitle="估计这些体验在你生活中出现的比例，0% 表示从不，100% 表示总是。",
        score_type="average",
        min_value=0,
        max_value=100,
        options=DES_OPTIONS,
        questions=(
            "发现自己到了某个地方，却不知道自己怎么到那里的",
            "听别人说你做过某些事，但你自己不记得",
            "发现自己在不熟悉的地方，却不知道为什么在那里",
            "发现自己穿着不记得穿上的衣服",
            "发现新物品在自己东西里，却不记得买过",
            "有人叫你另一个名字，或坚持说以前见过你",
            "感觉自己好像站在旁边看自己行动",
            "有人告诉你，有时你认不出朋友或家人",
            "对生活中重要事件没有记忆，例如毕业、婚礼或旅行",
            "被指责说谎，但你认为自己没有说谎",
            "照镜子时认不出自己",
            "感觉周围的人、物体或世界不真实",
            "感觉身体不属于自己",
            "清楚记得过去事件，仿佛正在重新经历",
            "不确定某件事是真发生过，还是只是梦到过",
            "在熟悉地方感到陌生",
            "看电影或电视时太投入，以至于不知道周围发生什么",
            "幻想或白日梦像真实发生一样",
            "有时能忽略疼痛",
            "盯着空处发呆，意识不到时间流逝",
            "独处时大声和自己说话",
            "在不同情境中表现得像不同的人",
            "有时能轻松完成平时困难的事",
            "不确定自己是否做过某事，还是只想过要做",
            "发现自己做了某事，却不记得做过",
            "发现有自己写下的东西、画作或笔记，但不记得写过或画过",
            "听到脑中有声音评论或指示自己做事",
            "感觉看着世界像隔着雾、梦或屏幕",
        ),
    ),
}

ALIASES = {
    "des-ii": "des2",
    "des_ii": "des2",
    "des": "des2",
}


def normalize_instrument(value: str) -> str:
    key = (value or "").strip().lower()
    return ALIASES.get(key, key)


def instrument_config() -> dict[str, Any]:
    return {
        "disclaimer": DISCLAIMER,
        "instruments": [serialize_instrument(item) for item in INSTRUMENTS.values()],
        "supplemental_modules": [serialize_supplemental_module(item) for item in SUPPLEMENTAL_MODULES],
    }


def serialize_instrument(item: ScreeningInstrument) -> dict[str, Any]:
    return {
        "code": item.code,
        "title": item.title,
        "subtitle": item.subtitle,
        "score_type": item.score_type,
        "min_value": item.min_value,
        "max_value": item.max_value,
        "options": [{"value": option.value, "label": option.label} for option in item.options],
        "questions": list(item.questions),
    }


def serialize_supplemental_module(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item["code"],
        "title": item["title"],
        "subtitle": item["subtitle"],
        "trigger": dict(item["trigger"]),
        "questions": [
            {
                "code": question["code"],
                "prompt": question["prompt"],
                "options": [dict(option) for option in question["options"]],
            }
            for question in item["questions"]
        ],
    }


def score_screening(instrument: str, answers: list[int]) -> dict[str, Any]:
    code = normalize_instrument(instrument)
    if code not in INSTRUMENTS:
        raise ValueError("unsupported_instrument")

    definition = INSTRUMENTS[code]
    if len(answers) != len(definition.questions):
        raise ValueError("answer_count_mismatch")

    for answer in answers:
        if not isinstance(answer, int):
            raise ValueError("answer_must_be_integer")
        if answer < definition.min_value or answer > definition.max_value:
            raise ValueError("answer_out_of_range")

    if definition.score_type == "average":
        score = round(sum(answers) / len(answers), 2)
    else:
        score = sum(answers)

    severity, label, recommendation = _classify(code, score)
    risk_flags = _risk_flags(code, score, answers)
    risk_level = _risk_level_for_flags(risk_flags)

    return {
        "instrument": code,
        "title": definition.title,
        "score": score,
        "severity": severity,
        "label": label,
        "recommendation": recommendation,
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "is_diagnosis": False,
        "disclaimer": DISCLAIMER,
    }


def save_screening_result(
    cur,
    *,
    user_id: str,
    instrument: str,
    answers: list[int],
    session_id: str = "",
) -> dict[str, Any]:
    batch = save_screening_batch(
        cur,
        user_id=user_id,
        screenings=[{"instrument": instrument, "answers": answers, "session_id": session_id}],
        session_id=session_id,
    )
    result = batch["results"][0]
    return {
        "success": True,
        "screening_id": result["screening_id"],
        "snapshot": batch["snapshot"],
        **result,
    }


def save_screening_batch(
    cur,
    *,
    user_id: str,
    screenings: list[dict[str, Any]],
    session_id: str = "",
    supplements: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    if not screenings:
        raise ValueError("screening_batch_empty")

    _ensure_user(cur, user_id)
    normalized_supplements = _validate_supplements(supplements or {})
    results = []

    for item in screenings:
        instrument = str(item.get("instrument") or "")
        answers = item.get("answers")
        item_session_id = str(item.get("session_id") or session_id or "")
        if not isinstance(answers, list):
            raise ValueError("answers_must_be_list")
        results.append(
            _insert_screening_result(
                cur,
                user_id=user_id,
                instrument=instrument,
                answers=answers,
                session_id=item_session_id,
            )
        )

    snapshot = rebuild_mental_state_snapshot(cur, user_id, supplements=normalized_supplements)
    return {
        "success": True,
        "user_id": user_id,
        "results": results,
        "results_by_instrument": {item["instrument"]: item for item in results},
        "snapshot": snapshot,
    }


def _insert_screening_result(
    cur,
    *,
    user_id: str,
    instrument: str,
    answers: list[int],
    session_id: str = "",
) -> dict[str, Any]:
    result = score_screening(instrument, answers)
    code = result["instrument"]
    now = now_iso()

    cur.execute(
        """
        INSERT INTO clinical_screenings (
            user_id, session_id, instrument, score, severity, label,
            answers_json, risk_level, risk_flags, is_diagnosis, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            session_id or "",
            code,
            float(result["score"]),
            result["severity"],
            result["label"],
            json.dumps(answers, ensure_ascii=False),
            result["risk_level"],
            json.dumps(result["risk_flags"], ensure_ascii=False),
            0,
            now,
        ),
    )
    cur.execute(
        """
        SELECT id
        FROM clinical_screenings
        WHERE user_id = ? AND instrument = ? AND created_at = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, code, now),
    )
    row = cur.fetchone()
    return {
        **result,
        "screening_id": row[0] if row else None,
        "created_at": now,
    }


def rebuild_mental_state_snapshot(
    cur,
    user_id: str,
    supplements: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    latest = latest_screening_results(cur, user_id)
    previous_snapshot = get_current_snapshot(cur, user_id)
    normalized_supplements = _validate_supplements(supplements or {})
    domains = build_snapshot_domains(latest, normalized_supplements)
    stage = determine_risk_stage(latest, domains)
    confidence = determine_snapshot_confidence(latest, normalized_supplements)
    trend = determine_snapshot_trend(latest, previous_snapshot)
    summary = build_snapshot_summary(latest, stage=stage, trend=trend)
    safety_level = highest_screening_risk([item["risk_level"] for item in latest.values()])
    safety_level = highest_screening_risk([safety_level, domains.get("safety", {}).get("risk_level", "none")])
    flags = []
    for item in latest.values():
        for flag in item.get("risk_flags", []):
            if flag not in flags:
                flags.append(flag)
    for flag in domains.get("safety", {}).get("flags", []):
        if flag not in flags:
            flags.append(flag)

    now = now_iso()
    payload = {
        "user_id": user_id,
        "screenings": latest,
        "domains": domains,
        "stage": stage,
        "confidence": confidence,
        "trend": trend,
        "safety": {
            "risk_level": safety_level,
            "flags": flags,
        },
        "summary": summary,
        "is_diagnosis": False,
        "disclaimer": DISCLAIMER,
        "updated_at": now,
    }

    cur.execute(
        """
        INSERT INTO mental_state_snapshots (
            user_id, summary, snapshot_json, safety_level, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            summary,
            json.dumps(payload, ensure_ascii=False),
            safety_level,
            now,
            now,
        ),
    )
    return payload


def latest_screening_results(cur, user_id: str) -> dict[str, dict[str, Any]]:
    cur.execute(
        """
        SELECT id, instrument, score, severity, label, risk_level, risk_flags, created_at
        FROM clinical_screenings
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 120
        """,
        (user_id,),
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in cur.fetchall():
        screening_id, instrument, score, severity, label, risk_level, risk_flags, created_at = row
        if instrument in latest:
            continue
        latest[instrument] = {
            "screening_id": screening_id,
            "instrument": instrument,
            "score": _display_score(instrument, score),
            "severity": severity,
            "label": label,
            "risk_level": risk_level or "none",
            "risk_flags": _loads_list(risk_flags),
            "created_at": created_at,
            "is_diagnosis": False,
        }
        if len(latest) == len(INSTRUMENTS):
            break
    return latest


def get_current_snapshot(cur, user_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT summary, snapshot_json, safety_level, updated_at
        FROM mental_state_snapshots
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    summary, snapshot_json, safety_level, updated_at = row
    try:
        payload = json.loads(snapshot_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("summary", summary)
    if not isinstance(payload.get("screenings"), dict):
        payload["screenings"] = {}
    if not isinstance(payload.get("safety"), dict):
        payload["safety"] = {"risk_level": safety_level or "none", "flags": []}
    else:
        payload["safety"].setdefault("risk_level", safety_level or "none")
        if not isinstance(payload["safety"].get("flags"), list):
            payload["safety"]["flags"] = []
    payload.setdefault("updated_at", updated_at)
    payload["is_diagnosis"] = False
    payload["disclaimer"] = DISCLAIMER
    return payload


def get_screening_history(cur, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    cur.execute(
        """
        SELECT id, instrument, score, severity, label, risk_level, risk_flags, created_at
        FROM clinical_screenings
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return [
        {
            "screening_id": row[0],
            "instrument": row[1],
            "score": _display_score(row[1], row[2]),
            "severity": row[3],
            "label": row[4],
            "risk_level": row[5] or "none",
            "risk_flags": _loads_list(row[6]),
            "created_at": row[7],
            "is_diagnosis": False,
        }
        for row in cur.fetchall()
    ]


def build_snapshot_domains(
    latest: dict[str, dict[str, Any]],
    supplements: dict[str, list[int]],
) -> dict[str, Any]:
    stage_answers = _supplement_answer_map(supplements, "stage")
    safety_answers = _supplement_answer_map(supplements, "safety")
    mania_answers = _supplement_answer_map(supplements, "mania")
    anxiety_answers = _supplement_answer_map(supplements, "anxiety")
    dissociation_answers = _supplement_answer_map(supplements, "dissociation")

    domains = {
        "depression": _screening_domain(latest, "phq9"),
        "anxiety": _screening_domain(latest, "gad7"),
        "mania_hypomania": _screening_domain(latest, "asrm"),
        "dissociation": _screening_domain(latest, "des2"),
        "functioning": _functioning_domain(stage_answers),
        "safety": _safety_domain(latest, safety_answers),
    }

    domains["depression"].update(
        {
            "duration": _supplement_answer_label("stage", "duration", stage_answers.get("duration")),
            "recent_change": _supplement_answer_label(
                "stage", "recent_change", stage_answers.get("recent_change")
            ),
            "sleep_change": _supplement_answer_label("stage", "sleep_change", stage_answers.get("sleep_change")),
            "recurrent": _supplement_answer_label("stage", "recurrent", stage_answers.get("recurrent")),
        }
    )
    domains["anxiety"].update(
        {
            "subtypes": _flagged_supplement_features(
                "anxiety",
                anxiety_answers,
                {
                    "generalized_worry": "广泛担忧",
                    "panic_like": "惊恐样体验",
                    "avoidance": "回避",
                    "somatic_tension": "躯体紧张",
                },
            )
        }
    )
    domains["mania_hypomania"].update(
        {
            "risk_features": _flagged_supplement_features(
                "mania",
                mania_answers,
                {
                    "reduced_sleep_need": "睡眠需求减少",
                    "impulsive_behavior": "冲动/冒险行为",
                    "activity_increase": "活动增加",
                    "reality_testing": "现实检验受损",
                },
            )
        }
    )
    domains["dissociation"].update(
        {
            "risk_features": _flagged_supplement_features(
                "dissociation",
                dissociation_answers,
                {
                    "derealization": "现实感减弱",
                    "amnesia": "记忆断片",
                    "identity_experience": "身份体验异常",
                    "functional_impact": "功能影响",
                },
            )
        }
    )
    return domains


def determine_risk_stage(latest: dict[str, dict[str, Any]], domains: dict[str, Any]) -> str:
    safety = domains.get("safety", {})
    if safety.get("current_danger") == "urgent_attention":
        return "urgent_attention"

    domain_ranks = [
        _level_rank(domain.get("level"))
        for name, domain in domains.items()
        if name != "safety" and isinstance(domain, dict)
    ]
    functioning_rank = _level_rank((domains.get("functioning") or {}).get("level"))
    safety_rank = _risk_rank(safety.get("risk_level"))

    if safety.get("current_danger") == "high_attention" or safety_rank >= 3:
        return "high_attention"
    if any(rank >= 3 for rank in domain_ranks):
        return "high_attention"
    if functioning_rank >= 3 and any(rank >= 2 for rank in domain_ranks):
        return "high_attention"
    if any(rank >= 2 for rank in domain_ranks) or functioning_rank >= 2 or safety_rank >= 2:
        return "moderate"
    if any(rank >= 1 for rank in domain_ranks) or functioning_rank >= 1 or safety_rank >= 1:
        return "mild"
    if latest:
        return "stable"
    return "stable"


def determine_snapshot_confidence(
    latest: dict[str, dict[str, Any]],
    supplements: dict[str, list[int]],
) -> str:
    core_count = len(latest)
    expected = expected_supplement_modules(latest)
    completed = set(supplements.keys())
    missing = expected - completed

    if "safety" in missing:
        return "low"
    if core_count == len(INSTRUMENTS) and not missing:
        return "high"
    if core_count >= 3:
        return "medium"
    return "low"


def determine_snapshot_trend(
    latest: dict[str, dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
) -> str:
    previous_screenings = (previous_snapshot or {}).get("screenings") or {}
    if not latest or not previous_screenings:
        return "unknown"

    diffs = []
    for code, item in latest.items():
        previous = previous_screenings.get(code)
        if not previous:
            continue
        diffs.append(_screening_rank(code, item.get("severity")) - _screening_rank(code, previous.get("severity")))

    if not diffs:
        return "unknown"

    total = sum(diffs)
    if total >= 2:
        return "worsening"
    if total <= -2:
        return "improving"
    return "stable"


def expected_supplement_modules(latest: dict[str, dict[str, Any]]) -> set[str]:
    expected: set[str] = set()
    if len(latest) == len(INSTRUMENTS):
        expected.add("stage")
    phq9 = latest.get("phq9") or {}
    if "self_harm_item_positive" in phq9.get("risk_flags", []):
        expected.add("safety")
    asrm = latest.get("asrm") or {}
    if float(asrm.get("score") or 0) >= 6:
        expected.add("mania")
    gad7 = latest.get("gad7") or {}
    if float(gad7.get("score") or 0) >= 10:
        expected.add("anxiety")
    des2 = latest.get("des2") or {}
    if float(des2.get("score") or 0) >= 30:
        expected.add("dissociation")
    return expected


def _validate_supplements(supplements: dict[str, list[int]]) -> dict[str, list[int]]:
    normalized: dict[str, list[int]] = {}
    for code, answers in supplements.items():
        module = SUPPLEMENTAL_MODULE_BY_CODE.get(code)
        if not module:
            raise ValueError("unsupported_supplement")
        if not isinstance(answers, list):
            raise ValueError("supplement_answers_must_be_list")
        questions = module["questions"]
        if len(answers) != len(questions):
            raise ValueError("supplement_answer_count_mismatch")

        values = []
        for index, answer in enumerate(answers):
            if not isinstance(answer, int):
                raise ValueError("supplement_answer_must_be_integer")
            allowed = {option["value"] for option in questions[index]["options"]}
            if answer not in allowed:
                raise ValueError("supplement_answer_out_of_range")
            values.append(answer)
        normalized[code] = values
    return normalized


def _supplement_answer_map(supplements: dict[str, list[int]], module_code: str) -> dict[str, int]:
    module = SUPPLEMENTAL_MODULE_BY_CODE[module_code]
    answers = supplements.get(module_code)
    if not answers:
        return {}
    return {question["code"]: answers[index] for index, question in enumerate(module["questions"])}


def _supplement_answer_label(module_code: str, question_code: str, value: int | None) -> str | None:
    if value is None:
        return None
    module = SUPPLEMENTAL_MODULE_BY_CODE[module_code]
    for question in module["questions"]:
        if question["code"] != question_code:
            continue
        for option in question["options"]:
            if option["value"] == value:
                return option["label"]
    return None


def _flagged_supplement_features(
    module_code: str,
    answers: dict[str, int],
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    features = []
    for code, label in labels.items():
        value = answers.get(code)
        if value is None or value <= 0:
            continue
        features.append(
            {
                "code": code,
                "label": label,
                "level": _level_from_rank(value),
                "answer_label": _supplement_answer_label(module_code, code, value),
            }
        )
    return features


def _screening_domain(latest: dict[str, dict[str, Any]], code: str) -> dict[str, Any]:
    item = latest.get(code)
    if not item:
        return {"available": False, "level": "unknown"}
    rank = _screening_rank(code, item.get("severity"))
    return {
        "available": True,
        "score": item.get("score"),
        "severity": item.get("severity"),
        "label": item.get("label"),
        "risk_level": item.get("risk_level", "none"),
        "risk_flags": item.get("risk_flags", []),
        "level": _level_from_rank(rank),
    }


def _functioning_domain(stage_answers: dict[str, int]) -> dict[str, Any]:
    functioning = stage_answers.get("functioning")
    work_social = stage_answers.get("work_social")
    rank = max([value for value in (functioning, work_social) if value is not None], default=0)
    return {
        "available": bool(stage_answers),
        "level": _level_from_rank(rank),
        "daily_functioning": _supplement_answer_label("stage", "functioning", functioning),
        "work_school_social": _supplement_answer_label("stage", "work_social", work_social),
    }


def _safety_domain(latest: dict[str, dict[str, Any]], safety_answers: dict[str, int]) -> dict[str, Any]:
    phq9 = latest.get("phq9") or {}
    flags = list(phq9.get("risk_flags", []))
    phq_self_harm = "self_harm_item_positive" in flags
    risk_level = "high" if phq_self_harm and not safety_answers else "none"
    current_danger = "high_attention" if phq_self_harm and not safety_answers else "stable"

    current_thought = safety_answers.get("current_thought", 0)
    plan = safety_answers.get("plan", 0)
    means = safety_answers.get("means", 0)
    support = safety_answers.get("support", 0)

    if safety_answers:
        if phq_self_harm and "self_harm_item_positive" not in flags:
            flags.append("self_harm_item_positive")
        if current_thought >= 3 or plan >= 2 or means >= 2 or support >= 2:
            risk_level = "high"
            current_danger = "urgent_attention"
            flags.append("current_safety_urgent")
        elif current_thought >= 2 or plan >= 1 or means >= 1:
            risk_level = "high"
            current_danger = "high_attention"
            flags.append("current_safety_high_attention")
        elif current_thought >= 1 or phq_self_harm:
            risk_level = "medium"
            current_danger = "moderate"
            flags.append("recent_self_harm_thoughts_without_current_plan")
        else:
            risk_level = "none"
            current_danger = "stable"

    deduped_flags = []
    for flag in flags:
        if flag not in deduped_flags:
            deduped_flags.append(flag)

    return {
        "available": bool(latest.get("phq9")),
        "supplement_completed": bool(safety_answers),
        "risk_level": risk_level,
        "current_danger": current_danger,
        "flags": deduped_flags,
        "current_thought": _supplement_answer_label("safety", "current_thought", safety_answers.get("current_thought")),
        "plan": _supplement_answer_label("safety", "plan", safety_answers.get("plan")),
        "means": _supplement_answer_label("safety", "means", safety_answers.get("means")),
        "support": _supplement_answer_label("safety", "support", safety_answers.get("support")),
    }


def _screening_rank(code: str, severity: str | None) -> int:
    if code in {"phq9", "gad7"}:
        return {
            "minimal": 0,
            "mild": 1,
            "moderate": 2,
            "moderately_severe": 3,
            "severe": 3,
        }.get(severity or "", 0)
    if code == "asrm":
        return {"not_elevated": 0, "elevated": 2, "high": 3}.get(severity or "", 0)
    if code == "des2":
        return {"not_elevated": 0, "elevated": 2}.get(severity or "", 0)
    return 0


def _level_from_rank(rank: int) -> str:
    if rank >= 3:
        return "high"
    if rank == 2:
        return "moderate"
    if rank == 1:
        return "mild"
    return "stable"


def _level_rank(level: str | None) -> int:
    return {"stable": 0, "none": 0, "minimal": 0, "mild": 1, "moderate": 2, "elevated": 2, "high": 3}.get(
        level or "stable", 0
    )


def _risk_rank(level: str | None) -> int:
    return {"none": 0, "low": 1, "medium": 2, "high": 3}.get(level or "none", 0)


def format_snapshot_for_context(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return "暂无状态筛查记录。"
    screenings = snapshot.get("screenings") or {}
    if not screenings:
        return "暂无状态筛查记录。"

    lines = [
        f"- 当前风险阶段：{risk_stage_label(snapshot.get('stage'))}；"
        f"置信度：{confidence_label(snapshot.get('confidence'))}；"
        f"趋势：{trend_label(snapshot.get('trend'))}。"
    ]
    for code in ("phq9", "gad7", "asrm", "des2"):
        item = screenings.get(code)
        if not item:
            continue
        lines.append(f"- {instrument_short_label(code)}：{item['label']}，分数 {item['score']}，非诊断")

    safety = snapshot.get("safety") or {}
    risk_level = safety.get("risk_level") or "none"
    if risk_level != "none":
        lines.append(f"- 安全提示：{risk_level}，需优先关注风险信号；不包含原始答题内容。")

    return "\n".join(lines) if lines else "暂无状态筛查记录。"


def build_snapshot_summary(
    latest: dict[str, dict[str, Any]],
    *,
    stage: str = "stable",
    trend: str = "unknown",
) -> str:
    if not latest:
        return "暂无状态筛查记录。"

    parts = []
    for code in ("phq9", "gad7", "asrm", "des2"):
        item = latest.get(code)
        if item:
            parts.append(f"{instrument_short_label(code)}：{item['label']}")

    return (
        "；".join(parts)
        + f"。当前风险阶段：{risk_stage_label(stage)}；趋势：{trend_label(trend)}。结果仅为筛查提示，非医疗诊断。"
    )


def risk_stage_label(stage: str | None) -> str:
    labels = {
        "stable": "稳定/未见明显风险",
        "mild": "轻度关注",
        "moderate": "中度关注",
        "high_attention": "高关注",
        "urgent_attention": "紧急关注",
    }
    return labels.get(stage or "stable", "稳定/未见明显风险")


def confidence_label(confidence: str | None) -> str:
    labels = {"low": "低", "medium": "中", "high": "高"}
    return labels.get(confidence or "low", "低")


def trend_label(trend: str | None) -> str:
    labels = {
        "improving": "改善",
        "stable": "稳定",
        "worsening": "加重",
        "unknown": "暂无足够历史",
    }
    return labels.get(trend or "unknown", "暂无足够历史")


def instrument_short_label(code: str) -> str:
    labels = {
        "phq9": "PHQ-9",
        "gad7": "GAD-7",
        "asrm": "ASRM",
        "des2": "DES-II",
    }
    return labels.get(code, code.upper())


def highest_screening_risk(levels: list[str]) -> str:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    highest = "none"
    for level in levels:
        key = level or "none"
        if order.get(key, 0) > order[highest]:
            highest = key
    return highest


def _classify(code: str, score: float) -> tuple[str, str, str]:
    if code == "phq9":
        if score <= 4:
            return "minimal", "最小或无明显抑郁症状风险", "可继续观察当前状态。"
        if score <= 9:
            return "mild", "轻度抑郁症状风险", "建议关注睡眠、活动量和压力来源。"
        if score <= 14:
            return "moderate", "中度抑郁症状风险", "建议考虑寻求专业评估或支持。"
        if score <= 19:
            return "moderately_severe", "中重度抑郁症状风险", "建议尽快联系专业人员进一步评估。"
        return "severe", "重度抑郁症状风险", "建议尽快寻求专业帮助；若有自伤想法，请立即联系紧急支持。"

    if code == "gad7":
        if score <= 4:
            return "minimal", "最小或无明显焦虑症状风险", "可继续观察当前状态。"
        if score <= 9:
            return "mild", "轻度焦虑症状风险", "建议关注担忧触发点和身体紧张信号。"
        if score <= 14:
            return "moderate", "中度焦虑症状风险", "建议考虑寻求专业评估或支持。"
        return "severe", "重度焦虑症状风险", "建议尽快联系专业人员进一步评估。"

    if code == "asrm":
        if score >= 12:
            return "high", "躁狂/轻躁狂症状风险明显升高", "建议尽快寻求专业评估，尤其关注睡眠减少和冲动行为。"
        if score >= 6:
            return "elevated", "躁狂/轻躁狂症状风险升高", "建议继续观察，并考虑进一步专业评估。"
        return "not_elevated", "未见明显躁狂/轻躁狂风险升高", "可继续观察睡眠、精力和冲动行为变化。"

    if code == "des2":
        if score >= 30:
            return "elevated", "解离症状明显升高", "建议寻求专业评估，进一步理解记忆断片、失真感或身份体验。"
        return "not_elevated", "未见明显解离症状升高", "可继续观察压力下的失真感、记忆断片或抽离体验。"

    raise ValueError("unsupported_instrument")


def _risk_flags(code: str, score: float, answers: list[int]) -> list[str]:
    flags: list[str] = []
    if code == "phq9" and len(answers) >= 9 and answers[8] > 0:
        flags.append("self_harm_item_positive")
    if code == "asrm":
        if score >= 6:
            flags.append("mania_hypomania_elevated")
        if score >= 12:
            flags.append("mania_hypomania_high")
    if code == "des2" and score >= 30:
        flags.append("dissociation_elevated")
    return flags


def _risk_level_for_flags(flags: list[str]) -> str:
    if "self_harm_item_positive" in flags:
        return "high"
    if "mania_hypomania_high" in flags:
        return "medium"
    if flags:
        return "low"
    return "none"


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _display_score(instrument: str, score: float) -> int | float:
    if instrument == "des2":
        return round(float(score), 2)
    return int(score)


def _ensure_user(cur, user_id: str):
    now = now_iso()
    cur.execute(
        """
        INSERT INTO users (user_id, created_at, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET updated_at = ?
        """,
        (user_id, now, now, now),
    )
