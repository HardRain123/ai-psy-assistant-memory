import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_DIFY_API_BASE = "https://api.dify.ai/v1"


@dataclass
class DifyChatResponse:
    answer: str
    conversation_id: str
    message_identifier: str
    raw: dict[str, Any]


class DifyClient:
    def __init__(
        self,
        api_key: str,
        api_base: str = DEFAULT_DIFY_API_BASE,
        timeout_seconds: int = 60,
        trust_env: bool = False,
        max_retries: int = 2,
    ):
        self._api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.trust_env = trust_env
        self.max_retries = max(max_retries, 0)

    @classmethod
    def from_env(cls):
        api_key = os.getenv("DIFY_API_KEY")
        if not api_key:
            raise RuntimeError("DIFY_API_KEY is required when RUN_DIFY_E2E=true")

        api_base = os.getenv("DIFY_API_BASE", DEFAULT_DIFY_API_BASE)
        try:
            timeout_seconds = int(os.getenv("DIFY_E2E_TIMEOUT_SECONDS", "60"))
        except ValueError:
            timeout_seconds = 60
        try:
            max_retries = int(os.getenv("DIFY_E2E_MAX_RETRIES", "2"))
        except ValueError:
            max_retries = 2

        return cls(
            api_key=api_key,
            api_base=api_base,
            timeout_seconds=timeout_seconds,
            trust_env=_bool_env("DIFY_E2E_TRUST_ENV"),
            max_retries=max_retries,
        )

    def chat(
        self,
        *,
        user_id: str,
        query: str,
        conversation_id: str = "",
        response_mode: str = "blocking",
    ) -> DifyChatResponse:
        url = f"{self.api_base}/chat-messages"
        payload = {
            "inputs": {"user_id": user_id},
            "query": query,
            "response_mode": response_mode,
            "conversation_id": conversation_id,
            "user": user_id,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        response = None
        last_error: httpx.HTTPError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds, trust_env=self.trust_env) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = _redact_response_text(exc.response.text)
                last_error = exc
                if attempt < self.max_retries and _is_transient_dify_status_error(status, body):
                    time.sleep(min(2**attempt, 8))
                    continue
                raise RuntimeError(f"Dify chat request failed status={status} body={body}") from exc
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise RuntimeError(
                        f"Dify blocking chat request timed out after {attempt + 1} attempt(s)"
                    ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise RuntimeError(
                        f"Dify chat request failed after {attempt + 1} attempt(s): "
                        f"{exc.__class__.__name__}"
                    ) from exc

            time.sleep(min(2**attempt, 8))

        if response is None:
            error_name = last_error.__class__.__name__ if last_error else "unknown"
            raise RuntimeError(f"Dify chat request failed: {error_name}")

        data = response.json()
        answer = str(data.get("answer") or "").strip()
        returned_conversation_id = str(data.get("conversation_id") or "").strip()
        message_identifier = str(data.get("message_id") or data.get("id") or "").strip()
        return DifyChatResponse(
            answer=answer,
            conversation_id=returned_conversation_id,
            message_identifier=message_identifier,
            raw=data,
        )


def _redact_response_text(text: str, limit: int = 500) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "..."
    api_key = os.getenv("DIFY_API_KEY")
    if api_key:
        cleaned = cleaned.replace(api_key, "[REDACTED]")
    return cleaned


def _is_transient_dify_status_error(status: int, body: str) -> bool:
    if status in {502, 503, 504}:
        return True

    transient_markers = (
        "502 Bad Gateway",
        "503 Service Unavailable",
        "504 Gateway Timeout",
        "PluginInvokeError",
        "Server Unavailable Error",
        "Connection aborted",
        "Connection reset by peer",
        "ConnectionResetError",
        "API request failed with status code 502",
        "API request failed with status code 503",
        "API request failed with status code 504",
    )
    return status == 400 and any(marker in body for marker in transient_markers)


def _bool_env(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}
