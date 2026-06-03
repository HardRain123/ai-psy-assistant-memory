# Testing Guide

This project has two test layers:

1. Backend tests that run locally and do not call Dify.
2. Real Dify Chatflow E2E tests that call the official Chatflow API only when explicitly enabled.

## Default Tests

Run:

```powershell
pytest -q
```

Default tests must not call real Dify. The real E2E suite is skipped unless `RUN_DIFY_E2E=true`.

## Real Dify Chatflow Longitudinal E2E

Required environment variables:

```powershell
$env:RUN_DIFY_E2E = "true"
$env:DIFY_API_KEY = "<your Dify App API Key>"
$env:BACKEND_URL = "https://ai-assistant-psy-mvp.619569391.workers.dev"
```

Optional environment variables:

```powershell
$env:DIFY_API_BASE = "https://api.dify.ai/v1"
$env:DIFY_E2E_TIMEOUT_SECONDS = "60"
$env:DIFY_E2E_MAX_RETRIES = "2"
$env:DIFY_E2E_TRUST_ENV = "false"
$env:BACKEND_E2E_TRUST_ENV = "false"
```

`DIFY_E2E_TRUST_ENV=false` is the default. Set it to `true` only when the E2E runner must use system proxy environment variables.
`BACKEND_E2E_TRUST_ENV` can override proxy handling for backend snapshot/cleanup requests when Dify API and `BACKEND_URL` need different network paths.
`DIFY_E2E_MAX_RETRIES` retries transient Dify network failures such as timeouts or remote disconnects; HTTP status-code failures still fail immediately.

Run only the real E2E test:

```powershell
pytest -q tests/test_dify_e2e.py
```

The test uses:

```http
POST {DIFY_API_BASE}/chat-messages
Authorization: Bearer {DIFY_API_KEY}
Content-Type: application/json
```

The request body uses `response_mode=blocking`:

```json
{
  "inputs": {
    "user_id": "codex-e2e-test-user-{run_id}"
  },
  "query": "用户输入",
  "response_mode": "blocking",
  "conversation_id": "",
  "user": "codex-e2e-test-user-{run_id}"
}
```

The real E2E is a 6-session longitudinal counseling flow, not a smoke test. The normal flow uses one synthetic user:

```text
codex-e2e-test-user-{run_id}
```

Each session starts a fresh Dify conversation by sending `conversation_id=""`. Later rounds inside the same session reuse the first returned `conversation_id`. This verifies history is restored through backend `/context`, memory, profile, and care-plan state rather than through a single Dify conversation.

The normal flow includes:

1. Initial counseling and problem mapping.
2. First very small action plan.
3. Plan failure, review, and downshift.
4. Partial completion and effective-factor extraction.
5. Continued execution with slight increase.
6. Stage completion, next-stage plan, and handoff summary.

Each normal session has at least 8 rounds, Session 1 has 10 rounds, and the normal flow has at least 50 rounds total. High-risk and low-content/reluctant scenarios use separate synthetic user IDs and do not participate in normal long-term plan scoring.

## Test Cleanup

The cleanup endpoint is:

```http
DELETE /test/e2e-data/{user_id}
```

It is strictly protected:

- Enabled only when `TESTING=true` or `APP_ENV=test`.
- Returns `403` when not in test mode.
- Only accepts `user_id` values starting with `codex-e2e-test-user`.
- Does not use query parameters to bypass environment protection.
- Does not reuse the debug deletion endpoint.

For a remote backend, enable test cleanup only in a dedicated test deployment. If cleanup is unavailable, real E2E still uses a unique `run_id` to avoid colliding with real users.

## Test Time Shift

The longitudinal E2E needs multiple formal sessions in one test run. If the backend enforces one formal session per day, use the protected time-shift endpoint in a dedicated test deployment:

```http
POST /test/e2e-time-shift/{user_id}
Content-Type: application/json

{"days": 1}
```

It is strictly protected:

- Enabled only when `TESTING=true` or `APP_ENV=test`.
- Returns `403` when not in test mode.
- Only accepts `user_id` values starting with `codex-e2e-test-user`.
- Shifts only that synthetic user's latest session timestamps.
- Does not reuse the debug deletion endpoint.

## E2E Report

Real E2E writes redacted reports to:

```text
test-artifacts/dify-e2e-{run_id}.json
test-artifacts/dify-e2e-{run_id}.md
```

Reports separate:

- Session and round counts, including `normal_total_rounds`, `overall_total_rounds`, `rounds_per_session`, and `total_conversations`.
- Normal, high-risk, and low-content synthetic user IDs.
- Event coverage for the longitudinal normal flow: `event_coverage`, `missing_core_events`, `manual_review_events`, and `key_evidence_by_event`.
- Session-level evidence from user trigger rounds, Dify reply rounds, session summaries, memory/profile/care-plan diffs, and user-level handoff summaries.
- Incremental persistence evidence: `care_plan_update_events`, `profile_update_events`, `care_plan_diff_after_each_session`, and `profile_diff_after_each_session`.
- User-level handoff scope: `handoff_session_count` and `handoff_session_limit`; the default user-level handoff limit is 10 and can be overridden with `session_limit`.
- Plan progression fields from initial tiny task through next-stage planning.
- Care-plan, memory, and profile diffs after each normal session.
- Key Dify reply excerpts with per-round 7-dimension quality scores.
- Backend persistence evidence and cleanup results.
- Failed assertions with reasons.

The 6-session longitudinal flow is evaluated by event coverage plus multi-source evidence. Keywords may appear as evidence hints, but a fixed keyword hit is not the primary pass/fail standard.

Reports must not include `DIFY_API_KEY`, Authorization headers, tokens, or real user data.

If `docs/psy-dsl-v*.yml` or any Dify prompt is changed, re-import the Dify application DSL and publish it before running real E2E against the hosted Chatflow. Local backend tests can verify code paths, but they cannot verify unpublished Dify prompt changes.

This is a product workflow and output-quality evaluation. It is not treatment-effect validation and must not be used to claim the system has proven real-world psychotherapy efficacy.
