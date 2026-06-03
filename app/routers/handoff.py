import logging

from fastapi import APIRouter, Query, Response

from app.db import transaction
from app.schemas import GenerateHandoffRequest
from app.services.handoff import (
    DEFAULT_USER_HANDOFF_SESSION_LIMIT,
    generate_handoff_document,
    get_handoff_document,
    list_handoff_documents_for_session,
    list_handoff_documents_for_user,
    render_user_handoff_document,
)


router = APIRouter()
logger = logging.getLogger(__name__)


def _export_response(document: dict, filename_prefix: str = "handoff"):
    content = document["content"]
    if document["format"] == "json":
        import json

        content = json.dumps(content, ensure_ascii=False, indent=2)
        media_type = "application/json; charset=utf-8"
    else:
        media_type = "text/markdown; charset=utf-8"

    filename = f"{filename_prefix}-{document['session_id']}.{document['format']}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/handoff/generate/{session_id}")
def generate_handoff(session_id: str, req: GenerateHandoffRequest = GenerateHandoffRequest()):
    try:
        with transaction() as cur:
            document = generate_handoff_document(
                cur,
                session_id,
                document_format=req.format,
                regenerate=req.regenerate,
                include_low_content=req.include_low_content,
                generated_by="system",
            )

        logger.info(
            "handoff_document_generated session_id=%s document_id=%s format=%s regenerate=%s",
            session_id,
            document.get("document_id"),
            req.format,
            req.regenerate,
        )
        return document

    except Exception as exc:
        logger.exception("generate_handoff_failed session_id=%s", session_id)
        return {"success": False, "error": "generate_handoff_failed", "message": str(exc)}


@router.get("/handoff/{document_id}")
def read_handoff(document_id: str):
    try:
        with transaction() as cur:
            document = get_handoff_document(cur, document_id)

        if not document:
            return {"success": False, "message": "handoff document not found"}
        return document

    except Exception as exc:
        logger.exception("read_handoff_failed document_id=%s", document_id)
        return {"success": False, "error": "read_handoff_failed", "message": str(exc)}


@router.get("/handoff/session/{session_id}")
def read_handoff_for_session(session_id: str):
    try:
        with transaction() as cur:
            documents = list_handoff_documents_for_session(cur, session_id)

        return {"session_id": session_id, "documents": documents}

    except Exception as exc:
        logger.exception("read_handoff_for_session_failed session_id=%s", session_id)
        return {"success": False, "error": "read_handoff_for_session_failed", "message": str(exc)}


@router.get("/handoff/user/{user_id}")
def read_handoff_for_user(
    user_id: str,
    format: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        with transaction() as cur:
            documents = list_handoff_documents_for_user(
                cur,
                user_id=user_id,
                document_format=format,
                limit=limit,
            )

        return {"user_id": user_id, "documents": documents}

    except Exception as exc:
        logger.exception("read_handoff_for_user_failed user_id=%s", user_id)
        return {"success": False, "error": "read_handoff_for_user_failed", "message": str(exc)}


@router.get("/handoff/export/user/{user_id}")
def export_latest_handoff_for_user(
    user_id: str,
    format: str | None = Query(default=None),
    session_limit: int = Query(default=DEFAULT_USER_HANDOFF_SESSION_LIMIT, ge=1, le=100),
):
    try:
        with transaction() as cur:
            document_format = (format or "markdown").lower()
            document = render_user_handoff_document(
                cur,
                user_id=user_id,
                document_format=document_format,
                session_limit=session_limit,
            )

        return _export_response(document, filename_prefix=f"handoff-{user_id}")

    except Exception as exc:
        logger.exception("export_handoff_for_user_failed user_id=%s", user_id)
        return {"success": False, "error": "export_handoff_for_user_failed", "message": str(exc)}


@router.get("/handoff/export/{document_id}")
def export_handoff(document_id: str):
    try:
        with transaction() as cur:
            document = get_handoff_document(cur, document_id)

        if not document:
            return {"success": False, "message": "handoff document not found"}

        return _export_response(document)

    except Exception as exc:
        logger.exception("export_handoff_failed document_id=%s", document_id)
        return {"success": False, "error": "export_handoff_failed", "message": str(exc)}
