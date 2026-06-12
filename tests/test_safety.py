from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import transaction
from app.main import app
from app.services.safety import (
    INCIDENT_STATUSES,
    RISK_LEVELS,
    _alert_text,
    assess_backend_risk,
    create_or_merge_safety_incident,
    get_safety_incident,
    immediate_action_from_evidence,
    process_pending_safety_alerts,
    safety_response_deadlines,
)
from app.services.launch_controls import (
    assert_invite_issuance_allowed,
    evaluate_launch_gates,
    get_launch_status,
    set_invite_pause,
)


client = TestClient(app)
client.headers.update({"X-Backend-Token": "test-backend-token"})


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _save_message_and_get_id(*, user_id: str, session_id: str, content: str) -> tuple[int, dict]:
    response = client.post(
        "/session-message",
        json={
            "user_id": user_id,
            "session_id": session_id,
            "role": "user",
            "content": content,
        },
    )
    assert response.status_code == 200
    with transaction() as cur:
        cur.execute(
            """
            SELECT id
            FROM session_messages
            WHERE user_id = ? AND session_id = ? AND role = 'user' AND content = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, session_id, content),
        )
        row = cur.fetchone()
    assert row
    return row[0], response.json()


def test_risk_enum_stays_compatible_with_dify():
    assert RISK_LEVELS == {"none", "low", "medium", "high"}
    assert "urgent" not in RISK_LEVELS
    assert INCIDENT_STATUSES == {
        "open",
        "acknowledged",
        "assessing",
        "contacted",
        "escalated",
        "resolved",
        "false_positive",
    }

    vague = assess_backend_risk("我不想活了")
    assert vague["final_risk_level"] == "high"
    assert vague["immediate_action_required"] is False

    imminent = assess_backend_risk("我打算今晚在楼顶跳下去")
    assert imminent["final_risk_level"] == "high"
    assert imminent["immediate_action_required"] is True

    assert immediate_action_from_evidence(
        final_risk_level="high",
        reason="已有具体计划并准备了工具",
    )
    assert not immediate_action_from_evidence(
        final_risk_level="medium",
        reason="已有具体计划并准备了工具",
    )


def test_sla_deadlines_and_wechat_alert_are_sanitized():
    at = datetime(2026, 6, 15, 10, 0)
    medium = safety_response_deadlines("medium", at=at)
    high = safety_response_deadlines("high", at=at)

    assert medium == {
        "acknowledgement_due_at": None,
        "first_response_due_at": None,
        "review_due_at": "2026-06-15T10:30:00",
    }
    assert high == {
        "acknowledgement_due_at": "2026-06-15T10:05:00",
        "first_response_due_at": "2026-06-15T10:15:00",
        "review_due_at": None,
    }

    alert = _alert_text(
        {
            "incident_id": "safety_sanitized",
            "final_risk_level": "high",
            "immediate_action_required": True,
            "created_at": "2026-06-15T10:00:00",
            "reason": "敏感聊天原文不应发送",
            "user_id": "private-user-id",
            "session_id": "private-session-id",
        }
    )
    assert "safety_sanitized" in alert
    assert "风险等级：high" in alert
    assert "立即处置：是" in alert
    assert "敏感聊天原文" not in alert
    assert "private-user-id" not in alert
    assert "private-session-id" not in alert


def test_dify_medium_never_becomes_immediate():
    user_id = _unique("safety-dify-medium")
    response = client.post(
        "/internal/safety/incidents",
        json={
            "user_id": user_id,
            "session_id": "session-1",
            "source": "dify",
            "source_risk_level": "medium",
            "final_risk_level": "medium",
            "immediate_action_required": True,
            "risk_flags": ["needs_review"],
            "reason": "需要人工复核",
            "source_evidence": {"need_safety_check": True},
        },
    )
    assert response.status_code == 200
    incident = response.json()["incident"]
    assert incident["final_risk_level"] == "medium"
    assert incident["immediate_action_required"] is False
    assert incident["alert_status"] == "not_required"


def test_dify_high_requires_imminence_evidence_for_immediate_flag():
    user_id = _unique("safety-dify-high")
    vague = client.post(
        "/internal/safety/incidents",
        json={
            "user_id": user_id,
            "session_id": "session-vague",
            "source": "dify",
            "source_risk_level": "high",
            "final_risk_level": "high",
            "immediate_action_required": True,
            "risk_flags": [],
            "reason": "当前输入出现高危表达",
            "source_evidence": {"need_safety_check": True},
        },
    ).json()["incident"]
    assert vague["immediate_action_required"] is False

    planned = client.post(
        "/internal/safety/incidents",
        json={
            "user_id": user_id,
            "session_id": "session-planned",
            "source": "dify",
            "source_risk_level": "high",
            "final_risk_level": "high",
            "immediate_action_required": False,
            "risk_flags": [],
            "reason": "当前输入出现具体计划并已准备工具",
            "source_evidence": {"need_safety_check": True},
        },
    ).json()["incident"]
    assert planned["immediate_action_required"] is True


def test_dify_low_is_recorded_without_creating_incident():
    user_id = _unique("safety-dify-low")
    response = client.post(
        "/internal/safety/incidents",
        json={
            "user_id": user_id,
            "session_id": "session-low",
            "source": "dify",
            "source_risk_level": "low",
            "final_risk_level": "low",
            "immediate_action_required": False,
            "risk_flags": [],
            "reason": "未发现明显安全风险",
            "source_evidence": {"need_safety_check": False},
        },
    )
    assert response.status_code == 200
    assert response.json()["incident"] is None
    with transaction() as cur:
        cur.execute(
            """
            SELECT source_risk_level, final_risk_level, immediate_action_required
            FROM safety_risk_evaluations
            WHERE user_id = ?
            """,
            (user_id,),
        )
        evaluation = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM safety_incidents WHERE user_id = ?", (user_id,))
        incident_count = cur.fetchone()[0]
    assert evaluation == ("low", "low", 0)
    assert incident_count == 0


def test_keyword_incident_merges_and_appends_evidence():
    user_id = _unique("safety-keyword")
    session_id = client.get(f"/session/status/{user_id}").json()["session_id"]

    first = client.post(
        "/session-message",
        json={
            "user_id": user_id,
            "session_id": session_id,
            "role": "user",
            "content": "我不想活了",
            "turn_id": "turn-1",
        },
    ).json()
    second = client.post(
        "/session-message",
        json={
            "user_id": user_id,
            "session_id": session_id,
            "role": "user",
            "content": "我打算今晚在楼顶跳下去",
            "turn_id": "turn-2",
        },
    ).json()

    assert first["risk_level"] == "high"
    assert first["immediate_action_required"] is False
    assert second["risk_level"] == "high"
    assert second["immediate_action_required"] is True
    assert first["safety_incident_id"] == second["safety_incident_id"]
    guidance = second["safety_guidance"]
    guidance_text = "\n".join(
        [guidance["title"], *guidance["actions"], guidance["coverage_message"]]
    )
    for marker in ["110", "120", "远离", "不要独处", "可信任"]:
        assert marker in guidance_text

    with transaction() as cur:
        cur.execute(
            """
            SELECT final_risk_level, immediate_action_required, source_evidence
            FROM safety_incidents
            WHERE incident_id = ?
            """,
            (first["safety_incident_id"],),
        )
        row = cur.fetchone()

    assert row[0] == "high"
    assert row[1] == 1
    assert '"keyword": [' in row[2]
    assert row[2].count('"recorded_at"') == 2
    assert "urgent" not in row[0]


def test_incident_default_context_is_bounded_around_trigger():
    user_id = _unique("safety-context")
    session_id = client.get(f"/session/status/{user_id}").json()["session_id"]
    saved_ids = []
    for content in ["前置消息一", "前置消息二"]:
        message_id, _ = _save_message_and_get_id(
            user_id=user_id,
            session_id=session_id,
            content=content,
        )
        saved_ids.append(message_id)
    trigger_id, trigger = _save_message_and_get_id(
        user_id=user_id,
        session_id=session_id,
        content="我打算今晚在楼顶跳下去",
    )
    saved_ids.append(trigger_id)
    for content in ["后续消息一", "后续消息二", "后续消息三不应默认展示"]:
        message_id, _ = _save_message_and_get_id(
            user_id=user_id,
            session_id=session_id,
            content=content,
        )
        saved_ids.append(message_id)

    with transaction() as cur:
        incident = get_safety_incident(cur, trigger["safety_incident_id"])
    context_ids = [item["message_id"] for item in incident["message_context"]]
    assert context_ids == saved_ids[:5]
    assert saved_ids[5] not in context_ids


def test_screening_urgent_flag_sets_immediate_boolean():
    user_id = _unique("safety-screening")
    response = client.post(
        "/screening/batch",
        json={
            "user_id": user_id,
            "screenings": [
                {"instrument": "phq9", "answers": [0, 0, 0, 0, 0, 0, 0, 0, 1]},
            ],
            "supplements": {"safety": [3, 2, 2, 2]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["safety"]["risk_level"] == "high"
    assert payload["snapshot"]["domains"]["safety"]["current_danger"] == "urgent_attention"
    assert "current_safety_urgent" in payload["snapshot"]["safety"]["flags"]
    assert payload["immediate_action_required"] is True
    assert payload["snapshot"]["safety"]["risk_level"] != "urgent"


def test_off_hours_high_risk_notice_does_not_promise_realtime_staff():
    user_id = _unique("safety-off-hours")
    session_id = client.get(f"/session/status/{user_id}").json()["session_id"]
    with patch("app.routers.messages.is_within_safety_coverage", return_value=False):
        response = client.post(
            "/session-message",
            json={
                "user_id": user_id,
                "session_id": session_id,
                "role": "user",
                "content": "我不想活了",
            },
        )
    assert response.status_code == 200
    guidance = response.json()["safety_guidance"]
    assert "无人实时查看" in guidance["coverage_message"]
    assert "下一工作日" in guidance["coverage_message"]
    assert "正在处理" not in guidance["coverage_message"]


def test_wechat_alert_failure_retries_and_remains_visible():
    user_id = _unique("safety-alert")
    with patch("app.services.safety.is_within_safety_coverage", return_value=True):
        with transaction() as cur:
            incident = create_or_merge_safety_incident(
                cur,
                user_id=user_id,
                session_id="session-alert",
                source="manual",
                source_risk_level="high",
                final_risk_level="high",
                immediate_action_required=True,
                risk_flags=["manual_test"],
                reason="测试告警重试",
                source_evidence={"test": True},
            )

    with (
        patch("app.services.safety.is_within_safety_coverage", return_value=True),
        patch("app.services.safety.WECHAT_WORK_WEBHOOK_URL", "https://example.invalid/webhook"),
        patch("app.services.safety.SAFETY_ALERT_RETRY_SECONDS", 1),
        patch("app.services.safety.httpx.post", side_effect=RuntimeError("network down")),
    ):
        first = process_pending_safety_alerts()
        with transaction() as cur:
            cur.execute(
                """
                UPDATE safety_incidents
                SET alert_last_attempt_at = ?
                WHERE incident_id = ?
                """,
                ((datetime.now() - timedelta(seconds=2)).isoformat(), incident["incident_id"]),
            )
        second = process_pending_safety_alerts()

    assert first["failed"] >= 1
    assert second["failed"] >= 1
    with transaction() as cur:
        cur.execute(
            """
            SELECT alert_status, alert_attempt_count, alert_last_error
            FROM safety_incidents
            WHERE incident_id = ?
            """,
            (incident["incident_id"],),
        )
        row = cur.fetchone()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM safety_incident_events
            WHERE incident_id = ? AND event_type = 'alert_failed'
            """,
            (incident["incident_id"],),
        )
        event_count = cur.fetchone()[0]

    assert row[0] == "failed"
    assert row[1] == 2
    assert row[2] == "RuntimeError"
    assert event_count == 2


def test_sensitive_transcript_access_and_actions_are_audited():
    admin_login = client.post(
        "/internal/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )
    admin_token = admin_login.json()["session_token"]
    user_id = _unique("safety-audit")
    session_id = client.get(f"/session/status/{user_id}").json()["session_id"]
    saved = client.post(
        "/session-message",
        json={
            "user_id": user_id,
            "session_id": session_id,
            "role": "user",
            "content": "我打算今晚在楼顶跳下去",
        },
    ).json()
    incident_id = saved["safety_incident_id"]

    action = client.post(
        f"/internal/admin/safety/incidents/{incident_id}/actions",
        headers={"X-Auth-Session": admin_token},
        json={"action": "acknowledge", "note": "已确认并开始安全评估"},
    )
    assert action.status_code == 200
    assert action.json()["incident"]["status"] == "acknowledged"

    transcript = client.post(
        f"/internal/admin/safety/incidents/{incident_id}/full-transcript-access",
        headers={"X-Auth-Session": admin_token},
        json={"reason": "用于当前高风险工单的安全评估"},
    )
    assert transcript.status_code == 200
    assert transcript.json()["transcript"]
    with transaction() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM safety_incident_events
            WHERE incident_id = ? AND event_type = 'acknowledge'
            """,
            (incident_id,),
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            """
            SELECT reason
            FROM sensitive_access_logs
            WHERE resource_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (incident_id,),
        )
        assert "安全评估" in cur.fetchone()[0]


def test_overdue_high_risk_gate_pauses_new_invites():
    user_id = _unique("safety-overdue")
    with patch("app.services.safety.is_within_safety_coverage", return_value=True):
        with transaction() as cur:
            incident = create_or_merge_safety_incident(
                cur,
                user_id=user_id,
                session_id="session-overdue",
                source="manual",
                source_risk_level="high",
                final_risk_level="high",
                risk_flags=["manual_test"],
                reason="测试工作时段首次响应超时",
                source_evidence={"test": True},
            )
            cur.execute(
                """
                UPDATE safety_incidents
                SET first_response_due_at = ?
                WHERE incident_id = ?
                """,
                ((datetime.now() - timedelta(minutes=1)).isoformat(), incident["incident_id"]),
            )

    with patch("app.services.launch_controls.is_within_safety_coverage", return_value=True):
        with transaction() as cur:
            status = evaluate_launch_gates(cur)
    assert status["paused"] is True
    assert "high_risk_first_response_overdue" in status["reason"]

    admin_login = client.post(
        "/internal/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )
    blocked = client.post(
        "/internal/admin/invites",
        headers={"X-Auth-Session": admin_login.json()["session_token"]},
        json={"note": "should-be-blocked"},
    )
    assert blocked.status_code == 409

    with transaction() as cur:
        cur.execute(
            """
            UPDATE safety_incidents
            SET first_response_at = ?, status = 'resolved', resolved_at = ?
            WHERE incident_id = ?
            """,
            (datetime.now().isoformat(), datetime.now().isoformat(), incident["incident_id"]),
        )
        set_invite_pause(
            cur,
            paused=False,
            reason="测试完成后恢复邀请码发放",
            metadata={"test_cleanup": True},
        )


def test_alert_and_deletion_failures_pause_new_invites():
    incident_id = ""
    request_id = _unique("deletion-gate")
    now = datetime.now().isoformat()
    try:
        with patch("app.services.safety.is_within_safety_coverage", return_value=True):
            with transaction() as cur:
                incident = create_or_merge_safety_incident(
                    cur,
                    user_id=_unique("alert-gate"),
                    session_id=_unique("session"),
                    source="manual",
                    source_risk_level="high",
                    final_risk_level="high",
                    risk_flags=["manual_test"],
                    reason="测试告警通道故障闸门",
                    source_evidence={"test": True},
                )
                incident_id = incident["incident_id"]
                cur.execute(
                    """
                    UPDATE safety_incidents
                    SET alert_status = 'failed', alert_attempt_count = 5
                    WHERE incident_id = ?
                    """,
                    (incident_id,),
                )

        with transaction() as cur:
            alert_status = evaluate_launch_gates(cur)
        assert alert_status["paused"] is True
        assert "safety_alert_channel_failed" in alert_status["reason"]

        with transaction() as cur:
            cur.execute("DELETE FROM safety_incident_events WHERE incident_id = ?", (incident_id,))
            cur.execute("DELETE FROM safety_risk_evaluations WHERE incident_id = ?", (incident_id,))
            cur.execute("DELETE FROM safety_incidents WHERE incident_id = ?", (incident_id,))
            set_invite_pause(
                cur,
                paused=False,
                reason="清理告警通道故障测试",
                metadata={"test_cleanup": True},
            )
            cur.execute(
                """
                INSERT INTO data_deletion_requests (
                    request_id, user_id_hash, status, requested_at, scheduled_for,
                    backup_status, created_at, updated_at
                )
                VALUES (?, ?, 'failed', ?, ?, 'pending', ?, ?)
                """,
                (request_id, "test-user-hash", now, now, now, now),
            )

        with transaction() as cur:
            deletion_status = evaluate_launch_gates(cur)
        assert deletion_status["paused"] is True
        assert "account_deletion_failed" in deletion_status["reason"]

        with transaction() as cur:
            cur.execute(
                """
                UPDATE data_deletion_requests
                SET status = 'completed', backup_status = 'failed'
                WHERE request_id = ?
                """,
                (request_id,),
            )
            set_invite_pause(
                cur,
                paused=False,
                reason="切换到备份删除故障测试",
                metadata={"test_cleanup": True},
            )

        with transaction() as cur:
            backup_status = evaluate_launch_gates(cur)
        assert backup_status["paused"] is True
        assert "backup_deletion_failed" in backup_status["reason"]
    finally:
        with transaction() as cur:
            if incident_id:
                cur.execute("DELETE FROM safety_incident_events WHERE incident_id = ?", (incident_id,))
                cur.execute("DELETE FROM safety_risk_evaluations WHERE incident_id = ?", (incident_id,))
                cur.execute("DELETE FROM safety_incidents WHERE incident_id = ?", (incident_id,))
            cur.execute("DELETE FROM data_deletion_requests WHERE request_id = ?", (request_id,))
            set_invite_pause(
                cur,
                paused=False,
                reason="清理上线闸门测试",
                metadata={"test_cleanup": True},
            )


def test_beta_user_limit_blocks_invite_issuance():
    user_id = _unique("beta-limit")
    username = _unique("beta-limit-user")
    now = datetime.now().isoformat()
    try:
        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO users (
                    user_id, username, password_hash, is_admin, created_at, updated_at
                )
                VALUES (?, ?, NULL, 0, ?, ?)
                """,
                (user_id, username, now, now),
            )
        with patch("app.services.launch_controls.BETA_USER_LIMIT", 1):
            with transaction() as cur:
                status = get_launch_status(cur)
                assert status["at_user_limit"] is True
                assert status["beta_user_limit"] == 1
                with pytest.raises(ValueError, match="beta_user_limit_reached"):
                    assert_invite_issuance_allowed(cur)
    finally:
        with transaction() as cur:
            cur.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
