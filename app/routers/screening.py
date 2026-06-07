import logging

from fastapi import APIRouter, HTTPException, Query

from app.db import read_transaction, transaction
from app.errors import public_error
from app.schemas import ScreeningBatchRequest, ScreeningSubmitRequest
from app.services.screening import (
    get_current_snapshot,
    get_screening_history,
    instrument_config,
    save_screening_batch,
    save_screening_result,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/screening/config")
def get_screening_config():
    return instrument_config()


def _screening_bootstrap_payload(user_id: str):
    with read_transaction() as cur:
        snapshot = get_current_snapshot(cur, user_id)

    return {
        "user_id": user_id,
        "config": instrument_config(),
        "current": {
            "exists": bool(snapshot),
            "snapshot": snapshot,
        },
    }


@router.get("/screening/bootstrap")
def screening_bootstrap_query(user_id: str = Query(...)):
    try:
        return _screening_bootstrap_payload(user_id)
    except Exception:
        logger.exception("screening_bootstrap_failed user_id=%s", user_id)
        return public_error("screening_bootstrap_failed")


@router.get("/screening/bootstrap/{user_id}")
def screening_bootstrap(user_id: str):
    try:
        return _screening_bootstrap_payload(user_id)
    except Exception:
        logger.exception("screening_bootstrap_failed user_id=%s", user_id)
        return public_error("screening_bootstrap_failed")


@router.post("/screening/batch")
def submit_screening_batch(req: ScreeningBatchRequest):
    try:
        with transaction() as cur:
            result = save_screening_batch(
                cur,
                user_id=req.user_id,
                screenings=[
                    {
                        "instrument": item.instrument,
                        "answers": item.answers,
                        "session_id": item.session_id or req.session_id or "",
                    }
                    for item in req.screenings
                ],
                session_id=req.session_id or "",
                supplements=req.supplements,
            )
        logger.info(
            "screening_batch_saved user_id=%s instruments=%s stage=%s",
            req.user_id,
            ",".join(item["instrument"] for item in result["results"]),
            result["snapshot"].get("stage"),
        )
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=public_error(str(exc), "状态评估答案格式不正确。"),
        ) from exc
    except Exception:
        logger.exception("screening_batch_failed user_id=%s", req.user_id)
        return public_error("screening_batch_failed")


@router.post("/screening/{instrument}")
def submit_screening(instrument: str, req: ScreeningSubmitRequest):
    try:
        with transaction() as cur:
            result = save_screening_result(
                cur,
                user_id=req.user_id,
                instrument=instrument,
                answers=req.answers,
                session_id=req.session_id or "",
            )
        logger.info(
            "screening_saved user_id=%s instrument=%s severity=%s risk_level=%s",
            req.user_id,
            result["instrument"],
            result["severity"],
            result["risk_level"],
        )
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=public_error(str(exc), "状态评估答案格式不正确。"),
        ) from exc
    except Exception:
        logger.exception("screening_submit_failed user_id=%s instrument=%s", req.user_id, instrument)
        return public_error("screening_submit_failed")


@router.get("/screening/current/{user_id}")
def current_screening_snapshot(user_id: str):
    try:
        with read_transaction() as cur:
            snapshot = get_current_snapshot(cur, user_id)

        if not snapshot:
            return {
                "exists": False,
                "user_id": user_id,
                "snapshot": None,
                "message": "screening snapshot not found",
            }

        return {"exists": True, "user_id": user_id, "snapshot": snapshot}
    except Exception:
        logger.exception("screening_current_failed user_id=%s", user_id)
        return public_error("screening_current_failed")


@router.get("/screening/history/{user_id}")
def screening_history(user_id: str, limit: int = Query(default=20, ge=1, le=100)):
    try:
        with read_transaction() as cur:
            history = get_screening_history(cur, user_id, limit=limit)
        return {"user_id": user_id, "history": history}
    except Exception:
        logger.exception("screening_history_failed user_id=%s", user_id)
        return public_error("screening_history_failed")
