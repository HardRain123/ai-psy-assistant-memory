from fastapi import APIRouter

from app.config import APP_ENV
from app.db import check_db_health


router = APIRouter()


@router.get("/health")
def health():
    db = check_db_health()
    return {
        "status": "ok" if db["ok"] else "degraded",
        "service": "running",
        "app_env": APP_ENV,
        "database": db,
    }
