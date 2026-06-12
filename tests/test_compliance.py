from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import transaction
from app.main import app
from app.services.compliance import (
    CURRENT_POLICY_VERSION,
    process_due_account_deletions,
    process_pending_backup_deletions,
)


client = TestClient(app)
client.headers.update({"X-Backend-Token": "test-backend-token"})


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _consents() -> dict:
    return {
        "policyVersion": CURRENT_POLICY_VERSION,
        "adultConfirmed": True,
        "aiServiceConsent": True,
        "sensitiveDataConsent": True,
        "conversationStorageConsent": True,
        "longTermMemoryConsent": True,
        "humanSafetyReviewConsent": True,
    }


def _admin_token() -> str:
    response = client.post(
        "/internal/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )
    assert response.status_code == 200
    return response.json()["session_token"]


def _invite() -> str:
    response = client.post(
        "/internal/admin/invites",
        headers={"X-Auth-Session": _admin_token()},
        json={"note": "compliance-test"},
    )
    assert response.status_code == 200
    return response.json()["invite"]["code"]


def _register_and_login(prefix: str) -> dict:
    username = _name(prefix)
    password = "password-123"
    response = client.post(
        "/internal/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "inviteCode": _invite(),
            **_consents(),
        },
    )
    assert response.status_code == 200, response.text
    login = client.post(
        "/internal/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    return {
        "user_id": response.json()["user"]["user_id"],
        "username": username,
        "password": password,
        "session_token": login.json()["session_token"],
    }


def test_registration_requires_all_separate_consents_without_consuming_invite():
    invite_code = _invite()
    username = _name("missing-consent")
    incomplete = client.post(
        "/internal/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "password-123",
            "inviteCode": invite_code,
            **{**_consents(), "humanSafetyReviewConsent": False},
        },
    )
    assert incomplete.status_code == 400

    complete = client.post(
        "/internal/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "password-123",
            "inviteCode": invite_code,
            **_consents(),
        },
    )
    assert complete.status_code == 200, complete.text
    user_id = complete.json()["user"]["user_id"]
    with transaction() as cur:
        cur.execute(
            """
            SELECT consent_key, policy_version, granted
            FROM user_consents
            WHERE user_id = ?
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    assert len(rows) == 6
    assert {row[1] for row in rows} == {CURRENT_POLICY_VERSION}
    assert all(row[2] == 1 for row in rows)


def test_account_export_complaint_freeze_cancel_and_due_deletion():
    user = _register_and_login("deletion")
    auth_headers = {"X-Auth-Session": user["session_token"]}
    session_id = client.get(f"/session/status/{user['user_id']}").json()["session_id"]
    client.post(
        "/session-message",
        headers=auth_headers,
        json={
            "user_id": user["user_id"],
            "session_id": session_id,
            "role": "user",
            "content": "这是一条用于导出和删除测试的消息。",
        },
    )
    complaint = client.post(
        "/internal/complaints",
        headers=auth_headers,
        json={"category": "privacy", "content": "我希望确认数据导出与删除流程是否正常。"},
    )
    assert complaint.status_code == 200

    exported = client.get("/internal/account/export", headers=auth_headers)
    assert exported.status_code == 200
    export_payload = exported.json()
    assert export_payload["consents"]["complete"] is True
    assert len(export_payload["messages"]) == 1
    assert len(export_payload["complaints"]) == 1

    first_request = client.post(
        "/internal/account/deletion-request",
        headers=auth_headers,
        json={"confirm_text": "删除我的账号"},
    )
    assert first_request.status_code == 200, first_request.text
    first = first_request.json()
    assert first["status"] == "pending"
    assert first["account_frozen"] is True
    requested_at = datetime.fromisoformat(first["requested_at"])
    scheduled_for = datetime.fromisoformat(first["scheduled_for"])
    backup_delete_by = datetime.fromisoformat(first["backup_delete_by"])
    assert timedelta(days=6, hours=23) < scheduled_for - requested_at < timedelta(days=7, hours=1)
    assert timedelta(days=29, hours=23) < backup_delete_by - requested_at < timedelta(days=30, hours=1)
    assert export_payload["consents"]["phone_contacts_enabled"] is False

    me = client.get("/internal/auth/me", headers=auth_headers)
    assert me.json()["authenticated"] is False
    status = client.get(
        "/internal/account/deletion-status",
        params={
            "request_id": first["request_id"],
            "cancellation_token": first["cancellation_token"],
        },
    )
    assert status.status_code == 200
    assert status.json()["status"] == "pending"

    cancelled = client.post(
        "/internal/account/deletion-cancel",
        json={
            "request_id": first["request_id"],
            "cancellation_token": first["cancellation_token"],
        },
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    login = client.post(
        "/internal/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    assert login.status_code == 200
    second_headers = {"X-Auth-Session": login.json()["session_token"]}
    second_request = client.post(
        "/internal/account/deletion-request",
        headers=second_headers,
        json={"confirm_text": "删除我的账号"},
    )
    assert second_request.status_code == 200
    second = second_request.json()

    with transaction() as cur:
        cur.execute(
            """
            UPDATE data_deletion_requests
            SET scheduled_for = ?
            WHERE request_id = ?
            """,
            ((datetime.now() - timedelta(seconds=1)).isoformat(), second["request_id"]),
        )
    result = process_due_account_deletions()
    assert result["completed"] >= 1

    completed_status = client.get(
        "/internal/account/deletion-status",
        params={
            "request_id": second["request_id"],
            "cancellation_token": second["cancellation_token"],
        },
    )
    assert completed_status.status_code == 200
    assert completed_status.json()["status"] == "completed"
    assert completed_status.json()["certificate_id"].startswith("deletion_certificate_")
    assert completed_status.json()["backup_status"] == "scheduled"

    webhook_response = Mock()
    webhook_response.raise_for_status.return_value = None
    with (
        patch(
            "app.services.compliance.BACKUP_DELETION_WEBHOOK_URL",
            "https://backup.example.invalid/delete",
        ),
        patch("app.services.compliance.httpx.post", return_value=webhook_response),
    ):
        backup_result = process_pending_backup_deletions()
    assert backup_result["completed"] >= 1
    backup_status = client.get(
        "/internal/account/deletion-status",
        params={
            "request_id": second["request_id"],
            "cancellation_token": second["cancellation_token"],
        },
    )
    assert backup_status.json()["backup_status"] == "completed"

    with transaction() as cur:
        cur.execute("SELECT COUNT(*) FROM users WHERE user_id = ?", (user["user_id"],))
        assert cur.fetchone()[0] == 0
        cur.execute(
            """
            SELECT deletion_manifest_json
            FROM data_deletion_requests
            WHERE request_id = ?
            """,
            (second["request_id"],),
        )
        manifest = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM compliance_audit_logs
            WHERE resource_id = ? AND action = 'account_deletion_completed'
            """,
            (second["request_id"],),
        )
        audit_count = cur.fetchone()[0]
    assert "backup_action" in manifest
    assert audit_count == 1
