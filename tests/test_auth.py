import os
import tempfile
import unittest
import uuid
from pathlib import Path


TEST_DB = Path(tempfile.gettempdir()) / "mvp-test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB}")
os.environ.setdefault("TASK_WORKER_ENABLED", "false")
os.environ.setdefault("ENABLE_DEBUG_ENDPOINTS", "false")
os.environ.setdefault("AUTH_SECRET", "test-auth-secret")
os.environ.setdefault("BACKEND_SHARED_TOKEN", "test-backend-token")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin-password")

from fastapi.testclient import TestClient

from app.db import transaction
from app.main import app


client = TestClient(app)
client.headers.update({"X-Backend-Token": "test-backend-token"})


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


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
            json={"username": username, "password": password, "inviteCode": invite_code},
        )
        self.assertEqual(registered.status_code, 200)
        user_id = registered.json()["user"]["user_id"]

        reused = client.post(
            "/internal/auth/register",
            json={
                "username": unique_name("user"),
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
                "password": "user-password-123",
                "inviteCode": invite_code,
            },
        )
        self.assertEqual(registered.status_code, 400)

    def test_plain_secrets_are_not_stored(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="hash-check")
        username = unique_name("hash")
        password = "user-password-123"

        client.post(
            "/internal/auth/register",
            json={"username": username, "password": password, "inviteCode": invite_code},
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

    def test_regular_user_cannot_manage_invites(self):
        admin_token = login_admin()
        invite_code = create_invite(admin_token, note="regular")
        username = unique_name("regular")
        password = "user-password-123"
        client.post(
            "/internal/auth/register",
            json={"username": username, "password": password, "inviteCode": invite_code},
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


if __name__ == "__main__":
    unittest.main()
