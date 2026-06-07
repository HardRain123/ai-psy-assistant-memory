CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    username TEXT,
    email TEXT,
    email_verified_at TEXT,
    password_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    last_login_at TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    request_ip_hash TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    request_ip_hash TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_outbox (
    id BIGSERIAL PRIMARY KEY,
    message_type TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error_type TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_security_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id TEXT,
    email_hash TEXT,
    ip_hash TEXT,
    user_agent TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_rate_limits (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    email_hash TEXT,
    ip_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    session_id TEXT UNIQUE,
    user_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    final_saved_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    auto_close_at TEXT,
    close_reason TEXT,
    timeout_checked_at TEXT,
    stage TEXT,
    summary TEXT,
    is_low_content INTEGER NOT NULL DEFAULT 0,
    summary_type TEXT NOT NULL DEFAULT 'formal',
    user_message_count INTEGER NOT NULL DEFAULT 0,
    user_char_count INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT 'none',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT DEFAULT '',
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'general',
    importance INTEGER NOT NULL DEFAULT 1,
    source_type TEXT NOT NULL DEFAULT 'manual',
    evidence TEXT,
    confidence TEXT NOT NULL DEFAULT 'medium',
    is_hypothesis INTEGER NOT NULL DEFAULT 0,
    should_persist INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS session_summaries (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    core_topics TEXT,
    next_focus TEXT,
    risk_level TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    profile_memory TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_messages (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS care_plans (
    user_id TEXT PRIMARY KEY,
    plan_text TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_task (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    scheduled_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_task_history (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    message TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handoff_documents (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    format TEXT NOT NULL,
    content TEXT NOT NULL,
    file_path TEXT,
    generated_by TEXT NOT NULL DEFAULT 'system',
    is_low_content INTEGER NOT NULL DEFAULT 0,
    content_quality TEXT NOT NULL DEFAULT 'formal',
    generated_reason TEXT,
    source_session_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clinical_screenings (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT DEFAULT '',
    instrument TEXT NOT NULL,
    score REAL NOT NULL,
    severity TEXT NOT NULL,
    label TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'none',
    risk_flags TEXT,
    is_diagnosis INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mental_state_snapshots (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    safety_level TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_password_reset_user_created ON password_reset_tokens(user_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_email_verification_token_hash ON email_verification_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_email_verification_user_created ON email_verification_tokens(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_email_outbox_status ON email_outbox(status, created_at);
CREATE INDEX IF NOT EXISTS idx_account_security_events_user ON account_security_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_account_security_events_type ON account_security_events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_account_rate_limits_action_email ON account_rate_limits(action, email_hash, created_at);
CREATE INDEX IF NOT EXISTS idx_account_rate_limits_action_ip ON account_rate_limits(action, ip_hash, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_started ON sessions(user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_open_auto_close ON sessions(status, auto_close_at);
CREATE INDEX IF NOT EXISTS idx_memories_user_created ON memories(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON session_messages(session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_task_unique ON session_task(session_id, task_type);
CREATE INDEX IF NOT EXISTS idx_session_task_status ON session_task(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_task_history_session ON session_task_history(session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_default_unique
ON handoff_documents(session_id, format, generated_by);
CREATE INDEX IF NOT EXISTS idx_screenings_user_created ON clinical_screenings(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_screenings_user_instrument ON clinical_screenings(user_id, instrument, created_at);
CREATE INDEX IF NOT EXISTS idx_screenings_user_id ON clinical_screenings(user_id, id);
CREATE INDEX IF NOT EXISTS idx_snapshots_user_created ON mental_state_snapshots(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_user_id ON mental_state_snapshots(user_id, id);
