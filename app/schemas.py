from typing import Optional

from pydantic import BaseModel, Field


class SaveSessionMessageRequest(BaseModel):
    user_id: str
    session_id: str
    role: str
    content: str
    turn_id: Optional[str] = None
    external_message_id: Optional[str] = None
    sync_status: str = "complete"
    dify_conversation_id: Optional[str] = None


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


class DifyTurnPrepRequest(BaseModel):
    user_id: str
    query: str
    auto_finalize_session: bool = False
    target_session_id: Optional[str] = None


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


class ScreeningSubmitRequest(BaseModel):
    user_id: str
    answers: list[int]
    session_id: Optional[str] = None


class ScreeningBatchItem(BaseModel):
    instrument: str
    answers: list[int]
    session_id: Optional[str] = None


class ScreeningBatchRequest(BaseModel):
    user_id: str
    screenings: list[ScreeningBatchItem]
    session_id: Optional[str] = None
    supplements: dict[str, list[int]] = Field(default_factory=dict)


class GenerateHandoffRequest(BaseModel):
    format: str = "markdown"
    regenerate: bool = False
    include_low_content: bool = False


class E2ETimeShiftRequest(BaseModel):
    days: int = 1


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    inviteCode: str


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str = ""


class PasswordResetConfirmRequest(BaseModel):
    token: str = ""
    new_password: str = ""


class EmailVerificationRequest(BaseModel):
    email: str = ""


class EmailVerificationConfirmRequest(BaseModel):
    token: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str = ""
    new_password: str = ""


class SessionTokenRequest(BaseModel):
    sessionToken: str = ""


class CreateInviteRequest(BaseModel):
    note: str = ""
    expires_at: Optional[str] = None


class RevokeInviteRequest(BaseModel):
    invite_id: int
