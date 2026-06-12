import json
from app.config import BETA_USER_LIMIT, SAFETY_ALERT_MAX_ATTEMPTS
from app.services.safety import is_within_safety_coverage, safety_deadline_now_iso
from app.utils import now_iso


INVITE_PAUSE_CONTROL = "invite_issuance_paused"


def _control_row(cur) -> dict:
    cur.execute(
        """
        SELECT enabled, reason, metadata_json, updated_by_user_id, created_at, updated_at
        FROM launch_controls
        WHERE control_key = ?
        LIMIT 1
        """,
        (INVITE_PAUSE_CONTROL,),
    )
    row = cur.fetchone()
    if not row:
        return {
            "paused": False,
            "reason": "",
            "metadata": {},
            "updated_by_user_id": None,
            "created_at": None,
            "updated_at": None,
        }
    try:
        metadata = json.loads(row[2] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return {
        "paused": bool(row[0]),
        "reason": row[1] or "",
        "metadata": metadata if isinstance(metadata, dict) else {},
        "updated_by_user_id": row[3],
        "created_at": row[4],
        "updated_at": row[5],
    }


def get_launch_status(cur) -> dict:
    control = _control_row(cur)
    cur.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin = 0 AND disabled_at IS NULL"
    )
    active_adult_users = cur.fetchone()[0] or 0
    return {
        **control,
        "active_adult_users": active_adult_users,
        "beta_user_limit": max(int(BETA_USER_LIMIT or 50), 1),
        "at_user_limit": active_adult_users >= max(int(BETA_USER_LIMIT or 50), 1),
    }


def set_invite_pause(
    cur,
    *,
    paused: bool,
    reason: str,
    metadata: dict | None = None,
    actor_user_id: str | None = None,
) -> dict:
    now = now_iso()
    cur.execute(
        """
        INSERT INTO launch_controls (
            control_key, enabled, reason, metadata_json,
            updated_by_user_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(control_key) DO UPDATE SET
            enabled = excluded.enabled,
            reason = excluded.reason,
            metadata_json = excluded.metadata_json,
            updated_by_user_id = excluded.updated_by_user_id,
            updated_at = excluded.updated_at
        """,
        (
            INVITE_PAUSE_CONTROL,
            1 if paused else 0,
            reason[:240],
            json.dumps(metadata or {}, ensure_ascii=False),
            actor_user_id,
            now,
            now,
        ),
    )
    return get_launch_status(cur)


def assert_invite_issuance_allowed(cur) -> None:
    status = get_launch_status(cur)
    if status["paused"]:
        raise ValueError("invite_issuance_paused")
    if status["at_user_limit"]:
        raise ValueError("beta_user_limit_reached")


def evaluate_launch_gates(cur) -> dict:
    reasons = []
    metadata = {}
    if is_within_safety_coverage():
        now = safety_deadline_now_iso()
        cur.execute(
            """
            SELECT incident_id
            FROM safety_incidents
            WHERE final_risk_level = 'high'
              AND status IN ('open', 'acknowledged', 'assessing')
              AND first_response_at IS NULL
              AND first_response_due_at IS NOT NULL
              AND first_response_due_at <= ?
            ORDER BY created_at ASC
            LIMIT 20
            """,
            (now,),
        )
        overdue = [row[0] for row in cur.fetchall()]
        if overdue:
            reasons.append("high_risk_first_response_overdue")
            metadata["overdue_incident_ids"] = overdue

    cur.execute(
        """
        SELECT incident_id
        FROM safety_incidents
        WHERE final_risk_level = 'high'
          AND alert_status = 'failed'
          AND alert_attempt_count >= ?
        ORDER BY updated_at DESC
        LIMIT 20
        """,
        (max(int(SAFETY_ALERT_MAX_ATTEMPTS or 5), 1),),
    )
    alert_failures = [row[0] for row in cur.fetchall()]
    if alert_failures:
        reasons.append("safety_alert_channel_failed")
        metadata["alert_failure_incident_ids"] = alert_failures

    cur.execute(
        """
        SELECT request_id
        FROM data_deletion_requests
        WHERE status = 'failed'
        ORDER BY updated_at DESC
        LIMIT 20
        """
    )
    deletion_failures = [row[0] for row in cur.fetchall()]
    if deletion_failures:
        reasons.append("account_deletion_failed")
        metadata["deletion_failure_request_ids"] = deletion_failures

    cur.execute(
        """
        SELECT request_id
        FROM data_deletion_requests
        WHERE status = 'completed' AND backup_status = 'failed'
        ORDER BY updated_at DESC
        LIMIT 20
        """
    )
    backup_failures = [row[0] for row in cur.fetchall()]
    if backup_failures:
        reasons.append("backup_deletion_failed")
        metadata["backup_deletion_failure_request_ids"] = backup_failures

    if reasons:
        return set_invite_pause(
            cur,
            paused=True,
            reason=",".join(reasons),
            metadata=metadata,
        )
    return get_launch_status(cur)
