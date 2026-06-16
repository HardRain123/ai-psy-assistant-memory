import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import (
    SAFETY_ADMIN_BASE_URL,
    SAFETY_ALERT_MAX_ATTEMPTS,
    SAFETY_ALERT_RETRY_SECONDS,
    SAFETY_COVERAGE_END_HOUR,
    SAFETY_COVERAGE_START_HOUR,
    SAFETY_COVERAGE_TIMEZONE,
    SAFETY_INCIDENT_MERGE_MINUTES,
    WECHAT_WORK_WEBHOOK_URL,
)
from app.db import read_transaction, transaction
from app.utils import now_iso


logger = logging.getLogger(__name__)

RISK_LEVELS = {"none", "low", "medium", "high"}
INCIDENT_STATUSES = {
    "open",
    "acknowledged",
    "assessing",
    "contacted",
    "escalated",
    "resolved",
    "false_positive",
}
ACTIVE_INCIDENT_STATUSES = {"open", "acknowledged", "assessing", "contacted", "escalated"}
INCIDENT_ACTIONS = {
    "acknowledge": "acknowledged",
    "assess": "assessing",
    "contact": "contacted",
    "escalate": "escalated",
    "resolve": "resolved",
    "false_positive": "false_positive",
}
RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}

SELF_HARM_TERMS = (
    "不想活",
    "想死",
    "自杀",
    "结束生命",
    "伤害自己",
    "自残",
    "割腕",
    "跳楼",
    "跳下去",
)
HARM_OTHER_TERMS = ("杀了他", "杀了她", "伤害别人", "弄死", "报复他们")
ACTION_TERMS = (
    "正在实施",
    "已经开始",
    "已经吞",
    "已经吃了",
    "已经割",
    "刀在手边",
    "药在手边",
    "绳子在手边",
    "站在楼顶",
    "控制不住",
    "现在就去",
    "马上就去",
)
PLAN_TERMS = ("计划", "打算", "准备", "决定", "具体方式")
TIME_TERMS = ("现在", "马上", "今晚", "今天", "一会儿", "等会儿", "明天")
MEANS_TERMS = ("刀", "药", "绳", "农药", "煤气", "楼顶", "桥上", "轨道", "枪")
LOCATION_TERMS = ("楼顶", "桥上", "窗边", "河边", "轨道", "家里没人")


def normalize_risk_level(value: str | None) -> str:
    level = (value or "none").strip().lower()
    return level if level in RISK_LEVELS else "none"


def highest_risk_level(*levels: str) -> str:
    return max((normalize_risk_level(level) for level in levels), key=lambda item: RISK_ORDER[item])


def assess_backend_risk(text: str) -> dict:
    normalized = (text or "").strip()
    has_core_risk = any(term in normalized for term in SELF_HARM_TERMS + HARM_OTHER_TERMS)
    if not has_core_risk:
        return {
            "source_risk_level": "none",
            "final_risk_level": "none",
            "immediate_action_required": False,
            "risk_flags": [],
            "reason": "",
        }

    flags = ["explicit_harm_expression"]
    immediate = any(term in normalized for term in ACTION_TERMS)
    dimensions = {
        "plan": any(term in normalized for term in PLAN_TERMS),
        "time": any(term in normalized for term in TIME_TERMS),
        "means": any(term in normalized for term in MEANS_TERMS),
        "location": any(term in normalized for term in LOCATION_TERMS),
    }
    for name, matched in dimensions.items():
        if matched:
            flags.append(f"immediacy_{name}")
    if sum(1 for matched in dimensions.values() if matched) >= 2:
        immediate = True
    if immediate:
        flags.append("immediate_action_required")

    return {
        "source_risk_level": "high",
        "final_risk_level": "high",
        "immediate_action_required": immediate,
        "risk_flags": flags,
        "reason": "检测到明确伤害表达" + ("及迫近危险信号" if immediate else ""),
    }


def _has_immediacy_signal(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if any(term in normalized for term in ACTION_TERMS + PLAN_TERMS):
        return True
    dimensions = (
        any(term in normalized for term in PLAN_TERMS),
        any(term in normalized for term in TIME_TERMS),
        any(term in normalized for term in MEANS_TERMS),
        any(term in normalized for term in LOCATION_TERMS),
    )
    return sum(1 for matched in dimensions if matched) >= 2


def immediate_action_from_evidence(
    *,
    final_risk_level: str,
    reason: str = "",
    risk_flags: list[str] | None = None,
    source_evidence: dict | None = None,
) -> bool:
    if normalize_risk_level(final_risk_level) != "high":
        return False
    flags = set(risk_flags or [])
    evidence = source_evidence or {}
    if "current_safety_urgent" in flags:
        return True
    if evidence.get("current_danger") == "urgent_attention":
        return True
    return _has_immediacy_signal(reason)


def is_within_safety_coverage(at: datetime | None = None) -> bool:
    timezone = ZoneInfo(SAFETY_COVERAGE_TIMEZONE)
    current = at.astimezone(timezone) if at and at.tzinfo else (at.replace(tzinfo=timezone) if at else datetime.now(timezone))
    return current.weekday() < 5 and SAFETY_COVERAGE_START_HOUR <= current.hour < SAFETY_COVERAGE_END_HOUR


def safety_deadline_now_iso() -> str:
    current = datetime.now(ZoneInfo(SAFETY_COVERAGE_TIMEZONE))
    return current.replace(tzinfo=None).isoformat()


def safety_response_deadlines(risk_level: str, at: datetime | None = None) -> dict:
    timezone = ZoneInfo(SAFETY_COVERAGE_TIMEZONE)
    current = at.astimezone(timezone) if at and at.tzinfo else (at.replace(tzinfo=timezone) if at else datetime.now(timezone))
    if not is_within_safety_coverage(current):
        candidate = current.replace(
            hour=SAFETY_COVERAGE_START_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
        if current >= candidate or current.weekday() >= 5:
            candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        current = candidate
    base = current.replace(tzinfo=None)
    level = normalize_risk_level(risk_level)
    return {
        "acknowledgement_due_at": (base + timedelta(minutes=5)).isoformat() if level == "high" else None,
        "first_response_due_at": (base + timedelta(minutes=15)).isoformat() if level == "high" else None,
        "review_due_at": (base + timedelta(minutes=30)).isoformat() if level == "medium" else None,
    }


def _json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _incident_payload(row) -> dict:
    return {
        "incident_id": row[0],
        "user_id": row[1],
        "session_id": row[2] or "",
        "status": row[3],
        "source": row[4],
        "source_risk_level": row[5],
        "final_risk_level": row[6],
        "immediate_action_required": bool(row[7]),
        "risk_flags": _json_list(row[8]),
        "reason": row[9] or "",
        "source_evidence": _json_object(row[10]),
        "trigger_message_id": row[11],
        "assigned_to_user_id": row[12],
        "alert_status": row[13],
        "alert_attempt_count": row[14] or 0,
        "alert_last_error": row[15],
        "alert_last_attempt_at": row[16],
        "alert_sent_at": row[17],
        "acknowledged_at": row[18],
        "first_response_at": row[19],
        "acknowledgement_due_at": row[20],
        "first_response_due_at": row[21],
        "review_due_at": row[22],
        "follow_up_at": row[23],
        "resolved_at": row[24],
        "created_at": row[25],
        "updated_at": row[26],
    }


INCIDENT_SELECT = """
    SELECT incident_id, user_id, session_id, status, source,
           source_risk_level, final_risk_level, immediate_action_required,
           risk_flags, reason, source_evidence, trigger_message_id,
           assigned_to_user_id, alert_status, alert_attempt_count,
           alert_last_error, alert_last_attempt_at, alert_sent_at,
           acknowledged_at, first_response_at,
           acknowledgement_due_at, first_response_due_at, review_due_at,
           follow_up_at, resolved_at,
           created_at, updated_at
    FROM safety_incidents
"""


def add_incident_event(
    cur,
    *,
    incident_id: str,
    event_type: str,
    actor_user_id: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str = "",
    metadata: dict | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO safety_incident_events (
            incident_id, event_type, actor_user_id, from_status,
            to_status, note, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incident_id,
            event_type,
            actor_user_id,
            from_status,
            to_status,
            (note or "")[:2000],
            json.dumps(metadata or {}, ensure_ascii=False),
            now_iso(),
        ),
    )


def create_or_merge_safety_incident(
    cur,
    *,
    user_id: str,
    session_id: str = "",
    source: str,
    source_risk_level: str,
    final_risk_level: str,
    immediate_action_required: bool = False,
    risk_flags: list[str] | None = None,
    reason: str = "",
    source_evidence: dict | None = None,
    trigger_message_id: int | None = None,
) -> dict | None:
    source_level = normalize_risk_level(source_risk_level)
    final_level = highest_risk_level(source_level, final_risk_level)

    source = (source or "manual").strip().lower()
    if source not in {"dify", "keyword", "screening", "manual"}:
        source = "manual"
    flags = list(dict.fromkeys(str(flag)[:120] for flag in (risk_flags or []) if str(flag).strip()))
    evidence = source_evidence or {}
    immediate = immediate_action_from_evidence(
        final_risk_level=final_level,
        reason=reason,
        risk_flags=flags,
        source_evidence=evidence,
    )
    if source in {"manual", "keyword"} and immediate_action_required:
        immediate = True
    if final_level != "high":
        immediate = False
    evaluation_id = f"risk_eval_{uuid.uuid4().hex}"
    now = now_iso()
    cur.execute(
        """
        INSERT INTO safety_risk_evaluations (
            evaluation_id, incident_id, user_id, session_id, source,
            source_risk_level, final_risk_level, immediate_action_required,
            risk_flags, reason, source_evidence, trigger_message_id, created_at
        )
        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evaluation_id,
            user_id,
            session_id or "",
            source,
            source_level,
            final_level,
            1 if immediate else 0,
            json.dumps(flags, ensure_ascii=False),
            (reason or "")[:1000],
            json.dumps(evidence, ensure_ascii=False),
            trigger_message_id,
            now,
        ),
    )
    if final_level not in {"medium", "high"}:
        return None

    cutoff = (datetime.now() - timedelta(minutes=max(SAFETY_INCIDENT_MERGE_MINUTES, 1))).isoformat()
    status_placeholders = ",".join("?" for _ in ACTIVE_INCIDENT_STATUSES)
    cur.execute(
        f"""
        {INCIDENT_SELECT}
        WHERE user_id = ?
          AND session_id = ?
          AND status IN ({status_placeholders})
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, session_id or "", *sorted(ACTIVE_INCIDENT_STATUSES), cutoff),
    )
    existing_row = cur.fetchone()
    if existing_row:
        existing = _incident_payload(existing_row)
        merged_level = highest_risk_level(existing["final_risk_level"], final_level)
        merged_flags = list(dict.fromkeys(existing["risk_flags"] + flags))
        merged_evidence = dict(existing["source_evidence"])
        existing_source_evidence = merged_evidence.get(source, [])
        if not isinstance(existing_source_evidence, list):
            existing_source_evidence = [existing_source_evidence]
        existing_source_evidence.append({"recorded_at": now, **evidence})
        merged_evidence[source] = existing_source_evidence
        merged_immediate = bool(existing["immediate_action_required"] or immediate)
        deadlines = safety_response_deadlines(merged_level)
        alert_status = existing["alert_status"]
        if merged_level == "high" and alert_status in {"not_required", "queued_off_hours"}:
            alert_status = "pending" if is_within_safety_coverage() else "queued_off_hours"
        cur.execute(
            """
            UPDATE safety_incidents
            SET source = ?,
                source_risk_level = ?,
                final_risk_level = ?,
                immediate_action_required = ?,
                risk_flags = ?,
                reason = ?,
                source_evidence = ?,
                trigger_message_id = COALESCE(?, trigger_message_id),
                alert_status = ?,
                acknowledgement_due_at = COALESCE(acknowledgement_due_at, ?),
                first_response_due_at = COALESCE(first_response_due_at, ?),
                review_due_at = COALESCE(review_due_at, ?),
                updated_at = ?
            WHERE incident_id = ?
            """,
            (
                source,
                highest_risk_level(existing["source_risk_level"], source_level),
                merged_level,
                1 if merged_immediate else 0,
                json.dumps(merged_flags, ensure_ascii=False),
                (reason or existing["reason"])[:1000],
                json.dumps(merged_evidence, ensure_ascii=False),
                trigger_message_id,
                alert_status,
                deadlines["acknowledgement_due_at"],
                deadlines["first_response_due_at"],
                deadlines["review_due_at"],
                now,
                existing["incident_id"],
            ),
        )
        add_incident_event(
            cur,
            incident_id=existing["incident_id"],
            event_type="risk_merged",
            note=reason,
            metadata={
                "source": source,
                "source_risk_level": source_level,
                "final_risk_level": final_level,
                "immediate_action_required": immediate,
                "risk_flags": flags,
            },
        )
        cur.execute(
            """
            UPDATE safety_risk_evaluations
            SET incident_id = ?
            WHERE evaluation_id = ?
            """,
            (existing["incident_id"], evaluation_id),
        )
        cur.execute(f"{INCIDENT_SELECT} WHERE incident_id = ?", (existing["incident_id"],))
        return _incident_payload(cur.fetchone())

    incident_id = f"safety_{uuid.uuid4().hex}"
    deadlines = safety_response_deadlines(final_level)
    alert_status = "not_required"
    if final_level == "high":
        alert_status = "pending" if is_within_safety_coverage() else "queued_off_hours"
    cur.execute(
        """
        INSERT INTO safety_incidents (
            incident_id, user_id, session_id, status, source,
            source_risk_level, final_risk_level, immediate_action_required,
            risk_flags, reason, source_evidence, trigger_message_id,
            alert_status, acknowledgement_due_at, first_response_due_at,
            review_due_at, created_at, updated_at
        )
        VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incident_id,
            user_id,
            session_id or "",
            source,
            source_level,
            final_level,
            1 if immediate else 0,
            json.dumps(flags, ensure_ascii=False),
            (reason or "")[:1000],
            json.dumps({source: [{"recorded_at": now, **evidence}]}, ensure_ascii=False),
            trigger_message_id,
            alert_status,
            deadlines["acknowledgement_due_at"],
            deadlines["first_response_due_at"],
            deadlines["review_due_at"],
            now,
            now,
        ),
    )
    add_incident_event(
        cur,
        incident_id=incident_id,
        event_type="created",
        note=reason,
        metadata={
            "source": source,
            "source_risk_level": source_level,
            "final_risk_level": final_level,
            "immediate_action_required": immediate,
            "risk_flags": flags,
        },
    )
    cur.execute(
        """
        UPDATE safety_risk_evaluations
        SET incident_id = ?
        WHERE evaluation_id = ?
        """,
        (incident_id, evaluation_id),
    )
    cur.execute(f"{INCIDENT_SELECT} WHERE incident_id = ?", (incident_id,))
    return _incident_payload(cur.fetchone())


def list_safety_incidents(cur, *, status: str = "", risk_level: str = "", limit: int = 100) -> list[dict]:
    clauses = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if risk_level:
        clauses.append("final_risk_level = ?")
        params.append(normalize_risk_level(risk_level))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    cur.execute(
        f"{INCIDENT_SELECT}{where} ORDER BY immediate_action_required DESC, created_at DESC LIMIT ?",
        (*params, max(1, min(limit, 200))),
    )
    return [_incident_payload(row) for row in cur.fetchall()]


def get_safety_incident(cur, incident_id: str) -> dict | None:
    cur.execute(f"{INCIDENT_SELECT} WHERE incident_id = ? LIMIT 1", (incident_id,))
    row = cur.fetchone()
    if not row:
        return None
    incident = _incident_payload(row)
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
    incident["events"] = [
        {
            "event_type": item[0],
            "actor_user_id": item[1],
            "from_status": item[2],
            "to_status": item[3],
            "note": item[4] or "",
            "metadata": _json_object(item[5]),
            "created_at": item[6],
        }
        for item in cur.fetchall()
    ]
    incident["message_context"] = get_incident_message_context(cur, incident)
    return incident


def get_incident_message_context(cur, incident: dict) -> list[dict]:
    message_id = incident.get("trigger_message_id")
    if not message_id:
        return []
    cur.execute(
        """
        SELECT id, role, content, risk_level, created_at
        FROM session_messages
        WHERE user_id = ? AND session_id = ? AND id <= ?
        ORDER BY id DESC
        LIMIT 3
        """,
        (
            incident["user_id"],
            incident["session_id"],
            int(message_id),
        ),
    )
    before_and_trigger = list(reversed(cur.fetchall()))
    cur.execute(
        """
        SELECT id, role, content, risk_level, created_at
        FROM session_messages
        WHERE user_id = ? AND session_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT 2
        """,
        (
            incident["user_id"],
            incident["session_id"],
            int(message_id),
        ),
    )
    rows = before_and_trigger + cur.fetchall()
    return [
        {
            "message_id": row[0],
            "role": row[1],
            "content": row[2],
            "risk_level": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def apply_incident_action(
    cur,
    *,
    incident_id: str,
    action: str,
    actor_user_id: str,
    note: str = "",
    follow_up_at: str | None = None,
) -> dict:
    if action not in INCIDENT_ACTIONS:
        raise ValueError("invalid_safety_action")
    incident = get_safety_incident(cur, incident_id)
    if not incident:
        raise LookupError("safety_incident_not_found")
    new_status = INCIDENT_ACTIONS[action]
    now = now_iso()
    acknowledged_at = incident["acknowledged_at"]
    first_response_at = incident["first_response_at"]
    resolved_at = incident["resolved_at"]
    if action == "acknowledge" and not acknowledged_at:
        acknowledged_at = now
    if action in {"contact", "escalate", "resolve"} and not first_response_at:
        first_response_at = now
    if action in {"resolve", "false_positive"}:
        resolved_at = now
    cur.execute(
        """
        UPDATE safety_incidents
        SET status = ?,
            assigned_to_user_id = COALESCE(assigned_to_user_id, ?),
            acknowledged_at = ?,
            first_response_at = ?,
            follow_up_at = COALESCE(?, follow_up_at),
            resolved_at = ?,
            updated_at = ?
        WHERE incident_id = ?
        """,
        (
            new_status,
            actor_user_id,
            acknowledged_at,
            first_response_at,
            follow_up_at,
            resolved_at,
            now,
            incident_id,
        ),
    )
    add_incident_event(
        cur,
        incident_id=incident_id,
        event_type=action,
        actor_user_id=actor_user_id,
        from_status=incident["status"],
        to_status=new_status,
        note=note,
        metadata={"follow_up_at": follow_up_at},
    )
    return get_safety_incident(cur, incident_id)


def retry_safety_alert(
    cur,
    *,
    incident_id: str,
    actor_user_id: str,
    note: str = "",
) -> dict:
    incident = get_safety_incident(cur, incident_id)
    if not incident:
        raise LookupError("safety_incident_not_found")
    if incident["final_risk_level"] != "high":
        raise ValueError("safety_alert_retry_requires_high_risk")
    if incident["status"] not in ACTIVE_INCIDENT_STATUSES:
        raise ValueError("safety_alert_retry_requires_active_incident")
    if incident["alert_status"] != "failed":
        raise ValueError("safety_alert_retry_requires_failed_alert")

    cur.execute(
        """
        UPDATE safety_incidents
        SET alert_status = 'pending',
            alert_attempt_count = 0,
            alert_last_error = NULL,
            alert_last_attempt_at = NULL,
            updated_at = ?
        WHERE incident_id = ?
        """,
        (now_iso(), incident_id),
    )
    add_incident_event(
        cur,
        incident_id=incident_id,
        event_type="alert_retry_queued",
        actor_user_id=actor_user_id,
        from_status=incident["status"],
        to_status=incident["status"],
        note=note,
        metadata={
            "previous_attempt_count": incident["alert_attempt_count"],
            "previous_error": incident["alert_last_error"],
        },
    )
    return get_safety_incident(cur, incident_id)


def record_sensitive_access(
    cur,
    *,
    actor_user_id: str,
    target_user_id: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    ip_hash: str = "",
    user_agent: str = "",
) -> None:
    cur.execute(
        """
        INSERT INTO sensitive_access_logs (
            actor_user_id, target_user_id, resource_type, resource_id,
            reason, ip_hash, user_agent, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor_user_id,
            target_user_id,
            resource_type,
            resource_id,
            reason[:500],
            ip_hash[:128],
            user_agent[:300],
            now_iso(),
        ),
    )


def get_full_incident_transcript(cur, *, incident: dict) -> list[dict]:
    cur.execute(
        """
        SELECT id, role, content, risk_level, created_at
        FROM session_messages
        WHERE user_id = ? AND session_id = ?
        ORDER BY id ASC
        """,
        (incident["user_id"], incident["session_id"]),
    )
    return [
        {
            "message_id": row[0],
            "role": row[1],
            "content": row[2],
            "risk_level": row[3],
            "created_at": row[4],
        }
        for row in cur.fetchall()
    ]


def _alert_text(incident: dict) -> str:
    priority = "最高优先级" if incident["immediate_action_required"] else "高风险"
    base_url = (SAFETY_ADMIN_BASE_URL or "").rstrip("/")
    detail_url = f"{base_url}/admin/safety/{incident['incident_id']}" if base_url else incident["incident_id"]
    return "\n".join(
        [
            f"心理安全工单：{priority}",
            f"事件ID：{incident['incident_id']}",
            f"风险等级：{incident['final_risk_level']}",
            f"立即处置：{'是' if incident['immediate_action_required'] else '否'}",
            f"创建时间：{incident['created_at']}",
            f"处理链接：{detail_url}",
        ]
    )


def process_pending_safety_alerts(limit: int = 20) -> dict:
    if not is_within_safety_coverage():
        return {"coverage_active": False, "processed": 0, "sent": 0, "failed": 0}

    cutoff = (datetime.now() - timedelta(seconds=max(SAFETY_ALERT_RETRY_SECONDS, 1))).isoformat()
    with read_transaction() as cur:
        cur.execute(
            f"""
            {INCIDENT_SELECT}
            WHERE final_risk_level = 'high'
              AND status IN ('open', 'acknowledged', 'assessing', 'contacted', 'escalated')
              AND alert_status IN ('pending', 'failed', 'queued_off_hours')
              AND alert_attempt_count < ?
              AND (alert_last_attempt_at IS NULL OR alert_last_attempt_at <= ?)
            ORDER BY immediate_action_required DESC, created_at ASC
            LIMIT ?
            """,
            (max(SAFETY_ALERT_MAX_ATTEMPTS, 1), cutoff, max(1, min(limit, 100))),
        )
        incidents = [_incident_payload(row) for row in cur.fetchall()]

    sent = 0
    failed = 0
    for incident in incidents:
        now = now_iso()
        status = "sent"
        error = None
        try:
            if not WECHAT_WORK_WEBHOOK_URL:
                raise RuntimeError("wechat_webhook_not_configured")
            response = httpx.post(
                WECHAT_WORK_WEBHOOK_URL,
                json={"msgtype": "text", "text": {"content": _alert_text(incident)}},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errcode") not in {None, 0}:
                raise RuntimeError(f"wechat_error_{payload.get('errcode')}")
            sent += 1
        except Exception as exc:
            status = "failed"
            error = re.sub(r"https?://\S+", "[url]", type(exc).__name__)[:120]
            failed += 1
            logger.warning(
                "safety_alert_failed incident_id=%s error_type=%s",
                incident["incident_id"],
                type(exc).__name__,
            )

        with transaction() as cur:
            cur.execute(
                """
                UPDATE safety_incidents
                SET alert_status = ?,
                    alert_attempt_count = alert_attempt_count + 1,
                    alert_last_error = ?,
                    alert_last_attempt_at = ?,
                    alert_sent_at = CASE WHEN ? = 'sent' THEN ? ELSE alert_sent_at END,
                    updated_at = ?
                WHERE incident_id = ?
                """,
                (status, error, now, status, now, now, incident["incident_id"]),
            )
            add_incident_event(
                cur,
                incident_id=incident["incident_id"],
                event_type="alert_sent" if status == "sent" else "alert_failed",
                note="" if status == "sent" else error or "alert_failed",
                metadata={"attempt": incident["alert_attempt_count"] + 1},
            )

    return {
        "coverage_active": True,
        "processed": len(incidents),
        "sent": sent,
        "failed": failed,
    }
