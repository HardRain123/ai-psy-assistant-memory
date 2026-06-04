from dataclasses import dataclass

from app.utils import clean_text


GREETING_ONLY_TEXTS = {
    "你好",
    "您好",
    "在吗",
    "嗯",
    "好",
    "没有",
    "没",
    "随便",
    "继续",
    "hi",
    "hello",
}

CONCERN_KEYWORDS = {
    "压力",
    "焦虑",
    "烦",
    "烦躁",
    "难受",
    "痛苦",
    "失眠",
    "睡不着",
    "工作",
    "项目",
    "游戏",
    "关系",
    "家人",
    "伴侣",
    "求职",
    "赚钱",
    "自责",
    "拖延",
    "崩溃",
    "害怕",
    "紧张",
    "羞耻",
    "失败",
    "熬夜",
    "刷视频",
    "生气",
    "难过",
    "想死",
    "自杀",
    "伤害自己",
    "伤害别人",
}

STRONG_INTERPRETATION_TERMS = {
    "防御",
    "创伤",
    "逃避型人格",
    "测试咨询师",
    "完美主义",
    "习得性无助",
    "缺乏自我接纳",
    "逃离被评价和控制",
    "深层动机",
    "潜意识",
    "病理化",
    "依赖",
    "人格问题",
    "自我价值",
    "自我批判模式",
    "行动力不足模式",
    "弹性不足",
}


@dataclass
class SessionQuality:
    is_low_content: bool
    user_message_count: int
    user_char_count: int
    has_concern: bool
    reason: str


def normalize_for_quality(text: str) -> str:
    return clean_text(text).replace("，", "").replace("。", "").replace("！", "").replace("？", "")


def is_greeting_only(text: str) -> bool:
    normalized = normalize_for_quality(text).lower()
    return normalized in GREETING_ONLY_TEXTS


def has_specific_concern(text: str) -> bool:
    return any(keyword in (text or "") for keyword in CONCERN_KEYWORDS)


def evaluate_session_quality(messages: list) -> SessionQuality:
    user_texts = [clean_text(row[1]) for row in messages if row[0] == "user" and clean_text(row[1])]
    user_message_count = len(user_texts)
    user_char_count = sum(len(text) for text in user_texts)
    combined = "\n".join(user_texts)
    has_concern = has_specific_concern(combined)

    if user_message_count == 0:
        return SessionQuality(True, 0, 0, False, "no_user_message")
    if all(is_greeting_only(text) for text in user_texts):
        return SessionQuality(True, user_message_count, user_char_count, False, "greeting_only")
    if user_message_count < 2:
        return SessionQuality(True, user_message_count, user_char_count, has_concern, "too_few_user_messages")
    if user_char_count < 20:
        return SessionQuality(True, user_message_count, user_char_count, has_concern, "too_short_user_content")
    if not has_concern:
        return SessionQuality(True, user_message_count, user_char_count, False, "no_specific_concern")

    return SessionQuality(False, user_message_count, user_char_count, True, "formal_session")


def has_strong_interpretation(text: str) -> bool:
    return any(term in (text or "") for term in STRONG_INTERPRETATION_TERMS)


def should_persist_memory(content: str, session_quality: SessionQuality | None = None) -> tuple[bool, str]:
    text = clean_text(content)
    if not text:
        return False, "empty"
    if is_greeting_only(text):
        return False, "greeting_only"
    if "用户主要表达为：你好" in text or "主要表达为：你好" in text:
        return False, "meaningless_summary"
    if has_strong_interpretation(text):
        return False, "strong_interpretation"
    if session_quality and session_quality.is_low_content:
        return False, "low_content_session"
    if len(text) < 12 and not has_specific_concern(text):
        return False, "too_short"
    return True, "ok"


def build_quality_plan() -> dict:
    return {
        "psychological_line": [
            "稳定咨询关系，允许用户直接说“不想做这个建议”。",
            "减少自责，用用户自己的话描述困难，不急着分析人格原因。",
            "识别切换到游戏前的压力、卡住、疲劳或等待空档。",
            "用户烦躁或质疑时，先修复关系，再决定是否继续原议题。",
        ],
        "action_line": [
            "今天只要求一个 25 分钟项目块。",
            "第一次打开游戏前，记录自己刚才正在做什么。",
            "不要求戒游戏，不要求立刻达到 8 小时。",
            "如果卡住，先停 1 秒或数 5 下，再决定是否继续。",
        ],
        "metrics": [
            "今日有效项目时长。",
            "今日第一次打开游戏前的场景。",
            "今日游戏是否影响关键任务。",
            "今日自责程度 0-10。",
            "今日是否完成一个最小项目块。",
        ],
    }


def repair_relationship_prompt_rules() -> list[str]:
    return [
        "用户烦躁、骂人或质疑时，先暂停原议题。",
        "承认刚才互动可能让用户不舒服。",
        "简短说明会调整追问密度或表达方式。",
        "不要继续推进技巧或动作建议。",
        "只问一个关于互动方式的问题。",
    ]
