import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


TEST_DB = Path(tempfile.gettempdir()) / "mvp-test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB}")
os.environ.setdefault("TASK_WORKER_ENABLED", "false")
os.environ.setdefault("ENABLE_DEBUG_ENDPOINTS", "false")
os.environ.setdefault("AUTH_SECRET", "test-auth-secret")
os.environ.setdefault("BACKEND_SHARED_TOKEN", "test-backend-token")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin-password")

if "app.main" not in sys.modules:
    for path in [TEST_DB, TEST_DB.with_name(f"{TEST_DB.name}-wal"), TEST_DB.with_name(f"{TEST_DB.name}-shm")]:
        if path.exists():
            path.unlink()

from fastapi.testclient import TestClient

from app import db as db_module
from app.db import transaction
from app.main import app
from app.services.auth import create_auth_session, hash_password


client = TestClient(app)
client.headers.update({"X-Backend-Token": "test-backend-token"})


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_email(prefix: str) -> str:
    return f"{unique_name(prefix)}@example.com"


def login_admin() -> str:
    response = client.post(
        "/internal/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_token"]


def create_invite(admin_token: str, note: str = "") -> str:
    response = client.post(
        "/internal/admin/invites",
        headers={"X-Auth-Session": admin_token},
        json={"note": note},
    )
    assert response.status_code == 200, response.text
    return response.json()["invite"]["code"]


def create_regular_user(admin_token: str, note: str = "user"):
    invite_code = create_invite(admin_token, note=note)
    username = unique_name(note)
    email = unique_email(note)
    password = "user-password-123"
    registered = client.post(
        "/internal/auth/register",
        json={"username": username, "email": email, "password": password, "inviteCode": invite_code},
    )
    assert registered.status_code == 200, registered.text
    logged_in = client.post(
        "/internal/auth/login",
        json={"username": username, "password": password},
    )
    assert logged_in.status_code == 200, logged_in.text
    return {
        "username": username,
        "email": email,
        "password": password,
        "user_id": registered.json()["user"]["user_id"],
        "session_token": logged_in.json()["session_token"],
    }


def create_extra_admin(note: str = "admin"):
    user_id = f"admin-{uuid.uuid4().hex}"
    username = unique_name(note)
    now = datetime.now().isoformat()
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO users (user_id, username, password_hash, is_admin, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (user_id, username, hash_password("admin-password-123"), now, now),
        )
        session = create_auth_session(cur, user_id)
    return {
        "user_id": user_id,
        "username": username,
        "session_token": session["session_token"],
    }


def collect_keys(value):
    if isinstance(value, dict):
        keys = []
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(collect_keys(item))
        return keys
    if isinstance(value, list):
        keys = []
        for item in value:
            keys.extend(collect_keys(item))
        return keys
    return []


def latest_audit(action: str, target_user_id: str):
    with transaction() as cur:
        cur.execute(
            """
            SELECT action, actor_user_id, target_user_id, success, error, ip_hash, user_agent
            FROM admin_audit_logs
            WHERE action = ? AND target_user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (action, target_user_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "action": row[0],
        "actor_user_id": row[1],
        "target_user_id": row[2],
        "success": bool(row[3]),
        "error": row[4],
        "ip_hash": row[5],
        "user_agent": row[6],
    }


def extract_reset_token(reset_url: str) -> str:
    token_values = parse_qs(urlparse(reset_url).query).get("token", [])
    assert token_values, reset_url
    return token_values[0]


def extract_token_from_email_body(body_text: str, path: str) -> str:
    for line in body_text.splitlines():
        if path in line and "token=" in line:
            return extract_reset_token(line.strip())
    raise AssertionError(body_text)


def extract_token_from_send_email(send_email, path: str = "/reset-password") -> str:
    args = send_email.call_args.args
    assert len(args) >= 3, args
    return extract_token_from_email_body(args[2], path)


def mark_email_verified(user_id: str, email: str | None = None) -> str:
    verified_at = "2026-01-01T00:00:00"
    with transaction() as cur:
        if email is None:
            cur.execute(
                """
                UPDATE users
                SET email_verified_at = ?
                WHERE user_id = ?
                """,
                (verified_at, user_id),
            )
        else:
            cur.execute(
                """
                UPDATE users
                SET email = ?, email_verified_at = ?
                WHERE user_id = ?
                """,
                (email, verified_at, user_id),
            )
    return verified_at


class AuthApiTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        client.close()

    def test_invite_register_login_me_logout_flow(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="flow")
        username = unique_name("user")
        password = "user-password-123"

        registered = client.post(
            "/internal/auth/register",
            json={
                "username": username,
                "email": unique_email("flow"),
                "password": password,
                "inviteCode": invite_code,
            },
        )
        self.assertEqual(registered.status_code, 200)
        user_id = registered.json()["user"]["user_id"]

        reused = client.post(
            "/internal/auth/register",
            json={
                "username": unique_name("user"),
                "email": unique_email("flow-reused"),
                "password": password,
                "inviteCode": invite_code,
            },
        )
        self.assertEqual(reused.status_code, 400)

        logged_in = client.post(
            "/internal/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(logged_in.status_code, 200)
        session_token = logged_in.json()["session_token"]

        me = client.get("/internal/auth/me", headers={"X-Auth-Session": session_token})
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json()["authenticated"])
        self.assertEqual(me.json()["user"]["user_id"], user_id)

        logout = client.post("/internal/auth/logout", headers={"X-Auth-Session": session_token})
        self.assertEqual(logout.status_code, 200)

        after_logout = client.get("/internal/auth/me", headers={"X-Auth-Session": session_token})
        self.assertEqual(after_logout.status_code, 200)
        self.assertFalse(after_logout.json()["authenticated"])

    def test_register_saves_normalized_unique_email(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="email-normalize")
        username = unique_name("email")
        email = f"  {unique_name('Email.User')}@Example.COM  "

        with patch("app.services.auth.send_email_message") as send_email:
            registered = client.post(
                "/internal/auth/register",
                json={
                    "username": username,
                    "email": email,
                    "password": "user-password-123",
                    "inviteCode": invite_code,
                },
            )

        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertEqual(send_email.call_count, 1)
        normalized_email = email.strip().lower()
        raw_verify_token = extract_token_from_send_email(send_email, "/verify-email")
        with transaction() as cur:
            cur.execute(
                "SELECT email, email_verified_at FROM users WHERE username = ?",
                (username,),
            )
            row = cur.fetchone()
            cur.execute(
                """
                SELECT token_hash
                FROM email_verification_tokens
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (registered.json()["user"]["user_id"],),
            )
            token_row = cur.fetchone()
            cur.execute(
                """
                SELECT body_text
                FROM email_outbox
                WHERE recipient_email = ? AND message_type = 'email_verification'
                ORDER BY id DESC
                LIMIT 1
                """,
                (normalized_email,),
            )
            outbox_row = cur.fetchone()
        self.assertEqual(row[0], normalized_email)
        self.assertIsNone(row[1])
        self.assertIsNotNone(token_row)
        self.assertNotEqual(token_row[0], raw_verify_token)
        self.assertNotIn(raw_verify_token, token_row[0])
        self.assertIsNotNone(outbox_row)
        self.assertIn("{VERIFY_LINK}", outbox_row[0])
        self.assertNotIn(raw_verify_token, outbox_row[0])

        second_invite = create_invite(admin_token, note="email-duplicate")
        duplicate = client.post(
            "/internal/auth/register",
            json={
                "username": unique_name("email"),
                "email": normalized_email.upper(),
                "password": "user-password-123",
                "inviteCode": second_invite,
            },
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"], "email_exists")

    def test_legacy_user_without_email_can_login_and_use_account_page(self):
        username = unique_name("legacy")
        password = "legacy-password-123"
        user_id = f"user_{uuid.uuid4().hex}"
        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO users (
                    user_id, username, email, email_verified_at, password_hash,
                    is_admin, created_at, updated_at
                )
                VALUES (?, ?, NULL, NULL, ?, 0, ?, ?)
                """,
                (user_id, username, hash_password(password), "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )

        logged_in = client.post(
            "/internal/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(logged_in.status_code, 200, logged_in.text)

        account = client.get(
            "/internal/auth/account",
            headers={"X-Auth-Session": logged_in.json()["session_token"]},
        )
        self.assertEqual(account.status_code, 200)
        payload = account.json()["account"]
        self.assertFalse(payload["has_email"])
        self.assertFalse(payload["email_verified"])
        self.assertEqual(payload["email"], "")

        new_email = unique_email("legacy-bind")
        with patch("app.services.auth.send_email_message") as send_email:
            requested = client.post(
                "/internal/auth/email/request-verification",
                headers={"X-Auth-Session": logged_in.json()["session_token"]},
                json={"email": new_email.upper()},
            )
        self.assertEqual(requested.status_code, 200, requested.text)
        self.assertEqual(send_email.call_count, 1)
        verify_token = extract_token_from_send_email(send_email, "/verify-email")

        with transaction() as cur:
            cur.execute(
                """
                SELECT email, email_verified_at
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            )
            bind_row = cur.fetchone()
            cur.execute(
                """
                SELECT body_text
                FROM email_outbox
                WHERE recipient_email = ? AND message_type = 'email_verification'
                ORDER BY id DESC
                LIMIT 1
                """,
                (new_email,),
            )
            outbox_row = cur.fetchone()
        self.assertEqual(bind_row[0], new_email)
        self.assertIsNone(bind_row[1])
        self.assertIsNotNone(outbox_row)
        self.assertIn("{VERIFY_LINK}", outbox_row[0])
        self.assertNotIn(verify_token, outbox_row[0])

        verified = client.post(
            "/internal/auth/email/confirm",
            json={"token": verify_token},
        )
        self.assertEqual(verified.status_code, 200, verified.text)

    def test_invite_can_be_revoked_before_use(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="revoke")

        invites = client.get("/internal/admin/invites", headers={"X-Auth-Session": admin_token}).json()["invites"]
        invite = next(item for item in invites if item["note"] == "revoke")

        revoked = client.request(
            "DELETE",
            "/internal/admin/invites",
            headers={"X-Auth-Session": admin_token},
            json={"invite_id": invite["id"]},
        )
        self.assertEqual(revoked.status_code, 200)

        registered = client.post(
            "/internal/auth/register",
            json={
                "username": unique_name("user"),
                "email": unique_email("revoke"),
                "password": "user-password-123",
                "inviteCode": invite_code,
            },
        )
        self.assertEqual(registered.status_code, 400)

    def test_email_verification_confirms_email_and_marks_token_used(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="verify-email")
        username = unique_name("verify")
        password = "user-password-123"
        email = unique_email("verify").upper()

        with patch("app.services.auth.send_email_message") as send_email:
            registered = client.post(
                "/internal/auth/register",
                json={
                    "username": username,
                    "email": email,
                    "password": password,
                    "inviteCode": invite_code,
                },
            )
        self.assertEqual(registered.status_code, 200, registered.text)
        user_id = registered.json()["user"]["user_id"]
        token = extract_token_from_send_email(send_email, "/verify-email")

        confirmed = client.post(
            "/internal/auth/email/confirm",
            json={"token": token},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertTrue(confirmed.json()["success"])
        self.assertNotIn(token, json.dumps(confirmed.json(), ensure_ascii=False))

        with transaction() as cur:
            cur.execute(
                """
                SELECT email, email_verified_at
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            )
            user_row = cur.fetchone()
            cur.execute(
                """
                SELECT used_at
                FROM email_verification_tokens
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            token_row = cur.fetchone()

        self.assertEqual(user_row[0], email.lower())
        self.assertTrue(user_row[1])
        self.assertTrue(token_row[0])

        reused = client.post(
            "/internal/auth/email/confirm",
            json={"token": token},
        )
        self.assertEqual(reused.status_code, 400)
        self.assertEqual(reused.json()["error"], "email_verification_invalid")

        logged_in = client.post(
            "/internal/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(logged_in.status_code, 200, logged_in.text)
        account = client.get(
            "/internal/auth/account",
            headers={"X-Auth-Session": logged_in.json()["session_token"]},
        )
        self.assertEqual(account.status_code, 200)
        self.assertTrue(account.json()["account"]["email_verified"])

    def test_plain_secrets_are_not_stored(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="hash-check")
        username = unique_name("hash")
        password = "user-password-123"

        client.post(
            "/internal/auth/register",
            json={
                "username": username,
                "email": unique_email("hash"),
                "password": password,
                "inviteCode": invite_code,
            },
        )
        login = client.post(
            "/internal/auth/login",
            json={"username": username, "password": password},
        ).json()
        session_token = login["session_token"]

        with transaction() as cur:
            cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
            password_hash = cur.fetchone()[0]
            cur.execute("SELECT code_hash FROM invite_codes WHERE note = ?", ("hash-check",))
            code_hash = cur.fetchone()[0]
            cur.execute(
                """
                SELECT token_hash
                FROM auth_sessions
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (login["user"]["user_id"],),
            )
            token_hash = cur.fetchone()[0]

        self.assertNotEqual(password_hash, password)
        self.assertNotIn(password, password_hash)
        self.assertNotEqual(code_hash, invite_code)
        self.assertNotIn(invite_code, code_hash)
        self.assertNotEqual(token_hash, session_token)
        self.assertNotIn(session_token, token_hash)

    def test_password_reset_request_is_stable_and_stores_only_token_hash(self):
        admin_token = login_admin()
        regular = create_regular_user(admin_token, note="reset-request")
        unverified_headers = {"X-Forwarded-For": "198.51.100.11"}
        verified_headers = {"X-Forwarded-For": "198.51.100.12"}

        with patch("app.services.auth.send_email_message") as send_email:
            unverified = client.post(
                "/internal/auth/password-reset/request",
                headers=unverified_headers,
                json={"email": regular["email"].upper()},
            )
            missing_before_verify = client.post(
                "/internal/auth/password-reset/request",
                headers=unverified_headers,
                json={"email": unique_email("missing-before-verify")},
            )

        self.assertEqual(unverified.status_code, 200)
        self.assertEqual(missing_before_verify.status_code, 200)
        self.assertEqual(unverified.json(), missing_before_verify.json())
        self.assertEqual(send_email.call_count, 0)

        mark_email_verified(regular["user_id"])

        with patch("app.services.auth.send_email_message") as send_email:
            existing = client.post(
                "/internal/auth/password-reset/request",
                headers=verified_headers,
                json={"email": regular["email"].upper()},
            )
            missing = client.post(
                "/internal/auth/password-reset/request",
                headers=verified_headers,
                json={"email": unique_email("missing")},
            )
            cooled_down = client.post(
                "/internal/auth/password-reset/request",
                headers=verified_headers,
                json={"email": regular["email"]},
            )

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(cooled_down.status_code, 200)
        self.assertEqual(existing.json(), missing.json())
        self.assertEqual(existing.json(), cooled_down.json())
        self.assertEqual(send_email.call_count, 1)

        to_email, subject, body_text = send_email.call_args.args[:3]
        self.assertEqual(to_email, regular["email"])
        self.assertEqual(subject, "重置你的密码")
        self.assertIn("/reset-password?token=", body_text)
        raw_token = extract_token_from_email_body(body_text, "/reset-password")

        with transaction() as cur:
            cur.execute(
                """
                SELECT token_hash, request_ip_hash, user_agent
                FROM password_reset_tokens
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (regular["user_id"],),
            )
            token_row = cur.fetchone()
            cur.execute(
                """
                SELECT body_text, status, attempt_count
                FROM email_outbox
                WHERE recipient_email = ? AND message_type = 'password_reset'
                ORDER BY id DESC
                LIMIT 1
                """,
                (regular["email"],),
            )
            outbox_row = cur.fetchone()

        self.assertIsNotNone(token_row)
        self.assertNotEqual(token_row[0], raw_token)
        self.assertNotIn(raw_token, token_row[0])
        self.assertTrue(token_row[1])
        self.assertIn("testclient", token_row[2].lower())
        self.assertIsNotNone(outbox_row)
        self.assertIn("{RESET_LINK}", outbox_row[0])
        self.assertNotIn(raw_token, outbox_row[0])
        self.assertEqual(outbox_row[1], "sent")
        self.assertEqual(outbox_row[2], 1)

        serialized = json.dumps([existing.json(), missing.json(), cooled_down.json()], ensure_ascii=False)
        self.assertNotIn(raw_token, serialized)

        exported = client.get(
            f"/internal/admin/users/{regular['user_id']}/export",
            headers={"X-Auth-Session": admin_token},
        )
        self.assertEqual(exported.status_code, 200)
        self.assertNotIn(raw_token, json.dumps(exported.json(), ensure_ascii=False))

    def test_password_reset_confirm_updates_password_and_revokes_sessions(self):
        admin_token = login_admin()
        regular = create_regular_user(admin_token, note="reset-confirm")
        mark_email_verified(regular["user_id"])
        reset_headers = {"X-Forwarded-For": "198.51.100.21"}
        second_login = client.post(
            "/internal/auth/login",
            json={"username": regular["username"], "password": regular["password"]},
        )
        self.assertEqual(second_login.status_code, 200)
        second_session = second_login.json()["session_token"]

        with patch("app.services.auth.send_email_message") as send_email:
            requested = client.post(
                "/internal/auth/password-reset/request",
                headers=reset_headers,
                json={"email": regular["email"]},
            )
        self.assertEqual(requested.status_code, 200)
        token = extract_token_from_send_email(send_email, "/reset-password")
        new_password = "new-password-456"

        confirmed = client.post(
            "/internal/auth/password-reset/confirm",
            json={"token": token, "new_password": new_password},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertTrue(confirmed.json()["success"])
        self.assertNotIn(token, json.dumps(confirmed.json(), ensure_ascii=False))

        old_login = client.post(
            "/internal/auth/login",
            json={"username": regular["username"], "password": regular["password"]},
        )
        self.assertEqual(old_login.status_code, 401)

        new_login = client.post(
            "/internal/auth/login",
            json={"username": regular["username"], "password": new_password},
        )
        self.assertEqual(new_login.status_code, 200)

        for old_session in [regular["session_token"], second_session]:
            me = client.get("/internal/auth/me", headers={"X-Auth-Session": old_session})
            self.assertEqual(me.status_code, 200)
            self.assertFalse(me.json()["authenticated"])

        reused = client.post(
            "/internal/auth/password-reset/confirm",
            json={"token": token, "new_password": "another-password-789"},
        )
        self.assertEqual(reused.status_code, 400)
        self.assertEqual(reused.json()["error"], "password_reset_invalid")

        with transaction() as cur:
            cur.execute(
                """
                SELECT used_at
                FROM password_reset_tokens
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (regular["user_id"],),
            )
            used_at = cur.fetchone()[0]
        self.assertTrue(used_at)

    def test_password_reset_rejects_expired_fake_and_weak_requests_stably(self):
        admin_token = login_admin()
        regular = create_regular_user(admin_token, note="reset-invalid")
        mark_email_verified(regular["user_id"])
        reset_headers = {"X-Forwarded-For": "198.51.100.31"}

        fake = client.post(
            "/internal/auth/password-reset/confirm",
            json={"token": "not-a-real-token", "new_password": "valid-password-123"},
        )
        self.assertEqual(fake.status_code, 400)
        self.assertEqual(fake.json()["error"], "password_reset_invalid")

        with patch("app.services.auth.send_email_message") as send_email:
            requested = client.post(
                "/internal/auth/password-reset/request",
                headers=reset_headers,
                json={"email": regular["email"]},
            )
        self.assertEqual(requested.status_code, 200)
        token = extract_token_from_send_email(send_email, "/reset-password")
        with transaction() as cur:
            cur.execute(
                """
                UPDATE password_reset_tokens
                SET expires_at = ?
                WHERE user_id = ?
                """,
                ("2000-01-01T00:00:00", regular["user_id"]),
            )

        expired = client.post(
            "/internal/auth/password-reset/confirm",
            json={"token": token, "new_password": "valid-password-123"},
        )
        self.assertEqual(expired.status_code, 400)
        self.assertEqual(expired.json()["error"], fake.json()["error"])
        self.assertEqual(expired.json()["message"], fake.json()["message"])

        weak = client.post(
            "/internal/auth/password-reset/confirm",
            json={"token": token, "new_password": "short"},
        )
        self.assertEqual(weak.status_code, 400)
        self.assertEqual(weak.json()["error"], "weak_password")

    def test_password_reset_exception_responses_and_logs_are_sanitized(self):
        admin_token = login_admin()
        regular = create_regular_user(admin_token, note="reset-sanitize")
        mark_email_verified(regular["user_id"])
        reset_headers = {"X-Forwarded-For": "198.51.100.41"}

        with patch(
            "app.services.auth.send_email_message",
            side_effect=RuntimeError("smtp secret SMTP_PASSWORD traceback test-backend-token"),
        ), self.assertLogs("app.services.auth", level="WARNING") as service_logs:
            smtp_failed = client.post(
                "/internal/auth/password-reset/request",
                headers=reset_headers,
                json={"email": regular["email"]},
            )
        self.assertEqual(smtp_failed.status_code, 200)

        with patch(
            "app.routers.auth.transaction",
            side_effect=RuntimeError("secret sql BACKEND_SHARED_TOKEN traceback test-backend-token"),
        ), self.assertLogs("app.routers.auth", level="WARNING") as router_logs:
            db_failed = client.post(
                "/internal/auth/password-reset/request",
                headers={"X-Forwarded-For": "198.51.100.42"},
                json={"email": regular["email"]},
            )
            confirm_failed = client.post(
                "/internal/auth/password-reset/confirm",
                json={"token": "fake-token", "new_password": "valid-password-123"},
            )

        payload_text = json.dumps(
            [smtp_failed.json(), db_failed.json(), confirm_failed.json()],
            ensure_ascii=False,
        )
        log_text = "\n".join(service_logs.output + router_logs.output)
        for forbidden in [
            "smtp secret",
            "secret sql",
            "SMTP_PASSWORD",
            "BACKEND_SHARED_TOKEN",
            "test-backend-token",
            "traceback",
        ]:
            self.assertNotIn(forbidden, payload_text)
            self.assertNotIn(forbidden, log_text)

    def test_regular_user_cannot_manage_invites(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="regular")
        username = unique_name("regular")
        password = "user-password-123"
        client.post(
            "/internal/auth/register",
            json={
                "username": username,
                "email": unique_email("regular"),
                "password": password,
                "inviteCode": invite_code,
            },
        )
        login = client.post(
            "/internal/auth/login",
            json={"username": username, "password": password},
        ).json()

        response = client.post(
            "/internal/admin/invites",
            headers={"X-Auth-Session": login["session_token"]},
            json={"note": "should-fail"},
        )

        self.assertEqual(response.status_code, 403)

    def test_regular_user_cannot_manage_users(self):
        admin_token = login_admin()
        regular = create_regular_user(admin_token, note="regular-users")

        response = client.get(
            "/internal/admin/users",
            headers={"X-Auth-Session": regular["session_token"]},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "admin_required")

        export_response = client.get(
            f"/internal/admin/users/{regular['user_id']}/export",
            headers={"X-Auth-Session": regular["session_token"]},
        )
        self.assertEqual(export_response.status_code, 403)
        self.assertEqual(export_response.json()["error"], "admin_required")

        disable_response = client.post(
            f"/internal/admin/users/{regular['user_id']}/disable",
            headers={"X-Auth-Session": regular["session_token"]},
        )
        self.assertEqual(disable_response.status_code, 403)
        self.assertEqual(disable_response.json()["error"], "admin_required")

    def test_admin_can_reset_only_own_latest_session_to_yesterday(self):
        admin_token = login_admin()
        admin_user_id = client.get(
            "/internal/auth/me",
            headers={"X-Auth-Session": admin_token},
        ).json()["user"]["user_id"]
        admin_session = client.get(f"/session/status/{admin_user_id}").json()
        regular = create_regular_user(admin_token, note="reset-other")
        regular_session = client.get(f"/session/status/{regular['user_id']}").json()

        response = client.post(
            "/internal/admin/self/session/reset-to-yesterday",
            headers={"X-Auth-Session": admin_token},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["shifted_session_id"], admin_session["session_id"])
        self.assertEqual(data["new_session"]["status"], "pending")
        self.assertFalse(data["new_session"]["timer_started"])
        self.assertNotEqual(data["new_session"]["session_id"], admin_session["session_id"])
        self.assertIsNone(data["new_session"]["started_at"])
        self.assertEqual(datetime.fromisoformat(data["new_session"]["created_at"]).date(), datetime.now().date())

        yesterday = datetime.now().date() - timedelta(days=1)
        with transaction() as cur:
            cur.execute(
                """
                SELECT user_id, started_at, auto_close_at, ended_at, final_saved_at,
                       status, stage, close_reason
                FROM sessions
                WHERE session_id = ?
                """,
                (admin_session["session_id"],),
            )
            shifted = cur.fetchone()
            cur.execute(
                """
                SELECT status, stage, close_reason
                FROM sessions
                WHERE session_id = ?
                """,
                (regular_session["session_id"],),
            )
            untouched_regular = cur.fetchone()

        self.assertEqual(shifted[0], admin_user_id)
        for value in shifted[1:5]:
            self.assertEqual(datetime.fromisoformat(value).date(), yesterday)
        self.assertEqual(shifted[3], shifted[2])
        self.assertEqual(shifted[4], shifted[3])
        self.assertEqual(shifted[5], "ended")
        self.assertEqual(shifted[6], "ended")
        self.assertEqual(shifted[7], "admin_self_session_reset")
        self.assertEqual(untouched_regular[0], "pending")
        self.assertEqual(untouched_regular[1], "not_started")
        self.assertIsNone(untouched_regular[2])

    def test_admin_session_reset_requires_admin_login_and_existing_session(self):
        admin_token = login_admin()
        regular = create_regular_user(admin_token, note="reset-forbidden")
        empty_admin = create_extra_admin(note="reset-empty-admin")

        missing_session = client.post("/internal/admin/self/session/reset-to-yesterday")
        self.assertEqual(missing_session.status_code, 401)

        forbidden = client.post(
            "/internal/admin/self/session/reset-to-yesterday",
            headers={"X-Auth-Session": regular["session_token"]},
        )
        self.assertEqual(forbidden.status_code, 403)

        not_found = client.post(
            "/internal/admin/self/session/reset-to-yesterday",
            headers={"X-Auth-Session": empty_admin["session_token"]},
        )
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json()["error"], "session_not_found")

    def test_admin_user_export_is_redacted_and_disable_revokes_sessions(self):
        admin_token = login_admin()
        admin_user_id = client.get(
            "/internal/auth/me",
            headers={"X-Auth-Session": admin_token},
        ).json()["user"]["user_id"]
        regular = create_regular_user(admin_token, note="export")
        user_id = regular["user_id"]

        session = client.get(f"/session/status/{user_id}").json()
        session_id = session["session_id"]
        client.post(
            "/profile",
            json={"user_id": user_id, "profile_memory": "长期画像：用户关注工作压力。"},
        )
        client.post(
            "/care-plan",
            json={"user_id": user_id, "plan_text": "计划：记录情绪并拆小行动。"},
        )
        for content in [
            "最近工作压力很大，晚上也会反复想项目。",
            "下次希望继续整理睡眠变差和项目拖延之间的关系。",
            "请不要导出 BACKEND_SHARED_TOKEN、DIFY_API_KEY、test-backend-token 或 test-dify-secret。",
        ]:
            client.post(
                "/session-message",
                json={"user_id": user_id, "session_id": session_id, "role": "user", "content": content},
            )
        client.post(
            "/memory",
            json={
                "user_id": user_id,
                "session_id": session_id,
                "memory": "用户希望下次继续讨论工作压力和睡眠。",
            },
        )
        client.post("/session/finalize", json={"user_id": user_id, "session_id": session_id})

        listed = client.get("/internal/admin/users", headers={"X-Auth-Session": admin_token})
        self.assertEqual(listed.status_code, 200)
        listed_user = next(item for item in listed.json()["users"] if item["user_id"] == user_id)
        self.assertTrue(listed_user["has_email"])
        self.assertFalse(listed_user["email_verified"])
        self.assertTrue(listed_user["email_masked"])
        self.assertNotEqual(listed_user["email_masked"], regular["email"])

        with patch.dict(os.environ, {"DIFY_API_KEY": "test-dify-secret"}, clear=False):
            exported = client.get(
                f"/internal/admin/users/{user_id}/export",
                headers={"X-Auth-Session": admin_token},
            )
        self.assertEqual(exported.status_code, 200)
        payload = exported.json()
        self.assertEqual(payload["user"]["user_id"], user_id)
        self.assertNotIn("email", payload["user"])
        self.assertIn("email_masked", payload["user"])
        self.assertNotEqual(payload["user"]["email_masked"], regular["email"])
        self.assertIn("profile", payload)
        self.assertIn("care_plan", payload)
        self.assertGreaterEqual(len(payload["sessions"]), 1)
        self.assertGreaterEqual(len(payload["messages"]), 3)
        self.assertGreaterEqual(len(payload["memories"]), 1)
        self.assertIn("counts", payload)
        self.assertIn("redactions", payload)
        self.assertEqual(payload["counts"]["sessions"], len(payload["sessions"]))
        self.assertEqual(payload["counts"]["messages"], len(payload["messages"]))
        self.assertEqual(payload["counts"]["memories"], len(payload["memories"]))
        self.assertIn("password", " ".join(payload["redactions"]))
        self.assertIn("token", " ".join(payload["redactions"]))
        self.assertIn("hash", " ".join(payload["redactions"]))
        self.assertIn("key", " ".join(payload["redactions"]))
        self.assertIn("secret", " ".join(payload["redactions"]))

        for key in collect_keys(payload):
            lowered = key.lower()
            self.assertNotIn("password", lowered)
            self.assertNotIn("token", lowered)
            self.assertNotIn("secret", lowered)
            self.assertNotIn("key", lowered)
            self.assertNotIn("_hash", lowered)

        serialized = json.dumps(payload, ensure_ascii=False)
        for forbidden in [
            "password_hash",
            "token_hash",
            "code_hash",
            "BACKEND_SHARED_TOKEN",
            "DIFY_API_KEY",
            "Dify Key",
            "test-backend-token",
            "test-dify-secret",
            regular["password"],
            regular["session_token"],
        ]:
            self.assertNotIn(forbidden, serialized)

        export_audit = latest_audit("admin_user_export", user_id)
        self.assertIsNotNone(export_audit)
        self.assertTrue(export_audit["success"])
        self.assertEqual(export_audit["actor_user_id"], admin_user_id)
        self.assertEqual(export_audit["target_user_id"], user_id)
        self.assertTrue(export_audit["ip_hash"])
        self.assertNotIn("test-backend-token", export_audit["user_agent"] or "")

        disabled = client.post(
            f"/internal/admin/users/{user_id}/disable",
            headers={"X-Auth-Session": admin_token},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertTrue(disabled.json()["success"])
        self.assertTrue(disabled.json()["disabled_at"])
        self.assertGreaterEqual(disabled.json()["revoked_sessions"], 1)

        disable_audit = latest_audit("admin_user_disable", user_id)
        self.assertIsNotNone(disable_audit)
        self.assertTrue(disable_audit["success"])
        self.assertEqual(disable_audit["actor_user_id"], admin_user_id)
        self.assertEqual(disable_audit["target_user_id"], user_id)

        after_disable = client.get(
            "/internal/auth/me",
            headers={"X-Auth-Session": regular["session_token"]},
        )
        self.assertEqual(after_disable.status_code, 200)
        self.assertFalse(after_disable.json()["authenticated"])

        relogin = client.post(
            "/internal/auth/login",
            json={"username": regular["username"], "password": regular["password"]},
        )
        self.assertEqual(relogin.status_code, 401)

    def test_admin_audit_records_failures_and_audit_write_failure_is_hidden(self):
        admin_token = login_admin()
        missing_user_id = f"missing-{uuid.uuid4().hex}"

        missing = client.get(
            f"/internal/admin/users/{missing_user_id}/export",
            headers={"X-Auth-Session": admin_token},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"], "user_not_found")

        failure_audit = latest_audit("admin_user_export", missing_user_id)
        self.assertIsNotNone(failure_audit)
        self.assertFalse(failure_audit["success"])
        self.assertEqual(failure_audit["error"], "user_not_found")

        regular = create_regular_user(admin_token, note="audit-hidden")
        with patch(
            "app.routers.admin.record_admin_audit",
            side_effect=RuntimeError("audit secret sql traceback"),
        ):
            exported = client.get(
                f"/internal/admin/users/{regular['user_id']}/export",
                headers={"X-Auth-Session": admin_token},
            )

        self.assertEqual(exported.status_code, 200)
        serialized = json.dumps(exported.json(), ensure_ascii=False)
        self.assertNotIn("audit secret", serialized)
        self.assertNotIn("traceback", serialized.lower())

    def test_admin_cannot_disable_self_or_admin(self):
        admin_token = login_admin()
        me = client.get("/internal/auth/me", headers={"X-Auth-Session": admin_token}).json()
        admin_user_id = me["user"]["user_id"]

        disable_self = client.post(
            f"/internal/admin/users/{admin_user_id}/disable",
            headers={"X-Auth-Session": admin_token},
        )
        self.assertEqual(disable_self.status_code, 400)
        self.assertEqual(disable_self.json()["error"], "cannot_disable_self")

        extra_admin_id = f"admin-extra-{uuid.uuid4().hex}"
        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, username, password_hash, is_admin, created_at, updated_at)
                VALUES (?, ?, NULL, 1, ?, ?)
                """,
                (extra_admin_id, unique_name("admin-extra"), "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )

        disable_admin = client.post(
            f"/internal/admin/users/{extra_admin_id}/disable",
            headers={"X-Auth-Session": admin_token},
        )
        self.assertEqual(disable_admin.status_code, 400)
        self.assertEqual(disable_admin.json()["error"], "cannot_disable_admin")

    def test_internal_exception_response_does_not_leak_exception_text(self):
        with patch("app.routers.memory.transaction", side_effect=RuntimeError("secret sql sk-test traceback")):
            response = client.get("/memory/leak-check-user")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["error"], "get_memory_failed")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("secret sql", serialized)
        self.assertNotIn("sk-test", serialized)
        self.assertNotIn("traceback", serialized.lower())

    def test_db_health_response_does_not_leak_exception_text(self):
        with patch.object(
            db_module,
            "get_conn",
            side_effect=RuntimeError("secret sql DIFY_API_KEY traceback"),
        ):
            health = db_module.check_db_health()

        serialized = json.dumps(health, ensure_ascii=False)
        self.assertFalse(health["ok"])
        self.assertEqual(health["error"], "db_health_failed")
        self.assertNotIn("secret sql", serialized)
        self.assertNotIn("DIFY_API_KEY", serialized)
        self.assertNotIn("traceback", serialized.lower())


if __name__ == "__main__":
    unittest.main()
