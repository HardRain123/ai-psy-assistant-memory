from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import APP_ENV
from app.db import check_db_health


router = APIRouter()


@router.get("/health")
def health():
    db = check_db_health()
    payload = {
        "status": "ok" if db["ok"] else "degraded",
        "service": "running",
        "app_env": APP_ENV,
        "database": db,
    }
    if not db["ok"]:
        return JSONResponse(status_code=503, content=payload)
    return payload
