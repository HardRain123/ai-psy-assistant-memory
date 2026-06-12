import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta

import httpx

from app.config import (
    ACCOUNT_DELETION_GRACE_DAYS,
    BACKUP_DELETION_MAX_ATTEMPTS,
    BACKUP_DELETION_RETRY_SECONDS,
    BACKUP_DELETION_WEBHOOK_URL,
    BACKUP_RETENTION_DAYS,
)
from app.services.admin import export_user_data
from app.services.auth import AuthError, hash_email_identifier, hash_secret
from app.utils import now_iso


logger = logging.getLogger(__name__)

CURRENT_POLICY_VERSION = "2026-06-12.1"
REQUIRED_CONSENTS = {
    "adult_confirmation": "仅限年满 18 岁用户",
    "ai_service": "AI 服务授权",
    "sensitive_mental_health_data": "心理健康敏感信息处理授权",
    "conversation_storage": "对话保存授权",
    "long_term_memory": "长期记忆授权",
    "human_safety_review": "人工安全复核授权",
}
CONSENT_FIELD_MAP = {
    "adult_confirmation": "adultConfirmed",
    "ai_service": "aiServiceConsent",
    "sensitive_mental_health_data": "sensitiveDataConsent",
    "conversation_storage": "conversationStorageConsent",
    "long_term_memory": "longTermMemoryConsent",
    "human_safety_review": "humanSafetyReviewConsent",
}
DELETION_CONFIRM_TEXT = "删除我的账号"


def bootstrap_policy_versions(cur) -> None:
    now = now_iso()
    for policy_key, description in REQUIRED_CONSENTS.items():
        content_hash = hash_secret(
            f"{CURRENT_POLICY_VERSION}:{policy_key}:{description}",
            "policy-content",
        )
        cur.execute(
            """
            INSERT INTO policy_versions (
                policy_key, version, content_hash, effective_at, active, created_at
            )
            SELECT ?, ?, ?, ?, 1, ?
            WHERE NOT EXISTS (
                SELECT 1
                FROM policy_versions
                WHERE policy_key = ? AND version = ?
            )
            """,
            (
                policy_key,
                CURRENT_POLICY_VERSION,
                content_hash,
                now,
                now,
                policy_key,
                CURRENT_POLICY_VERSION,
            ),
        )


def consent_values_from_request(req) -> dict[str, bool]:
    return {
        consent_key: bool(getattr(req, field_name, False))
        for consent_key, field_name in CONSENT_FIELD_MAP.items()
    }


def validate_required_consents(policy_version: str, values: dict[str, bool]) -> None:
    if policy_version != CURRENT_POLICY_VERSION:
        raise AuthError("policy_version_outdated", status_code=400)
    missing = [key for key in REQUIRED_CONSENTS if not values.get(key)]
    if missing:
        raise AuthError("required_consents_missing", status_code=400)


def record_compliance_audit(
    cur,
    *,
    action: str,
    actor_user_id: str | None,
    target_user_id: str | None,
    resource_id: str = "",
    details: dict | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO compliance_audit_logs (
            action, actor_user_id, target_user_id, resource_id, details_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            action[:80],
            actor_user_id,
            target_user_id,
            resource_id[:160],
            json.dumps(details or {}, ensure_ascii=False),
            now_iso(),
        ),
    )


def record_user_consents(
    cur,
    *,
    user_id: str,
    policy_version: str,
    values: dict[str, bool],
    source: str,
    ip_hash: str = "",
    user_agent: str = "",
) -> dict:
    validate_required_consents(policy_version, values)
    now = now_iso()
    for consent_key in REQUIRED_CONSENTS:
        cur.execute(
            """
            INSERT INTO user_consents (
                user_id, consent_key, policy_version, granted, source,
                ip_hash, user_agent, granted_at, revoked_at
            )
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, NULL)
            """,
            (
                user_id,
                consent_key,
                policy_version,
                source[:40],
                ip_hash[:128],
                user_agent[:300],
                now,
            ),
        )
    record_compliance_audit(
        cur,
        action="consents_granted",
        actor_user_id=user_id,
        target_user_id=user_id,
        details={"policy_version": policy_version, "consent_keys": list(REQUIRED_CONSENTS)},
    )
    return {
        "policy_version": policy_version,
        "complete": True,
        "granted_at": now,
        "consents": {key: True for key in REQUIRED_CONSENTS},
    }


def get_user_consents(cur, user_id: str) -> dict:
    cur.execute(
        """
        SELECT consent_key, policy_version, granted, granted_at, revoked_at
        FROM user_consents
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    )
    latest = {}
    for consent_key, version, granted, granted_at, revoked_at in cur.fetchall():
        if consent_key in latest:
            continue
        latest[consent_key] = {
            "granted": bool(granted) and not revoked_at,
            "policy_version": version,
            "granted_at": granted_at,
            "revoked_at": revoked_at,
        }
    complete = all(
        latest.get(key, {}).get("granted")
        and latest.get(key, {}).get("policy_version") == CURRENT_POLICY_VERSION
        for key in REQUIRED_CONSENTS
    )
    return {
        "current_policy_version": CURRENT_POLICY_VERSION,
        "required": [
            {"key": key, "label": label, **latest.get(key, {"granted": False})}
            for key, label in REQUIRED_CONSENTS.items()
        ],
        "complete": complete,
        "phone_contacts_enabled": False,
        "coverage_notice": "工作日 09:00–18:00（中国时间）提供人工安全值守，不是 7×24 小时危机服务。",
    }


def export_account_data(cur, user_id: str) -> dict:
    payload = export_user_data(cur, user_id)
    payload["consents"] = get_user_consents(cur, user_id)

    cur.execute(
        """
        SELECT id, instrument, score, severity, label, risk_level, risk_flags, created_at
        FROM clinical_screenings
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (user_id,),
    )
    payload["clinical_screenings"] = [
        {
            "screening_id": row[0],
            "instrument": row[1],
            "score": row[2],
            "severity": row[3],
            "label": row[4],
            "risk_level": row[5],
            "risk_flags": json.loads(row[6] or "[]"),
            "created_at": row[7],
        }
        for row in cur.fetchall()
    ]
    cur.execute(
        """
        SELECT id, summary, snapshot_json, safety_level, created_at, updated_at
        FROM mental_state_snapshots
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (user_id,),
    )
    payload["mental_state_snapshots"] = [
        {
            "snapshot_id": row[0],
            "summary": row[1],
            "snapshot": json.loads(row[2] or "{}"),
            "safety_level": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }
        for row in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT incident_id, status, source, source_risk_level, final_risk_level,
               immediate_action_required, risk_flags, reason, source_evidence,
               alert_status, created_at, updated_at
        FROM safety_incidents
        WHERE user_id = ?
        ORDER BY created_at ASC
        """,
        (user_id,),
    )
    payload["safety_incidents"] = [
        {
            "incident_id": row[0],
            "status": row[1],
            "source": row[2],
            "source_risk_level": row[3],
            "final_risk_level": row[4],
            "immediate_action_required": bool(row[5]),
            "risk_flags": json.loads(row[6] or "[]"),
            "reason": row[7] or "",
            "source_evidence": json.loads(row[8] or "{}"),
            "alert_status": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }
        for row in cur.fetchall()
    ]
    incident_ids = [item["incident_id"] for item in payload["safety_incidents"]]
    payload["safety_incident_events"] = []
    for incident_id in incident_ids:
        cur.execute(
            """
            SELECT event_type, actor_user_id, from_status, to_status,
                   note, metadata_json, created_at
            FROM safety_incident_events
            WHERE incident_id = ?
            ORDER BY id ASC
            """,
            (incident_id,),
        )
        payload["safety_incident_events"].extend(
            {
                "incident_id": incident_id,
                "event_type": row[0],
                "actor_user_id": row[1],
                "from_status": row[2],
                "to_status": row[3],
                "note": row[4] or "",
                "metadata": json.loads(row[5] or "{}"),
                "created_at": row[6],
            }
            for row in cur.fetchall()
        )
    cur.execute(
        """
        SELECT evaluation_id, incident_id, session_id, source,
               source_risk_level, final_risk_level, immediate_action_required,
               risk_flags, reason, source_evidence, created_at
        FROM safety_risk_evaluations
        WHERE user_id = ?
        ORDER BY created_at ASC
        """,
        (user_id,),
    )
    payload["safety_risk_evaluations"] = [
        {
            "evaluation_id": row[0],
            "incident_id": row[1],
            "session_id": row[2] or "",
            "source": row[3],
            "source_risk_level": row[4],
            "final_risk_level": row[5],
            "immediate_action_required": bool(row[6]),
            "risk_flags": json.loads(row[7] or "[]"),
            "reason": row[8] or "",
            "source_evidence": json.loads(row[9] or "{}"),
            "created_at": row[10],
        }
        for row in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT complaint_id, category, content, status, created_at, updated_at
        FROM complaints
        WHERE user_id = ?
        ORDER BY created_at ASC
        """,
        (user_id,),
    )
    payload["complaints"] = [
        {
            "complaint_id": row[0],
            "category": row[1],
            "content": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }
        for row in cur.fetchall()
    ]
    record_compliance_audit(
        cur,
        action="account_export",
        actor_user_id=user_id,
        target_user_id=user_id,
        details={"format": "json"},
    )
    return payload


def request_account_deletion(cur, *, user_id: str, confirm_text: str) -> dict:
    if (confirm_text or "").strip() != DELETION_CONFIRM_TEXT:
        raise ValueError("deletion_confirmation_required")
    cur.execute(
        """
        SELECT request_id
        FROM data_deletion_requests
        WHERE user_id = ? AND status = 'pending'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    if cur.fetchone():
        raise ValueError("deletion_request_already_pending")

    cur.execute("SELECT disabled_at FROM users WHERE user_id = ? LIMIT 1", (user_id,))
    user_row = cur.fetchone()
    if not user_row:
        raise LookupError("user_not_found")

    now_dt = datetime.now()
    requested_at = now_dt.isoformat()
    scheduled_for = (
        now_dt + timedelta(days=max(int(ACCOUNT_DELETION_GRACE_DAYS or 7), 1))
    ).isoformat()
    backup_delete_by = (
        now_dt + timedelta(days=max(int(BACKUP_RETENTION_DAYS or 30), 1))
    ).isoformat()
    request_id = f"delete_{uuid.uuid4().hex}"
    cancellation_token = secrets.token_urlsafe(40)
    cancellation_token_hash = hash_secret(cancellation_token, "deletion-cancel")
    user_id_hash = hash_secret(user_id, "deleted-user")
    cur.execute(
        """
        INSERT INTO data_deletion_requests (
            request_id, user_id, user_id_hash, status, cancellation_token_hash,
            previous_disabled_at, requested_at, scheduled_for, backup_delete_by,
            backup_status, created_at, updated_at
        )
        VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            request_id,
            user_id,
            user_id_hash,
            cancellation_token_hash,
            user_row[0],
            requested_at,
            scheduled_for,
            backup_delete_by,
            requested_at,
            requested_at,
        ),
    )
    cur.execute(
        """
        UPDATE users
        SET disabled_at = COALESCE(disabled_at, ?), updated_at = ?
        WHERE user_id = ?
        """,
        (requested_at, requested_at, user_id),
    )
    cur.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE user_id = ? AND revoked_at IS NULL
        """,
        (requested_at, user_id),
    )
    record_compliance_audit(
        cur,
        action="account_deletion_requested",
        actor_user_id=user_id,
        target_user_id=user_id,
        resource_id=request_id,
        details={"scheduled_for": scheduled_for, "backup_delete_by": backup_delete_by},
    )
    return {
        "request_id": request_id,
        "status": "pending",
        "requested_at": requested_at,
        "scheduled_for": scheduled_for,
        "backup_delete_by": backup_delete_by,
        "cancellation_token": cancellation_token,
        "account_frozen": True,
    }


def _get_verified_deletion_request(cur, request_id: str, cancellation_token: str):
    token_hash = hash_secret(cancellation_token or "", "deletion-cancel")
    cur.execute(
        """
        SELECT request_id, user_id, status, requested_at, scheduled_for,
               cancelled_at, completed_at, backup_delete_by, backup_status,
               certificate_id, last_error, previous_disabled_at,
               backup_attempt_count, backup_last_attempt_at, backup_last_error
        FROM data_deletion_requests
        WHERE request_id = ? AND cancellation_token_hash = ?
        LIMIT 1
        """,
        (request_id, token_hash),
    )
    row = cur.fetchone()
    if not row:
        raise AuthError("invalid_deletion_token", status_code=401)
    return row


def deletion_request_status(cur, *, request_id: str, cancellation_token: str) -> dict:
    row = _get_verified_deletion_request(cur, request_id, cancellation_token)
    return {
        "request_id": row[0],
        "status": row[2],
        "requested_at": row[3],
        "scheduled_for": row[4],
        "cancelled_at": row[5],
        "completed_at": row[6],
        "backup_delete_by": row[7],
        "backup_status": row[8],
        "certificate_id": row[9],
        "last_error": row[10],
        "backup_attempt_count": row[12] or 0,
        "backup_last_attempt_at": row[13],
        "backup_last_error": row[14],
    }


def cancel_account_deletion(cur, *, request_id: str, cancellation_token: str) -> dict:
    row = _get_verified_deletion_request(cur, request_id, cancellation_token)
    if row[2] != "pending":
        raise ValueError("deletion_request_not_cancellable")
    now = now_iso()
    user_id = row[1]
    cur.execute(
        """
        UPDATE data_deletion_requests
        SET status = 'cancelled', cancelled_at = ?, cancellation_token_hash = NULL, updated_at = ?
        WHERE request_id = ? AND status = 'pending'
        """,
        (now, now, request_id),
    )
    if user_id:
        cur.execute(
            """
            UPDATE users
            SET disabled_at = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (row[11], now, user_id),
        )
    record_compliance_audit(
        cur,
        action="account_deletion_cancelled",
        actor_user_id=user_id,
        target_user_id=user_id,
        resource_id=request_id,
    )
    return {"request_id": request_id, "status": "cancelled", "cancelled_at": now}


def create_complaint(cur, *, user_id: str, category: str, content: str) -> dict:
    normalized_content = (content or "").strip()
    if len(normalized_content) < 10:
        raise ValueError("complaint_too_short")
    if len(normalized_content) > 5000:
        raise ValueError("complaint_too_long")
    normalized_category = (category or "service").strip().lower()
    if normalized_category not in {"service", "privacy", "safety", "content", "other"}:
        normalized_category = "other"
    complaint_id = f"complaint_{uuid.uuid4().hex}"
    now = now_iso()
    cur.execute(
        """
        INSERT INTO complaints (
            complaint_id, user_id, category, content, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'submitted', ?, ?)
        """,
        (complaint_id, user_id, normalized_category, normalized_content, now, now),
    )
    record_compliance_audit(
        cur,
        action="complaint_submitted",
        actor_user_id=user_id,
        target_user_id=user_id,
        resource_id=complaint_id,
        details={"category": normalized_category},
    )
    return {
        "complaint_id": complaint_id,
        "category": normalized_category,
        "status": "submitted",
        "created_at": now,
    }


def _delete_where_user(cur, table: str, user_id: str) -> int:
    cur.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    return max(cur.rowcount, 0)


def _purge_user(cur, request_row) -> dict:
    request_id, user_id, user_id_hash, backup_delete_by = request_row
    cur.execute("SELECT email FROM users WHERE user_id = ? LIMIT 1", (user_id,))
    user_row = cur.fetchone()
    email = user_row[0] if user_row else ""
    counts = {}

    cur.execute("SELECT incident_id FROM safety_incidents WHERE user_id = ?", (user_id,))
    incident_ids = [row[0] for row in cur.fetchall()]
    for incident_id in incident_ids:
        cur.execute("DELETE FROM safety_incident_events WHERE incident_id = ?", (incident_id,))
        counts["safety_incident_events"] = counts.get("safety_incident_events", 0) + max(cur.rowcount, 0)

    tables = (
        "session_messages",
        "session_summaries",
        "memories",
        "user_profiles",
        "care_plans",
        "handoff_documents",
        "session_task_history",
        "session_task",
        "clinical_screenings",
        "mental_state_snapshots",
        "safety_incidents",
        "safety_risk_evaluations",
        "complaints",
        "user_consents",
        "user_roles",
        "password_reset_tokens",
        "email_verification_tokens",
        "auth_sessions",
        "sessions",
    )
    for table in tables:
        counts[table] = _delete_where_user(cur, table, user_id)

    if email:
        cur.execute("DELETE FROM email_outbox WHERE recipient_email = ?", (email,))
        counts["email_outbox"] = max(cur.rowcount, 0)
        email_hash = hash_email_identifier(email)
        cur.execute("DELETE FROM account_rate_limits WHERE email_hash = ?", (email_hash,))
        counts["account_rate_limits"] = max(cur.rowcount, 0)
        cur.execute(
            """
            UPDATE account_security_events
            SET email_hash = ''
            WHERE email_hash = ?
            """,
            (email_hash,),
        )
        counts["security_event_email_links_cleared"] = max(cur.rowcount, 0)

    cur.execute("UPDATE invite_codes SET used_by_user_id = NULL WHERE used_by_user_id = ?", (user_id,))
    counts["invite_code_links_cleared"] = max(cur.rowcount, 0)
    cur.execute("UPDATE account_security_events SET user_id = NULL WHERE user_id = ?", (user_id,))
    counts["security_event_links_cleared"] = max(cur.rowcount, 0)
    cur.execute(
        """
        UPDATE sensitive_access_logs
        SET actor_user_id = CASE WHEN actor_user_id = ? THEN ? ELSE actor_user_id END,
            target_user_id = CASE WHEN target_user_id = ? THEN ? ELSE target_user_id END
        WHERE actor_user_id = ? OR target_user_id = ?
        """,
        (user_id, user_id_hash, user_id, user_id_hash, user_id, user_id),
    )
    counts["sensitive_access_links_anonymized"] = max(cur.rowcount, 0)
    cur.execute(
        """
        UPDATE compliance_audit_logs
        SET actor_user_id = CASE WHEN actor_user_id = ? THEN ? ELSE actor_user_id END,
            target_user_id = CASE WHEN target_user_id = ? THEN ? ELSE target_user_id END
        WHERE actor_user_id = ? OR target_user_id = ?
        """,
        (user_id, user_id_hash, user_id, user_id_hash, user_id, user_id),
    )
    counts["compliance_audit_links_anonymized"] = max(cur.rowcount, 0)
    cur.execute(
        """
        UPDATE admin_audit_logs
        SET actor_user_id = CASE WHEN actor_user_id = ? THEN ? ELSE actor_user_id END,
            target_user_id = CASE WHEN target_user_id = ? THEN ? ELSE target_user_id END
        WHERE actor_user_id = ? OR target_user_id = ?
        """,
        (user_id, user_id_hash, user_id, user_id_hash, user_id, user_id),
    )
    counts["admin_audit_links_anonymized"] = max(cur.rowcount, 0)
    cur.execute(
        """
        UPDATE data_deletion_requests
        SET user_id = NULL, user_id_hash = ?, updated_at = ?
        WHERE user_id = ? AND request_id <> ?
        """,
        (user_id_hash, now_iso(), user_id, request_id),
    )
    counts["prior_deletion_requests_anonymized"] = max(cur.rowcount, 0)
    cur.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    counts["users"] = max(cur.rowcount, 0)

    completed_at = now_iso()
    certificate_id = f"deletion_certificate_{uuid.uuid4().hex}"
    manifest = {
        "request_id": request_id,
        "user_id_hash": user_id_hash,
        "completed_at": completed_at,
        "backup_delete_by": backup_delete_by,
        "backup_action": "delete_from_all_backup_sets_by_deadline",
        "counts": counts,
    }
    cur.execute(
        """
        UPDATE data_deletion_requests
        SET user_id = NULL,
            status = 'completed',
            completed_at = ?,
            deletion_counts_json = ?,
            deletion_manifest_json = ?,
            certificate_id = ?,
            backup_status = 'scheduled',
            updated_at = ?
        WHERE request_id = ?
        """,
        (
            completed_at,
            json.dumps(counts, ensure_ascii=False),
            json.dumps(manifest, ensure_ascii=False),
            certificate_id,
            completed_at,
            request_id,
        ),
    )
    record_compliance_audit(
        cur,
        action="account_deletion_completed",
        actor_user_id=None,
        target_user_id=user_id_hash,
        resource_id=request_id,
        details={"certificate_id": certificate_id, "counts": counts},
    )
    return manifest


def process_due_account_deletions(limit: int = 10) -> dict:
    from app.db import transaction

    now = now_iso()
    with transaction() as cur:
        cur.execute(
            """
            SELECT request_id, user_id, user_id_hash, backup_delete_by
            FROM data_deletion_requests
            WHERE status = 'pending' AND scheduled_for <= ? AND user_id IS NOT NULL
            ORDER BY scheduled_for ASC
            LIMIT ?
            """,
            (now, max(1, min(limit, 50))),
        )
        due = cur.fetchall()

    completed = 0
    failed = 0
    for row in due:
        try:
            with transaction() as cur:
                _purge_user(cur, row)
            completed += 1
        except Exception as exc:
            failed += 1
            logger.exception("account_deletion_failed request_id=%s", row[0])
            with transaction() as cur:
                cur.execute(
                    """
                    UPDATE data_deletion_requests
                    SET status = 'failed', last_error = ?, updated_at = ?
                    WHERE request_id = ?
                    """,
                    (type(exc).__name__[:120], now_iso(), row[0]),
                )
                record_compliance_audit(
                    cur,
                    action="account_deletion_failed",
                    actor_user_id=None,
                    target_user_id=row[2],
                    resource_id=row[0],
                    details={"error_type": type(exc).__name__},
                )
    return {"processed": len(due), "completed": completed, "failed": failed}


def process_pending_backup_deletions(limit: int = 10) -> dict:
    from app.db import transaction

    if not BACKUP_DELETION_WEBHOOK_URL:
        return {
            "configured": False,
            "processed": 0,
            "completed": 0,
            "failed": 0,
        }

    cutoff = (
        datetime.now()
        - timedelta(seconds=max(int(BACKUP_DELETION_RETRY_SECONDS or 300), 1))
    ).isoformat()
    with transaction() as cur:
        cur.execute(
            """
            SELECT request_id, user_id_hash, certificate_id, backup_delete_by,
                   backup_attempt_count
            FROM data_deletion_requests
            WHERE status = 'completed'
              AND backup_status IN ('scheduled', 'failed')
              AND backup_attempt_count < ?
              AND (backup_last_attempt_at IS NULL OR backup_last_attempt_at <= ?)
            ORDER BY completed_at ASC
            LIMIT ?
            """,
            (
                max(int(BACKUP_DELETION_MAX_ATTEMPTS or 10), 1),
                cutoff,
                max(1, min(limit, 50)),
            ),
        )
        requests = cur.fetchall()

    completed = 0
    failed = 0
    for request_id, user_id_hash, certificate_id, backup_delete_by, attempt_count in requests:
        now = now_iso()
        status = "completed"
        error = None
        try:
            response = httpx.post(
                BACKUP_DELETION_WEBHOOK_URL,
                json={
                    "request_id": request_id,
                    "user_id_hash": user_id_hash,
                    "certificate_id": certificate_id,
                    "delete_by": backup_delete_by,
                    "action": "delete_user_from_all_backup_sets",
                },
                timeout=15,
            )
            response.raise_for_status()
            completed += 1
        except Exception as exc:
            status = "failed"
            error = type(exc).__name__[:120]
            failed += 1
            logger.warning(
                "backup_deletion_callback_failed request_id=%s error_type=%s",
                request_id,
                type(exc).__name__,
            )

        with transaction() as cur:
            cur.execute(
                """
                UPDATE data_deletion_requests
                SET backup_status = ?,
                    backup_attempt_count = backup_attempt_count + 1,
                    backup_last_attempt_at = ?,
                    backup_last_error = ?,
                    updated_at = ?
                WHERE request_id = ?
                """,
                (status, now, error, now, request_id),
            )
            record_compliance_audit(
                cur,
                action=(
                    "backup_deletion_completed"
                    if status == "completed"
                    else "backup_deletion_failed"
                ),
                actor_user_id=None,
                target_user_id=user_id_hash,
                resource_id=request_id,
                details={
                    "attempt": (attempt_count or 0) + 1,
                    "error_type": error,
                    "delete_by": backup_delete_by,
                },
            )
    return {
        "configured": True,
        "processed": len(requests),
        "completed": completed,
        "failed": failed,
    }
