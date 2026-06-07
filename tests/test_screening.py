from fastapi.testclient import TestClient

from app.db import transaction
from app.main import app
from app.services.screening import build_snapshot_domains, determine_risk_stage, score_screening


client = TestClient(app)
client.headers.update({"X-Backend-Token": "test-backend-token"})


def test_screening_score_boundaries():
    assert score_screening("phq9", [0] * 9)["severity"] == "minimal"
    assert score_screening("phq9", [1, 1, 1, 1, 1, 0, 0, 0, 0])["severity"] == "mild"
    assert score_screening("phq9", [2, 2, 2, 2, 2, 0, 0, 0, 0])["severity"] == "moderate"
    assert score_screening("phq9", [2, 2, 2, 2, 2, 2, 2, 1, 0])["severity"] == "moderately_severe"
    assert score_screening("phq9", [3, 3, 3, 3, 3, 3, 2, 0, 0])["severity"] == "severe"

    assert score_screening("gad7", [0] * 7)["severity"] == "minimal"
    assert score_screening("gad7", [1, 1, 1, 1, 1, 0, 0])["severity"] == "mild"
    assert score_screening("gad7", [2, 2, 2, 2, 2, 0, 0])["severity"] == "moderate"
    assert score_screening("gad7", [3, 3, 3, 3, 3, 0, 0])["severity"] == "severe"

    asrm_elevated = score_screening("asrm", [2, 1, 1, 1, 1])
    assert asrm_elevated["severity"] == "elevated"
    assert "mania_hypomania_elevated" in asrm_elevated["risk_flags"]

    asrm_high = score_screening("asrm", [4, 4, 4, 0, 0])
    assert asrm_high["severity"] == "high"
    assert asrm_high["risk_level"] == "medium"

    des_elevated = score_screening("des2", [30] * 28)
    assert des_elevated["score"] == 30
    assert des_elevated["severity"] == "elevated"


def test_screening_api_rejects_invalid_answers():
    count_error = client.post(
        "/screening/phq9",
        json={"user_id": "screening-invalid", "answers": [0] * 8},
    )
    assert count_error.status_code == 400
    assert count_error.json()["error"] == "answer_count_mismatch"

    range_error = client.post(
        "/screening/gad7",
        json={"user_id": "screening-invalid", "answers": [0, 0, 0, 0, 0, 0, 4]},
    )
    assert range_error.status_code == 400
    assert range_error.json()["error"] == "answer_out_of_range"

    unsupported = client.post(
        "/screening/unknown",
        json={"user_id": "screening-invalid", "answers": [0]},
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"] == "unsupported_instrument"


def test_screening_submission_persists_snapshot_and_context_without_answers():
    user_id = "screening-context-user"
    answers = [0, 0, 0, 0, 0, 0, 0, 0, 1]

    response = client.post(
        "/screening/phq9",
        json={"user_id": user_id, "answers": answers, "session_id": "screening-session"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert data["instrument"] == "phq9"
    assert data["is_diagnosis"] is False
    assert data["risk_level"] == "high"
    assert "self_harm_item_positive" in data["risk_flags"]
    assert data["snapshot"]["safety"]["risk_level"] == "high"

    current = client.get(f"/screening/current/{user_id}").json()
    assert current["exists"] is True
    snapshot = current["snapshot"]
    assert snapshot["screenings"]["phq9"]["label"]
    assert "answers" not in str(snapshot).lower()

    history = client.get(f"/screening/history/{user_id}").json()["history"]
    assert history[0]["instrument"] == "phq9"
    assert "answers" not in history[0]

    context = client.get(f"/context/{user_id}").json()
    assert "【最近状态筛查】" in context["context_text"]
    assert "PHQ-9" in context["context_text"]
    assert "非诊断" in context["context_text"]
    assert str(answers) not in context["context_text"]

    with transaction() as cur:
        cur.execute(
            """
            SELECT answers_json
            FROM clinical_screenings
            WHERE user_id = ? AND instrument = 'phq9'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        assert cur.fetchone()[0] == "[0, 0, 0, 0, 0, 0, 0, 0, 1]"
        cur.execute(
            """
            SELECT COUNT(*)
            FROM mental_state_snapshots
            WHERE user_id = ?
            """,
            (user_id,),
        )
        assert cur.fetchone()[0] >= 1


def test_screening_config_lists_all_instruments():
    config = client.get("/screening/config").json()
    codes = {item["code"] for item in config["instruments"]}
    assert codes == {"phq9", "gad7", "asrm", "des2"}
    assert all(item["questions"] for item in config["instruments"])
    module_codes = {item["code"] for item in config["supplemental_modules"]}
    assert module_codes == {"stage", "safety", "mania", "anxiety", "dissociation"}
    assert "不是医疗诊断" in config["disclaimer"]


def test_screening_bootstrap_returns_config_and_current_snapshot():
    user_id = "screening-bootstrap-user"
    initial = client.get(f"/screening/bootstrap/{user_id}").json()
    assert initial["config"]["instruments"]
    assert initial["current"]["exists"] is False
    assert initial["current"]["snapshot"] is None

    client.post(
        "/screening/phq9",
        json={"user_id": user_id, "answers": [0] * 9},
    )

    hydrated = client.get(f"/screening/bootstrap/{user_id}").json()
    assert hydrated["current"]["exists"] is True
    assert hydrated["current"]["snapshot"]["screenings"]["phq9"]["score"] == 0


def test_screening_bootstrap_tolerates_legacy_malformed_snapshot_json():
    user_id = "screening-legacy-snapshot-user"
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO mental_state_snapshots (
                user_id, summary, snapshot_json, safety_level, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "历史快照摘要",
                '["legacy", "shape"]',
                "none",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )

    response = client.get(f"/screening/bootstrap/{user_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["config"]["instruments"]
    assert data["current"]["exists"] is True
    assert data["current"]["snapshot"]["summary"] == "历史快照摘要"
    assert data["current"]["snapshot"]["screenings"] == {}


def test_screening_bootstrap_query_supports_path_sensitive_user_ids():
    user_id = "legacy/user-with-slash"
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO mental_state_snapshots (
                user_id, summary, snapshot_json, safety_level, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "路径敏感历史用户",
                "{}",
                "none",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )

    response = client.get("/screening/bootstrap", params={"user_id": user_id})
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user_id
    assert data["current"]["exists"] is True
    assert data["current"]["snapshot"]["summary"] == "路径敏感历史用户"


def test_screening_batch_persists_multiple_scales_and_one_snapshot():
    user_id = "screening-batch-user"
    response = client.post(
        "/screening/batch",
        json={
            "user_id": user_id,
            "screenings": [
                {"instrument": "phq9", "answers": [0] * 9},
                {"instrument": "gad7", "answers": [1, 1, 1, 1, 1, 0, 0]},
                {"instrument": "asrm", "answers": [0] * 5},
                {"instrument": "des2", "answers": [0] * 28},
            ],
            "supplements": {"stage": [0, 0, 0, 0, 0, 0]},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert set(data["results_by_instrument"]) == {"phq9", "gad7", "asrm", "des2"}
    assert data["snapshot"]["stage"] == "mild"
    assert data["snapshot"]["confidence"] == "high"
    assert "answers" not in str(data["snapshot"]).lower()

    with transaction() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM clinical_screenings
            WHERE user_id = ?
            """,
            (user_id,),
        )
        assert cur.fetchone()[0] == 4
        cur.execute(
            """
            SELECT COUNT(*)
            FROM mental_state_snapshots
            WHERE user_id = ?
            """,
            (user_id,),
        )
        assert cur.fetchone()[0] == 1


def test_screening_batch_layered_triggers_and_context_without_raw_answers():
    user_id = "screening-layered-user"
    phq9 = [3, 3, 3, 3, 3, 3, 3, 0, 1]
    response = client.post(
        "/screening/batch",
        json={
            "user_id": user_id,
            "screenings": [
                {"instrument": "phq9", "answers": phq9},
                {"instrument": "gad7", "answers": [2, 2, 2, 2, 2, 0, 0]},
                {"instrument": "asrm", "answers": [2, 1, 1, 1, 1]},
                {"instrument": "des2", "answers": [30] * 28},
            ],
            "supplements": {
                "stage": [3, 3, 2, 3, 3, 2],
                "safety": [3, 2, 2, 2],
                "mania": [2, 2, 2, 2],
                "anxiety": [2, 2, 2, 2],
                "dissociation": [2, 2, 2, 2],
            },
        },
    )

    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["stage"] == "urgent_attention"
    assert snapshot["confidence"] == "high"
    assert snapshot["domains"]["safety"]["current_danger"] == "urgent_attention"
    assert "current_safety_urgent" in snapshot["safety"]["flags"]
    assert snapshot["domains"]["anxiety"]["subtypes"]
    assert snapshot["domains"]["mania_hypomania"]["risk_features"]
    assert snapshot["domains"]["dissociation"]["risk_features"]
    assert str(phq9) not in str(snapshot)

    context = client.get(f"/context/{user_id}").json()["context_text"]
    assert "当前风险阶段" in context
    assert "紧急关注" in context
    assert "answers_json" not in context
    assert str(phq9) not in context


def test_risk_stage_boundaries():
    def item(instrument, answers):
        result = score_screening(instrument, answers)
        return {
            "score": result["score"],
            "severity": result["severity"],
            "label": result["label"],
            "risk_level": result["risk_level"],
            "risk_flags": result["risk_flags"],
        }

    stable_latest = {
        "phq9": item("phq9", [0] * 9),
        "gad7": item("gad7", [0] * 7),
        "asrm": item("asrm", [0] * 5),
        "des2": item("des2", [0] * 28),
    }
    assert determine_risk_stage(stable_latest, build_snapshot_domains(stable_latest, {"stage": [0, 0, 0, 0, 0, 0]})) == "stable"

    mild_latest = {**stable_latest, "phq9": item("phq9", [1, 1, 1, 1, 1, 0, 0, 0, 0])}
    assert determine_risk_stage(mild_latest, build_snapshot_domains(mild_latest, {"stage": [1, 1, 0, 1, 0, 0]})) == "mild"

    moderate_latest = {**stable_latest, "gad7": item("gad7", [2, 2, 2, 2, 2, 0, 0])}
    assert determine_risk_stage(moderate_latest, build_snapshot_domains(moderate_latest, {"stage": [1, 1, 1, 1, 1, 0]})) == "moderate"

    high_latest = {**stable_latest, "phq9": item("phq9", [3, 3, 3, 3, 3, 3, 3, 0, 0])}
    assert determine_risk_stage(high_latest, build_snapshot_domains(high_latest, {"stage": [2, 2, 2, 2, 2, 1]})) == "high_attention"

    urgent_latest = {**stable_latest, "phq9": item("phq9", [0, 0, 0, 0, 0, 0, 0, 0, 1])}
    assert (
        determine_risk_stage(
            urgent_latest,
            build_snapshot_domains(urgent_latest, {"safety": [3, 2, 2, 2]}),
        )
        == "urgent_attention"
    )
