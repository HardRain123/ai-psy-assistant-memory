import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


logger = logging.getLogger(__name__)

DEFAULT_DIFY_API_BASE = "https://api.dify.ai/v1"
AUTO_FINALIZE_MARKER = "[SYSTEM_AUTO_FINALIZE_SESSION]"
AUTO_FINALIZE_QUERY = (
    AUTO_FINALIZE_MARKER
    + " "
    + "\u672c\u6b21\u6b63\u5f0f\u54a8\u8be2\u5df2\u8de8\u5929\uff0c"
    + "\u8bf7\u8fdb\u5165\u7ed3\u675f\u6d41\u7a0b\uff0c"
    + "\u751f\u6210\u5e76\u4fdd\u5b58\u672c\u6b21\u54a8\u8be2\u603b\u7ed3\u3002"
)


@dataclass
class DifyAutoFinalizeResult:
    attempted: bool
    success: bool
    reason: str
    conversation_id: str = ""
    message_id: str = ""
    answer: str = ""


def is_auto_finalize_query(query: str | None) -> bool:
    return AUTO_FINALIZE_MARKER in (query or "")


def auto_finalize_target_from_query(query: str | None) -> str:
    match = re.search(r"\btarget_session_id=([A-Za-z0-9_.:-]+)", query or "")
    return match.group(1) if match else ""


def request_dify_auto_finalize(
    *,
    user_id: str,
    session_id: str,
    conversation_id: str,
) -> DifyAutoFinalizeResult:
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        return DifyAutoFinalizeResult(attempted=False, success=False, reason="conversation_id_missing")

    api_key = (os.getenv("DIFY_API_KEY") or "").strip()
    if not api_key:
        return DifyAutoFinalizeResult(attempted=False, success=False, reason="dify_api_key_missing")

    api_base = (
        os.getenv("DIFY_API_URL")
        or os.getenv("DIFY_API_BASE")
        or DEFAULT_DIFY_API_BASE
    ).rstrip("/")
    try:
        timeout_seconds = int(os.getenv("DIFY_AUTO_FINALIZE_TIMEOUT_SECONDS", "60"))
    except ValueError:
        timeout_seconds = 60

    payload = {
        "inputs": {
            "user_id": user_id,
            "auto_finalize_session": True,
            "target_session_id": session_id,
        },
        "query": f"{AUTO_FINALIZE_QUERY} target_session_id={session_id}",
        "response_mode": "blocking",
        "conversation_id": conversation_id,
        "user": user_id,
    }

    try:
        with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
            response = client.post(
                f"{api_base}/chat-messages",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        data: dict[str, Any] = response.json()
    except Exception as exc:
        logger.warning(
            "dify_auto_finalize_failed user_id=%s session_id=%s error=%s",
            user_id,
            session_id,
            exc.__class__.__name__,
        )
        return DifyAutoFinalizeResult(
            attempted=True,
            success=False,
            reason=f"dify_request_failed:{exc.__class__.__name__}",
        )

    return DifyAutoFinalizeResult(
        attempted=True,
        success=True,
        reason="dify_request_completed",
        conversation_id=str(data.get("conversation_id") or "").strip(),
        message_id=str(data.get("message_id") or data.get("id") or "").strip(),
        answer=str(data.get("answer") or "").strip(),
    )
