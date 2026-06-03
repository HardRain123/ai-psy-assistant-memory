import os
import tempfile
import unittest
from pathlib import Path


TEST_DB = Path(tempfile.gettempdir()) / "mvp-test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB}")
os.environ.setdefault("TASK_WORKER_ENABLED", "false")
os.environ.setdefault("ENABLE_DEBUG_ENDPOINTS", "false")

from fastapi.testclient import TestClient

from app.db import transaction
from app.main import app


client = TestClient(app)


def restore_env(saved: dict[str, str | None]):
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class TestingCleanupTests(unittest.TestCase):
    def setUp(self):
        self.saved_env = {
            "TESTING": os.environ.get("TESTING"),
            "APP_ENV": os.environ.get("APP_ENV"),
        }

    def tearDown(self):
        restore_env(self.saved_env)

    def test_cleanup_is_forbidden_outside_testing_even_with_query_param(self):
        os.environ["TESTING"] = "false"
        os.environ["APP_ENV"] = "development"

        response = client.delete(
            "/test/e2e-data/codex-e2e-test-user-disabled?TESTING=true&APP_ENV=test"
        )

        self.assertEqual(response.status_code, 403)

    def test_cleanup_rejects_non_e2e_user_prefix(self):
        os.environ["TESTING"] = "true"
        os.environ["APP_ENV"] = "development"

        response = client.delete("/test/e2e-data/real-user")

        self.assertEqual(response.status_code, 400)

    def test_cleanup_deletes_only_allowed_e2e_user_data(self):
        os.environ["TESTING"] = "true"
        user_id = "codex-e2e-test-user-cleanup"
        session = client.get(f"/session/status/{user_id}").json()
        session_id = session["session_id"]
        client.post(
            "/session-message",
            json={
                "user_id": user_id,
                "session_id": session_id,
                "role": "user",
                "content": "最近工作压力很大，想测试清理能力。",
            },
        )
        client.post("/profile", json={"user_id": user_id, "profile_memory": "测试画像"})
        client.post("/care-plan", json={"user_id": user_id, "plan_text": "测试计划"})

        response = client.delete(f"/test/e2e-data/{user_id}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        with transaction() as cur:
            for table in [
                "users",
                "sessions",
                "session_messages",
                "user_profiles",
                "care_plans",
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,))
                self.assertEqual(cur.fetchone()[0], 0, table)

    def test_time_shift_is_forbidden_outside_testing(self):
        os.environ["TESTING"] = "false"
        os.environ["APP_ENV"] = "development"

        response = client.post(
            "/test/e2e-time-shift/codex-e2e-test-user-disabled",
            json={"days": 1},
        )

        self.assertEqual(response.status_code, 403)

    def test_time_shift_rejects_non_e2e_user_prefix(self):
        os.environ["TESTING"] = "true"

        response = client.post("/test/e2e-time-shift/real-user", json={"days": 1})

        self.assertEqual(response.status_code, 400)

    def test_time_shift_allows_next_e2e_session_without_cleanup(self):
        os.environ["TESTING"] = "true"
        user_id = "codex-e2e-test-user-time-shift"
        first = client.get(f"/session/status/{user_id}").json()
        first_session_id = first["session_id"]
        client.post(
            "/session/finalize",
            json={"user_id": user_id, "session_id": first_session_id},
        )

        shifted = client.post(f"/test/e2e-time-shift/{user_id}", json={"days": 1})
        self.assertEqual(shifted.status_code, 200)
        self.assertTrue(shifted.json()["success"])

        second = client.get(f"/session/status/{user_id}").json()
        self.assertTrue(second["is_new_session"])
        self.assertNotEqual(second["session_id"], first_session_id)


if __name__ == "__main__":
    unittest.main()
