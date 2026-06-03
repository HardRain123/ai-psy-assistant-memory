from datetime import datetime

from app.config import SESSION_MINUTES


RISK_KEYWORDS = [
    "不想活了",
    "想死",
    "自杀",
    "活着没意义",
    "伤害自己",
    "伤害别人",
]


def now_iso() -> str:
    return datetime.now().isoformat()


def bool_text(value):
    return "true" if value else "false"


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def truncate_text(value: str, limit: int = 280) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def detect_risk_level(text: str) -> str:
    normalized = text or ""
    return "high" if any(keyword in normalized for keyword in RISK_KEYWORDS) else "none"


def highest_risk_level(*levels: str) -> str:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    highest = "none"
    for level in levels:
        if order.get(level or "none", 0) > order[highest]:
            highest = level
    return highest


def calc_stage(started_at: datetime):
    """
    Return elapsed minutes, remaining minutes, and a Dify-friendly session stage.
    """
    now = datetime.now()
    elapsed = (now - started_at).total_seconds() / 60
    remaining = SESSION_MINUTES - elapsed

    if elapsed < 5:
        stage = "trust"
    elif elapsed < 25:
        stage = "deep"
    elif elapsed < 40:
        stage = "reframe"
    elif elapsed < 48:
        stage = "action"
    elif elapsed < SESSION_MINUTES:
        stage = "ending"
    else:
        stage = "ended"

    return round(elapsed, 2), round(max(remaining, 0), 2), stage
