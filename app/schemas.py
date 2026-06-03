from typing import Optional

from pydantic import BaseModel


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
    risk_level: str = "none"


class FinalizeSessionRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None


class SaveMemoryRequest(BaseModel):
    user_id: str
    memory: str
    session_id: Optional[str] = None
    memory_type: str = "general"
    importance: int = 1
    source_type: str = "manual"
    evidence: str = ""
    confidence: str = "medium"
    is_hypothesis: bool = False
    should_persist: bool = True


class GenerateHandoffRequest(BaseModel):
    format: str = "markdown"
    regenerate: bool = False
    include_low_content: bool = False


class E2ETimeShiftRequest(BaseModel):
    days: int = 1
