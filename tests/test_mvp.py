import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(tempfile.gettempdir())
TEST_DB = TEST_DIR / "mvp-test.db"

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["TASK_WORKER_ENABLED"] = "false"
os.environ["ENABLE_DEBUG_ENDPOINTS"] = "false"

for path in [TEST_DB, TEST_DIR / "mvp-test.db-wal", TEST_DIR / "mvp-test.db-shm"]:
    if path.exists():
        path.unlink()

from fastapi.testclient import TestClient

from app.db import transaction
from app.main import app
from app.services.quality import build_quality_plan, repair_relationship_prompt_rules
from app.services.session_tasks import run_session_task_once


client = TestClient(app)


def latest_session_id(user_id: str) -> str:
    with transaction() as cur:
        cur.execute(
            """
            SELECT session_id
            FROM sessions
            WHERE user_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return row[0]


def latest_dsl_path() -> Path:
    candidates = sorted((ROOT / "docs").glob("psy-dsl-v*.yml"))
    if candidates:
        return candidates[-1]
    return ROOT / "docs" / "psy-dsl.yml"


def make_latest_session_expired(user_id: str, days_ago: int = 0):
    started_at = datetime.now() - timedelta(days=days_ago, minutes=SESSION_OFFSET_MINUTES)
    auto_close_at = started_at + timedelta(minutes=50)
    with transaction() as cur:
        cur.execute(
            """
            UPDATE sessions
            SET started_at = ?,
                auto_close_at = ?,
                ended_at = NULL,
                final_saved_at = NULL,
                status = 'open',
                stage = 'deep',
                updated_at = ?
            WHERE session_id = ?
            """,
            (
                started_at.isoformat(),
                auto_close_at.isoformat(),
                datetime.now().isoformat(),
                latest_session_id(user_id),
            ),
        )


SESSION_OFFSET_MINUTES = 55


class MvpApiTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        client.close()

    def test_health_checks_database(self):
        response = client.get("/health")
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["database"]["ok"])

    def test_new_user_first_status_creates_session(self):
        data = client.get("/session/status/new-user").json()
        for field in [
            "session_id",
            "status",
            "started_at",
            "ended_at",
            "elapsed_minutes",
            "remaining_minutes",
            "stage",
            "session_stage",
            "is_new_session",
            "is_new_session_str",
            "can_continue",
            "can_start_new_session",
            "daily_limit_reached",
            "message",
        ]:
            self.assertIn(field, data)
        self.assertEqual(data["status"], "open")
        self.assertTrue(data["is_new_session"])
        self.assertIsInstance(data["is_new_session_str"], str)
        self.assertIn(data["session_stage"], {"trust", "deep", "reframe", "action", "ending", "ended"})

    def test_low_content_session_skips_summary_memory_and_formal_handoff(self):
        user_id = "low-content-user"
        session = client.get(f"/session/status/{user_id}").json()
        session_id = session["session_id"]
        client.post(
            "/session-message",
            json={"user_id": user_id, "session_id": session_id, "role": "user", "content": "你好"},
        )
        finalized = client.post(
            "/session/finalize",
            json={"user_id": user_id, "session_id": session_id},
        ).json()
        self.assertTrue(finalized["is_low_content"])
        self.assertEqual(finalized["summary_type"], "low_content")

        with transaction() as cur:
            cur.execute("SELECT COUNT(*) FROM session_summaries WHERE session_id = ?", (session_id,))
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute("SELECT COUNT(*) FROM memories WHERE session_id = ?", (session_id,))
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute(
                "SELECT is_low_content, summary_type, user_message_count FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], "low_content")
            self.assertEqual(row[2], 1)

        skipped = client.post(
            f"/handoff/generate/{session_id}",
            json={"format": "markdown", "regenerate": False},
        ).json()
        self.assertFalse(skipped["generated"])
        self.assertEqual(skipped["reason"], "low_content_session")

        low_doc = client.post(
            f"/handoff/generate/{session_id}",
            json={"format": "json", "regenerate": False, "include_low_content": True},
        ).json()
        self.assertTrue(low_doc["content"]["is_low_content"])
        self.assertIn("facts", low_doc["content"])
        self.assertIn("hypotheses", low_doc["content"])
        self.assertIn("action_plan", low_doc["content"])

    def test_existing_open_session_returns_same_session(self):
        first = client.get("/session/status/open-user").json()
        second = client.get("/session/status/open-user").json()
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(second["status"], "open")
        self.assertFalse(second["is_new_session"])

    def test_manual_finalize_uses_actual_end_time(self):
        user_id = "manual-finalize-user"
        session = client.get(f"/session/status/{user_id}").json()
        session_id = session["session_id"]

        finalized = client.post(
            "/session/finalize",
            json={"user_id": user_id, "session_id": session_id},
        ).json()

        with transaction() as cur:
            cur.execute(
                "SELECT ended_at, final_saved_at, auto_close_at, close_reason FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            ended_at, final_saved_at, auto_close_at, close_reason = cur.fetchone()

        self.assertTrue(finalized["final_saved"])
        self.assertEqual(close_reason, "manual_finalize")
        self.assertEqual(ended_at, final_saved_at)
        self.assertLess(datetime.fromisoformat(ended_at), datetime.fromisoformat(auto_close_at))

    def test_expired_open_session_auto_ends_on_status(self):
        session = client.get("/session/status/expired-user").json()
        session_id = session["session_id"]
        client.post(
            "/session-message",
            json={
                "user_id": "expired-user",
                "session_id": session_id,
                "role": "user",
                "content": "最近工作压力很大，晚上睡不着。",
            },
        )
        client.post(
            "/session-message",
            json={
                "user_id": "expired-user",
                "session_id": session_id,
                "role": "user",
                "content": "主要担心项目推进不下去，也会忍不住切去玩游戏。",
            },
        )
        make_latest_session_expired("expired-user")

        ended = client.get("/session/status/expired-user").json()
        self.assertEqual(ended["status"], "ended")
        self.assertEqual(ended["session_stage"], "ended")
        self.assertEqual(ended["remaining_minutes"], 0)

        docs = client.get(f"/handoff/session/{session_id}").json()["documents"]
        self.assertEqual(len([doc for doc in docs if doc["format"] == "markdown"]), 1)

    def test_yesterday_open_session_auto_ends_and_new_session_starts(self):
        old = client.get("/session/status/yesterday-user").json()
        old_session_id = old["session_id"]
        make_latest_session_expired("yesterday-user", days_ago=1)

        current = client.get("/session/status/yesterday-user").json()
        self.assertEqual(current["status"], "open")
        self.assertTrue(current["is_new_session"])
        self.assertNotEqual(current["session_id"], old_session_id)

        with transaction() as cur:
            cur.execute("SELECT status FROM sessions WHERE session_id = ?", (old_session_id,))
            self.assertEqual(cur.fetchone()[0], "ended")

    def test_background_task_is_idempotent(self):
        session = client.get("/session/status/task-user").json()
        session_id = session["session_id"]
        for content in [
            "最近项目进展卡住，我会反复等工具输出，心里越来越急。",
            "卡住以后我容易转去玩游戏，之后又很自责。",
        ]:
            client.post(
                "/session-message",
                json={
                    "user_id": "task-user",
                    "session_id": session_id,
                    "role": "user",
                    "content": content,
                },
            )
        make_latest_session_expired("task-user")

        first = run_session_task_once(scan_limit=20, fetch_limit=10)
        second = run_session_task_once(scan_limit=20, fetch_limit=10)

        self.assertEqual(first["claimed_tasks"], 1)
        self.assertEqual(second["claimed_tasks"], 0)

        with transaction() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM handoff_documents WHERE session_id = ? AND format = 'markdown'",
                (session_id,),
            )
            self.assertEqual(cur.fetchone()[0], 1)

    def test_memory_dedupes_same_session_content(self):
        session = client.get("/session/status/memory-user").json()
        payload = {
            "user_id": "memory-user",
            "session_id": session["session_id"],
            "memory": "用户希望下次继续讨论工作压力。",
            "memory_type": "therapy_goal",
            "importance": 2,
        }
        first = client.post("/memory", json=payload).json()
        second = client.post("/memory", json=payload).json()
        self.assertTrue(first["success"])
        self.assertTrue(second["already_exists"])

        with transaction() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM memories WHERE user_id = ? AND session_id = ?",
                ("memory-user", session["session_id"]),
            )
            self.assertEqual(cur.fetchone()[0], 1)

    def test_memory_quality_filters_greetings_and_strong_labels(self):
        greeting = client.post("/memory", json={"user_id": "memory-filter", "memory": "你好"}).json()
        self.assertTrue(greeting["skipped"])
        self.assertEqual(greeting["reason"], "greeting_only")

        strong_label = client.post(
            "/memory",
            json={
                "user_id": "memory-filter",
                "memory": "用户处于防御状态，正在测试咨询师可信度。",
            },
        ).json()
        self.assertTrue(strong_label["skipped"])
        self.assertEqual(strong_label["reason"], "strong_interpretation")

    def test_handoff_markdown_and_json_generation(self):
        session = client.get("/session/status/handoff-user").json()
        session_id = session["session_id"]
        client.post(
            "/session-message",
            json={
                "user_id": "handoff-user",
                "session_id": session_id,
                "role": "user",
                "content": "我最近很焦虑，想先把工作里的冲突理清楚。",
            },
        )
        client.post(
            "/session-message",
            json={
                "user_id": "handoff-user",
                "session_id": session_id,
                "role": "user",
                "content": "冲突发生后我会反复回想自己是不是说错了，也担心下次沟通更僵。",
            },
        )
        client.post("/session/finalize", json={"user_id": "handoff-user", "session_id": session_id})

        markdown_doc = client.post(
            f"/handoff/generate/{session_id}",
            json={"format": "markdown", "regenerate": False},
        ).json()
        json_doc = client.post(
            f"/handoff/generate/{session_id}",
            json={"format": "json", "regenerate": False},
        ).json()

        self.assertEqual(markdown_doc["format"], "markdown")
        self.assertIn("# 咨询交接文档", markdown_doc["content"])
        self.assertIn("## 2. 本次会话有效性", markdown_doc["content"])
        self.assertIn("## 3. 主要事实观察", markdown_doc["content"])
        self.assertIn("## 待验证假设", markdown_doc["content"])
        self.assertEqual(json_doc["format"], "json")
        self.assertIn("risk_assessment", json_doc["content"])
        self.assertIn("facts", json_doc["content"])
        self.assertIn("hypotheses", json_doc["content"])
        self.assertIn("action_plan", json_doc["content"])

        user_docs = client.get("/handoff/user/handoff-user").json()
        self.assertGreaterEqual(len(user_docs["documents"]), 2)

        exported = client.get("/handoff/export/user/handoff-user?format=markdown")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/markdown", exported.headers["content-type"])
        self.assertIn("session_id", exported.text)

    def test_postgresql_database_url_config_can_be_read(self):
        code = (
            "import os;"
            "os.environ['DATABASE_URL']='postgresql://user:password@host:5432/dbname';"
            "import app.config as c;"
            "print(c.IS_POSTGRES, c.DATABASE_URL)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("True postgresql://user:password@host:5432/dbname", result.stdout)

    def test_user_export_auto_generates_latest_ended_session_document(self):
        session = client.get("/session/status/user-export-auto").json()
        session_id = session["session_id"]
        client.post(
            "/session-message",
            json={
                "user_id": "user-export-auto",
                "session_id": session_id,
                "role": "user",
                "content": "我想把这次咨询整理成之后可以交接的内容。",
            },
        )
        client.post(
            "/session-message",
            json={
                "user_id": "user-export-auto",
                "session_id": session_id,
                "role": "user",
                "content": "重点是工作压力、睡眠变差，以及下次希望继续跟进的行动计划。",
            },
        )
        client.post(
            "/session/finalize",
            json={"user_id": "user-export-auto", "session_id": session_id},
        )

        with transaction() as cur:
            cur.execute(
                """
                DELETE FROM handoff_documents
                WHERE user_id = ? AND session_id = ? AND format = 'json'
                """,
                ("user-export-auto", session_id),
            )

        exported = client.get("/handoff/export/user/user-export-auto?format=json")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("application/json", exported.headers["content-type"])
        self.assertIn("risk_assessment", exported.text)
        self.assertIn("long_term_memories", exported.text)
        self.assertIn("recent_message_clues", exported.text)

    def test_user_export_uses_longitudinal_user_context(self):
        user_id = "longitudinal-user"
        first = client.get(f"/session/status/{user_id}").json()
        first_session_id = first["session_id"]
        client.post(
            "/profile",
            json={"user_id": user_id, "profile_memory": "长期画像：用户长期关注工作压力和边界感。"},
        )
        client.post(
            "/care-plan",
            json={"user_id": user_id, "plan_text": "计划：持续练习情绪记录和沟通前暂停。"},
        )
        client.post(
            "/session-message",
            json={
                "user_id": user_id,
                "session_id": first_session_id,
                "role": "user",
                "content": "第一次咨询主要讨论工作压力。",
            },
        )
        client.post(
            "/session-message",
            json={
                "user_id": user_id,
                "session_id": first_session_id,
                "role": "user",
                "content": "用户提到压力大时会拖延项目，并希望减少自责。",
            },
        )
        client.post("/session/finalize", json={"user_id": user_id, "session_id": first_session_id})

        with transaction() as cur:
            yesterday = datetime.now() - timedelta(days=1)
            cur.execute(
                """
                UPDATE sessions
                SET started_at = ?, ended_at = ?, final_saved_at = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    yesterday.isoformat(),
                    (yesterday + timedelta(minutes=50)).isoformat(),
                    (yesterday + timedelta(minutes=50)).isoformat(),
                    datetime.now().isoformat(),
                    first_session_id,
                ),
            )

        second = client.get(f"/session/status/{user_id}").json()
        second_session_id = second["session_id"]
        client.post(
            "/session-message",
            json={
                "user_id": user_id,
                "session_id": second_session_id,
                "role": "user",
                "content": "第二次咨询继续讨论亲密关系中的表达方式。",
            },
        )
        client.post(
            "/session-message",
            json={
                "user_id": user_id,
                "session_id": second_session_id,
                "role": "user",
                "content": "用户担心直接表达需求会让关系变紧张，想练习更温和但清楚的说法。",
            },
        )
        client.post("/session/finalize", json={"user_id": user_id, "session_id": second_session_id})

        exported = client.get(f"/handoff/export/user/{user_id}?format=markdown")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("长期画像", exported.text)
        self.assertIn("最近多次咨询摘要", exported.text)
        self.assertIn(first_session_id, exported.text)
        self.assertIn(second_session_id, exported.text)

    def test_user_handoff_default_session_limit_is_10_and_query_override_works(self):
        user_id = "handoff-limit-user"
        session_ids = []
        for index in range(6):
            session = client.get(f"/session/status/{user_id}").json()
            session_id = session["session_id"]
            session_ids.append(session_id)
            client.post(
                "/session-message",
                json={
                    "user_id": user_id,
                    "session_id": session_id,
                    "role": "user",
                    "content": f"第 {index + 1} 次咨询继续讨论项目推进、面试压力和一个很小的行动反馈。",
                },
            )
            client.post(
                "/session-message",
                json={
                    "user_id": user_id,
                    "session_id": session_id,
                    "role": "user",
                    "content": "这次有具体内容，想把下次前最小行动继续调轻一点。",
                },
            )
            client.post("/session/finalize", json={"user_id": user_id, "session_id": session_id})
            with transaction() as cur:
                shifted = datetime.now() - timedelta(days=6 - index)
                cur.execute(
                    """
                    UPDATE sessions
                    SET started_at = ?, ended_at = ?, final_saved_at = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    (
                        shifted.isoformat(),
                        (shifted + timedelta(minutes=50)).isoformat(),
                        (shifted + timedelta(minutes=50)).isoformat(),
                        datetime.now().isoformat(),
                        session_id,
                    ),
                )

        exported_default = client.get(f"/handoff/export/user/{user_id}?format=json")
        self.assertEqual(exported_default.status_code, 200)
        default_payload = json.loads(exported_default.text)
        self.assertEqual(default_payload["scope"]["session_limit"], 10)
        self.assertEqual(default_payload["scope"]["session_count"], 6)
        self.assertTrue(set(session_ids).issubset({item["session_id"] for item in default_payload["sessions"]}))

        exported_limited = client.get(f"/handoff/export/user/{user_id}?format=json&session_limit=3")
        self.assertEqual(exported_limited.status_code, 200)
        limited_payload = json.loads(exported_limited.text)
        self.assertEqual(limited_payload["scope"]["session_limit"], 3)
        self.assertEqual(limited_payload["scope"]["session_count"], 3)

    def test_finalize_incrementally_updates_care_plan_and_profile_for_eventful_sessions(self):
        user_id = "longitudinal-increment-user"

        first = client.get(f"/session/status/{user_id}").json()
        first_session_id = first["session_id"]
        for content in [
            "我没工作一段时间了，面试压力很大，一想到项目就去玩游戏，拖完又很自责。",
            "我不想听自律建议，只想先把问题地图理清楚，再试一个很小的行动。",
        ]:
            client.post(
                "/session-message",
                json={"user_id": user_id, "session_id": first_session_id, "role": "user", "content": content},
            )

        first_finalize = client.post(
            "/session/finalize",
            json={"user_id": user_id, "session_id": first_session_id},
        ).json()
        self.assertTrue(first_finalize["care_plan_updated"])
        self.assertTrue(first_finalize["profile_updated"])

        first_profile = client.get(f"/profile/{user_id}").json()["profile_memory"]
        first_plan = client.get(f"/care-plan/{user_id}").json()["plan_text"]
        self.assertIn(first_session_id, first_profile)
        self.assertIn(first_session_id, first_plan)

        with transaction() as cur:
            yesterday = datetime.now() - timedelta(days=1)
            cur.execute(
                """
                UPDATE sessions
                SET started_at = ?, ended_at = ?, final_saved_at = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    yesterday.isoformat(),
                    (yesterday + timedelta(minutes=50)).isoformat(),
                    (yesterday + timedelta(minutes=50)).isoformat(),
                    datetime.now().isoformat(),
                    first_session_id,
                ),
            )

        second = client.get(f"/session/status/{user_id}").json()
        second_session_id = second["session_id"]
        for content in [
            "上次那个任务没做成，打开电脑后就刷视频了，我有点羞耻，感觉自己又失败了。",
            "如果继续原计划我大概率做不到，能不能把计划再小一点，比如只打开 VSCode 不写代码。",
        ]:
            client.post(
                "/session-message",
                json={"user_id": user_id, "session_id": second_session_id, "role": "user", "content": content},
            )

        second_finalize = client.post(
            "/session/finalize",
            json={"user_id": user_id, "session_id": second_session_id},
        ).json()
        self.assertTrue(second_finalize["care_plan_updated"])
        self.assertTrue(second_finalize["profile_updated"])

        second_profile = client.get(f"/profile/{user_id}").json()["profile_memory"]
        second_plan = client.get(f"/care-plan/{user_id}").json()["plan_text"]
        self.assertIn(first_session_id, second_profile)
        self.assertIn(second_session_id, second_profile)
        self.assertIn(first_session_id, second_plan)
        self.assertIn(second_session_id, second_plan)

    def test_quality_plan_and_relationship_repair_rules_are_specific(self):
        plan = build_quality_plan()
        self.assertIn("psychological_line", plan)
        self.assertIn("action_line", plan)
        self.assertIn("metrics", plan)
        self.assertNotIn("继续探索", "\n".join(plan["action_line"]))

        rules = "\n".join(repair_relationship_prompt_rules())
        self.assertIn("先暂停原议题", rules)
        self.assertIn("先修复关系", "先修复关系：" + rules)
        self.assertIn("不要继续推进技巧", rules)

    def test_dify_dsl_contains_quality_rules_and_no_api_key(self):
        dsl_path = latest_dsl_path()
        dsl_text = dsl_path.read_text(encoding="utf-8")
        yaml.safe_load(dsl_text)
        self.assertIn("/session/status", dsl_text)
        self.assertIn("session_stage", dsl_text)
        self.assertIn("risk_level", dsl_text)
        self.assertIn("低内容", dsl_text)
        self.assertIn("暂停原议题", dsl_text)
        self.assertIn("先修复关系", dsl_text)
        self.assertIn("心理线", dsl_text)
        self.assertIn("行动线", dsl_text)
        self.assertIn("用户只是说“困了”“好困”“有点累”“状态不好”，不等于结束", dsl_text)
        self.assertIn("fatigue_without_explicit_end", dsl_text)
        self.assertIn("Finalize Session", dsl_text)
        self.assertIn("纵向咨询事件回应原则", dsl_text)
        self.assertIn("当用户反馈任务未完成时", dsl_text)
        self.assertIn("当用户表达连续几天或多次完成小动作时", dsl_text)
        self.assertIn("当用户表达总结、阶段结束、下一阶段或交接时", dsl_text)
        self.assertNotIn("更改保存标签", dsl_text)
        self.assertNotIn("sk-", dsl_text.lower())

    def test_dify_end_intent_parse_keeps_fatigue_only_open(self):
        dsl_path = latest_dsl_path()
        dsl = yaml.safe_load(dsl_path.read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in dsl["workflow"]["graph"]["nodes"]}
        code = nodes["1779968610422"]["data"]["code"]
        namespace = {}
        exec(code, namespace)

        result = namespace["main"](
            '{"user_wants_end": true, "confidence": 0.9, "reason": "用户说困了"}',
            "呃，不记得了，我现在好困",
            True,
            "trust",
            44.0,
        )

        self.assertFalse(result["user_wants_end"])
        self.assertFalse(result["should_close"])
        self.assertEqual(result["reason"], "fatigue_without_explicit_end")


if __name__ == "__main__":
    unittest.main()
