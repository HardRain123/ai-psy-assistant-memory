import hmac
import os

from fastapi import Header, HTTPException

from app.config import BACKEND_SHARED_TOKEN


def _backend_token() -> str:
    return os.getenv("BACKEND_SHARED_TOKEN", BACKEND_SHARED_TOKEN)


def require_backend_token(x_backend_token: str | None = Header(default=None)):
    expected = _backend_token()
    if not expected:
        raise HTTPException(status_code=503, detail="backend token is not configured")

    if not x_backend_token or not hmac.compare_digest(x_backend_token, expected):
        raise HTTPException(status_code=401, detail="backend token required")

    return True
