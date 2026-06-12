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
    source: str = "keyword"
    source_risk_level: Optional[str] = None
    final_risk_level: Optional[str] = None
    immediate_action_required: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    risk_reason: str = ""
    source_evidence: dict = Field(default_factory=dict)


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
    policyVersion: str = ""
    adultConfirmed: bool = False
    aiServiceConsent: bool = False
    sensitiveDataConsent: bool = False
    conversationStorageConsent: bool = False
    longTermMemoryConsent: bool = False
    humanSafetyReviewConsent: bool = False


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


class SafetyIncidentCreateRequest(BaseModel):
    user_id: str
    session_id: str = ""
    source: str
    source_risk_level: str
    final_risk_level: str
    immediate_action_required: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    reason: str = ""
    source_evidence: dict = Field(default_factory=dict)
    trigger_message_id: Optional[int] = None


class SafetyIncidentActionRequest(BaseModel):
    action: str
    note: str = ""
    follow_up_at: Optional[str] = None


class SensitiveTranscriptAccessRequest(BaseModel):
    reason: str


class ConsentUpdateRequest(BaseModel):
    policyVersion: str
    adultConfirmed: bool
    aiServiceConsent: bool
    sensitiveDataConsent: bool
    conversationStorageConsent: bool
    longTermMemoryConsent: bool
    humanSafetyReviewConsent: bool


class AccountDeletionRequest(BaseModel):
    confirm_text: str = ""


class AccountDeletionCancelRequest(BaseModel):
    request_id: str
    cancellation_token: str


class ComplaintCreateRequest(BaseModel):
    category: str = "service"
    content: str


class LaunchControlUpdateRequest(BaseModel):
    paused: bool
    note: str


class SafetyOperatorRoleRequest(BaseModel):
    user_id: str
    role: str
    enabled: bool = True
