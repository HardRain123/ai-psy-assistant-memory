import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import DATABASE_URL, IS_POSTGRES, LOG_LEVEL


logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

db_lock = threading.RLock()


def _sqlite_path_from_url(database_url: str) -> str:
    if database_url in {"sqlite:///:memory:", ":memory:"}:
        return ":memory:"

    parsed = urlparse(database_url)
    if parsed.scheme == "sqlite":
        if database_url.startswith("sqlite:///"):
            return unquote(database_url[len("sqlite:///") :])
        if database_url.startswith("sqlite://"):
            return unquote(database_url[len("sqlite://") :])

    if not parsed.scheme:
        return database_url

    return "data.db"


def _postgres_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url[len("postgres://") :]
    return database_url


def _convert_placeholders(sql: str) -> str:
    return sql.replace("?", "%s")


class CompatCursor:
    def __init__(self, cursor, is_postgres: bool):
        self._cursor = cursor
        self._is_postgres = is_postgres

    def execute(self, sql: str, params=None):
        if self._is_postgres:
            sql = _convert_placeholders(sql)
        self._cursor.execute(sql, () if params is None else params)
        return self

    def executemany(self, sql: str, seq_of_params):
        if self._is_postgres:
            sql = _convert_placeholders(sql)
        self._cursor.executemany(sql, seq_of_params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount


class CompatConnection:
    def __init__(self, conn, is_postgres: bool):
        self._conn = conn
        self._is_postgres = is_postgres

    def cursor(self):
        return CompatCursor(self._conn.cursor(), self._is_postgres)

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_database_backend() -> str:
    return "postgresql" if IS_POSTGRES else "sqlite"


def get_conn():
    if IS_POSTGRES:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL DATABASE_URL requires installing psycopg[binary]."
            ) from exc

        return CompatConnection(psycopg.connect(_postgres_url(DATABASE_URL)), True)

    sqlite_path = _sqlite_path_from_url(DATABASE_URL)
    conn = sqlite3.connect(sqlite_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return CompatConnection(conn, False)


def get_read_conn():
    if IS_POSTGRES:
        return get_conn()

    sqlite_path = _sqlite_path_from_url(DATABASE_URL)
    if sqlite_path == ":memory:":
        conn = sqlite3.connect(sqlite_path, timeout=30)
    else:
        uri = Path(sqlite_path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, timeout=5, uri=True)
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return CompatConnection(conn, False)


@contextmanager
def transaction():
    with db_lock:
        conn = get_conn()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def read_transaction():
    conn = get_read_conn()
    try:
        cur = conn.cursor()
        yield cur
        if IS_POSTGRES:
            conn.commit()
    except Exception:
        if IS_POSTGRES:
            conn.rollback()
        raise
    finally:
        conn.close()


def _column_exists(cur, table: str, column: str) -> bool:
    if IS_POSTGRES:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ? AND column_name = ?
            LIMIT 1
            """,
            (table, column),
        )
        return cur.fetchone() is not None

    cur.execute(f"PRAGMA table_info({table})")
    return column in {row[1] for row in cur.fetchall()}


def ensure_column(cur, table: str, column: str, definition: str):
    if not _column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _serial_primary_key() -> str:
    return "BIGSERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _create_schema(cur):
    serial_pk = _serial_primary_key()

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {serial_pk},
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
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id {serial_pk},
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            request_ip_hash TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id {serial_pk},
            user_id TEXT NOT NULL,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            request_ip_hash TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS email_outbox (
            id {serial_pk},
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
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS account_security_events (
            id {serial_pk},
            event_type TEXT NOT NULL,
            user_id TEXT,
            email_hash TEXT,
            ip_hash TEXT,
            user_agent TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS account_rate_limits (
            id {serial_pk},
            action TEXT NOT NULL,
            email_hash TEXT,
            ip_hash TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id {serial_pk},
            code_hash TEXT NOT NULL UNIQUE,
            created_by_user_id TEXT NOT NULL,
            used_by_user_id TEXT,
            note TEXT,
            expires_at TEXT,
            used_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id {serial_pk},
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            user_agent TEXT,
            ip_hash TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id {serial_pk},
            action TEXT NOT NULL,
            actor_user_id TEXT,
            target_user_id TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            ip_hash TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS user_roles (
            id {serial_pk},
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            created_by_user_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS safety_incidents (
            id {serial_pk},
            incident_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            session_id TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            source TEXT NOT NULL,
            source_risk_level TEXT NOT NULL,
            final_risk_level TEXT NOT NULL,
            immediate_action_required INTEGER NOT NULL DEFAULT 0,
            risk_flags TEXT,
            reason TEXT,
            source_evidence TEXT,
            trigger_message_id INTEGER,
            assigned_to_user_id TEXT,
            alert_status TEXT NOT NULL DEFAULT 'not_required',
            alert_attempt_count INTEGER NOT NULL DEFAULT 0,
            alert_last_error TEXT,
            alert_last_attempt_at TEXT,
            alert_sent_at TEXT,
            acknowledged_at TEXT,
            first_response_at TEXT,
            acknowledgement_due_at TEXT,
            first_response_due_at TEXT,
            review_due_at TEXT,
            follow_up_at TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS safety_incident_events (
            id {serial_pk},
            incident_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor_user_id TEXT,
            from_status TEXT,
            to_status TEXT,
            note TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS safety_risk_evaluations (
            id {serial_pk},
            evaluation_id TEXT NOT NULL UNIQUE,
            incident_id TEXT,
            user_id TEXT NOT NULL,
            session_id TEXT DEFAULT '',
            source TEXT NOT NULL,
            source_risk_level TEXT NOT NULL,
            final_risk_level TEXT NOT NULL,
            immediate_action_required INTEGER NOT NULL DEFAULT 0,
            risk_flags TEXT,
            reason TEXT,
            source_evidence TEXT,
            trigger_message_id INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS sensitive_access_logs (
            id {serial_pk},
            actor_user_id TEXT NOT NULL,
            target_user_id TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            reason TEXT NOT NULL,
            ip_hash TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS policy_versions (
            id {serial_pk},
            policy_key TEXT NOT NULL,
            version TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            effective_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS user_consents (
            id {serial_pk},
            user_id TEXT NOT NULL,
            consent_key TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            granted INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL,
            ip_hash TEXT,
            user_agent TEXT,
            granted_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS data_deletion_requests (
            id {serial_pk},
            request_id TEXT NOT NULL UNIQUE,
            user_id TEXT,
            user_id_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            cancellation_token_hash TEXT,
            previous_disabled_at TEXT,
            requested_at TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            cancelled_at TEXT,
            completed_at TEXT,
            backup_delete_by TEXT,
            backup_status TEXT NOT NULL DEFAULT 'pending',
            backup_attempt_count INTEGER NOT NULL DEFAULT 0,
            backup_last_attempt_at TEXT,
            backup_last_error TEXT,
            deletion_counts_json TEXT,
            deletion_manifest_json TEXT,
            certificate_id TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS complaints (
            id {serial_pk},
            complaint_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS compliance_audit_logs (
            id {serial_pk},
            action TEXT NOT NULL,
            actor_user_id TEXT,
            target_user_id TEXT,
            resource_id TEXT,
            details_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS launch_controls (
            control_key TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            metadata_json TEXT,
            updated_by_user_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS memories (
            id {serial_pk},
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
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            session_id TEXT UNIQUE,
            user_id TEXT NOT NULL,
            dify_conversation_id TEXT,
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
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS session_summaries (
            id {serial_pk},
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            core_topics TEXT,
            next_focus TEXT,
            risk_level TEXT NOT NULL DEFAULT 'none',
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            profile_memory TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS session_messages (
            id {serial_pk},
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id TEXT,
            external_message_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            risk_level TEXT NOT NULL DEFAULT 'none',
            sync_status TEXT NOT NULL DEFAULT 'complete',
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS care_plans (
            user_id TEXT PRIMARY KEY,
            plan_text TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS session_task (
            id {serial_pk},
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
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS session_task_history (
            id {serial_pk},
            task_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT,
            message TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS handoff_documents (
            id {serial_pk},
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
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS clinical_screenings (
            id {serial_pk},
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
        )
        """
    )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS mental_state_snapshots (
            id {serial_pk},
            user_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            safety_level TEXT NOT NULL DEFAULT 'none',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _migrate_existing_schema(cur):
    ensure_column(cur, "users", "username", "username TEXT")
    ensure_column(cur, "users", "email", "email TEXT")
    ensure_column(cur, "users", "email_verified_at", "email_verified_at TEXT")
    ensure_column(cur, "users", "password_hash", "password_hash TEXT")
    ensure_column(cur, "users", "is_admin", "is_admin INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "users", "last_login_at", "last_login_at TEXT")
    ensure_column(cur, "users", "disabled_at", "disabled_at TEXT")

    ensure_column(cur, "memories", "session_id", "session_id TEXT DEFAULT ''")
    ensure_column(cur, "memories", "memory_type", "memory_type TEXT NOT NULL DEFAULT 'general'")
    ensure_column(cur, "memories", "importance", "importance INTEGER NOT NULL DEFAULT 1")
    ensure_column(cur, "memories", "source_type", "source_type TEXT NOT NULL DEFAULT 'manual'")
    ensure_column(cur, "memories", "evidence", "evidence TEXT")
    ensure_column(cur, "memories", "confidence", "confidence TEXT NOT NULL DEFAULT 'medium'")
    ensure_column(cur, "memories", "is_hypothesis", "is_hypothesis INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "memories", "should_persist", "should_persist INTEGER NOT NULL DEFAULT 1")
    ensure_column(cur, "memories", "updated_at", "updated_at TEXT")

    ensure_column(cur, "sessions", "session_id", "session_id TEXT")
    ensure_column(cur, "sessions", "dify_conversation_id", "dify_conversation_id TEXT")
    ensure_column(cur, "sessions", "final_saved_at", "final_saved_at TEXT")
    ensure_column(cur, "sessions", "auto_close_at", "auto_close_at TEXT")
    ensure_column(cur, "sessions", "close_reason", "close_reason TEXT")
    ensure_column(cur, "sessions", "timeout_checked_at", "timeout_checked_at TEXT")
    ensure_column(cur, "sessions", "stage", "stage TEXT")
    ensure_column(cur, "sessions", "summary", "summary TEXT")
    ensure_column(cur, "sessions", "is_low_content", "is_low_content INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "sessions", "summary_type", "summary_type TEXT NOT NULL DEFAULT 'formal'")
    ensure_column(cur, "sessions", "user_message_count", "user_message_count INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "sessions", "user_char_count", "user_char_count INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "sessions", "risk_level", "risk_level TEXT NOT NULL DEFAULT 'none'")
    ensure_column(cur, "sessions", "created_at", "created_at TEXT")
    ensure_column(cur, "sessions", "updated_at", "updated_at TEXT")

    ensure_column(cur, "session_summaries", "risk_level", "risk_level TEXT NOT NULL DEFAULT 'none'")
    ensure_column(cur, "session_summaries", "updated_at", "updated_at TEXT")
    ensure_column(cur, "user_profiles", "created_at", "created_at TEXT")
    ensure_column(cur, "session_messages", "turn_id", "turn_id TEXT")
    ensure_column(cur, "session_messages", "external_message_id", "external_message_id TEXT")
    ensure_column(cur, "session_messages", "risk_level", "risk_level TEXT NOT NULL DEFAULT 'none'")
    ensure_column(cur, "session_messages", "sync_status", "sync_status TEXT NOT NULL DEFAULT 'complete'")
    ensure_column(cur, "session_messages", "updated_at", "updated_at TEXT")
    ensure_column(cur, "care_plans", "created_at", "created_at TEXT")
    ensure_column(cur, "session_task_history", "result", "result TEXT")
    ensure_column(cur, "session_task_history", "message", "message TEXT")
    ensure_column(cur, "handoff_documents", "is_low_content", "is_low_content INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "handoff_documents", "content_quality", "content_quality TEXT NOT NULL DEFAULT 'formal'")
    ensure_column(cur, "handoff_documents", "generated_reason", "generated_reason TEXT")
    ensure_column(cur, "handoff_documents", "source_session_count", "source_session_count INTEGER NOT NULL DEFAULT 1")
    ensure_column(cur, "safety_incidents", "source_evidence", "source_evidence TEXT")
    ensure_column(cur, "safety_incidents", "trigger_message_id", "trigger_message_id INTEGER")
    ensure_column(cur, "safety_incidents", "assigned_to_user_id", "assigned_to_user_id TEXT")
    ensure_column(cur, "safety_incidents", "alert_status", "alert_status TEXT NOT NULL DEFAULT 'not_required'")
    ensure_column(cur, "safety_incidents", "alert_attempt_count", "alert_attempt_count INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "safety_incidents", "alert_last_error", "alert_last_error TEXT")
    ensure_column(cur, "safety_incidents", "alert_last_attempt_at", "alert_last_attempt_at TEXT")
    ensure_column(cur, "safety_incidents", "alert_sent_at", "alert_sent_at TEXT")
    ensure_column(cur, "safety_incidents", "acknowledged_at", "acknowledged_at TEXT")
    ensure_column(cur, "safety_incidents", "first_response_at", "first_response_at TEXT")
    ensure_column(cur, "safety_incidents", "acknowledgement_due_at", "acknowledgement_due_at TEXT")
    ensure_column(cur, "safety_incidents", "first_response_due_at", "first_response_due_at TEXT")
    ensure_column(cur, "safety_incidents", "review_due_at", "review_due_at TEXT")
    ensure_column(cur, "safety_incidents", "follow_up_at", "follow_up_at TEXT")
    ensure_column(cur, "safety_incidents", "resolved_at", "resolved_at TEXT")
    ensure_column(cur, "data_deletion_requests", "backup_delete_by", "backup_delete_by TEXT")
    ensure_column(
        cur,
        "data_deletion_requests",
        "backup_status",
        "backup_status TEXT NOT NULL DEFAULT 'pending'",
    )
    ensure_column(
        cur,
        "data_deletion_requests",
        "backup_attempt_count",
        "backup_attempt_count INTEGER NOT NULL DEFAULT 0",
    )
    ensure_column(cur, "data_deletion_requests", "backup_last_attempt_at", "backup_last_attempt_at TEXT")
    ensure_column(cur, "data_deletion_requests", "backup_last_error", "backup_last_error TEXT")
    ensure_column(cur, "data_deletion_requests", "deletion_counts_json", "deletion_counts_json TEXT")
    ensure_column(cur, "data_deletion_requests", "deletion_manifest_json", "deletion_manifest_json TEXT")
    ensure_column(cur, "data_deletion_requests", "certificate_id", "certificate_id TEXT")
    ensure_column(cur, "data_deletion_requests", "last_error", "last_error TEXT")

    cur.execute("UPDATE sessions SET session_id = id WHERE session_id IS NULL OR session_id = ''")
    cur.execute("UPDATE sessions SET created_at = started_at WHERE created_at IS NULL")
    cur.execute("UPDATE sessions SET updated_at = started_at WHERE updated_at IS NULL")
    cur.execute("UPDATE sessions SET risk_level = 'none' WHERE risk_level IS NULL OR risk_level = ''")
    cur.execute("UPDATE sessions SET summary_type = 'formal' WHERE summary_type IS NULL OR summary_type = ''")
    cur.execute("UPDATE memories SET session_id = '' WHERE session_id IS NULL")
    cur.execute("UPDATE memories SET updated_at = created_at WHERE updated_at IS NULL")
    cur.execute("UPDATE memories SET confidence = 'medium' WHERE confidence IS NULL OR confidence = ''")
    cur.execute("UPDATE session_summaries SET updated_at = created_at WHERE updated_at IS NULL")
    cur.execute("UPDATE session_messages SET sync_status = 'complete' WHERE sync_status IS NULL OR sync_status = ''")
    cur.execute("UPDATE session_messages SET updated_at = created_at WHERE updated_at IS NULL")
    cur.execute("UPDATE user_profiles SET created_at = updated_at WHERE created_at IS NULL")
    cur.execute("UPDATE care_plans SET created_at = updated_at WHERE created_at IS NULL")


def _create_indexes(cur):
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_invite_codes_hash ON invite_codes(code_hash)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invite_codes_created ON invite_codes(created_at)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_sessions_token ON auth_sessions(token_hash)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, expires_at)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_user_created ON password_reset_tokens(user_id, created_at)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_verification_token_hash ON email_verification_tokens(token_hash)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_email_verification_user_created ON email_verification_tokens(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_email_outbox_status ON email_outbox(status, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_account_security_events_user ON account_security_events(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_account_security_events_type ON account_security_events(event_type, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_account_rate_limits_action_email ON account_rate_limits(action, email_hash, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_account_rate_limits_action_ip ON account_rate_limits(action, ip_hash, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_logs(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_target ON admin_audit_logs(target_user_id, created_at)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_roles_unique ON user_roles(user_id, role)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role, user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_safety_incidents_queue ON safety_incidents(status, final_risk_level, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_safety_incidents_user ON safety_incidents(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_safety_incidents_session ON safety_incidents(session_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_safety_incidents_alert ON safety_incidents(alert_status, alert_last_attempt_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_safety_events_incident ON safety_incident_events(incident_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_safety_evaluations_user ON safety_risk_evaluations(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_safety_evaluations_incident ON safety_risk_evaluations(incident_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sensitive_access_actor ON sensitive_access_logs(actor_user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sensitive_access_target ON sensitive_access_logs(target_user_id, created_at)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_versions_unique ON policy_versions(policy_key, version)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_policy_versions_active ON policy_versions(policy_key, active)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_consents_user ON user_consents(user_id, consent_key, granted_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deletion_requests_due ON data_deletion_requests(status, scheduled_for)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deletion_requests_user ON data_deletion_requests(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_complaints_user ON complaints(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_compliance_audit_target ON compliance_audit_logs(target_user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_launch_controls_enabled ON launch_controls(enabled, updated_at)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_started ON sessions(user_id, started_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_open_auto_close ON sessions(status, auto_close_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_user_created ON memories(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_created ON session_messages(session_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_turn_role ON session_messages(session_id, turn_id, role)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_external ON session_messages(external_message_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_session_task_unique ON session_task(session_id, task_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_session_task_status ON session_task(status, scheduled_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_task_history_session ON session_task_history(session_id, created_at)")
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_default_unique
        ON handoff_documents(session_id, format, generated_by)
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_screenings_user_created ON clinical_screenings(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_screenings_user_instrument ON clinical_screenings(user_id, instrument, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_screenings_user_id ON clinical_screenings(user_id, id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_user_created ON mental_state_snapshots(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_user_id ON mental_state_snapshots(user_id, id)")


def init_db():
    with db_lock:
        conn = get_conn()
        try:
            if not IS_POSTGRES and _sqlite_path_from_url(DATABASE_URL) != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL;")
            cur = conn.cursor()
            _create_schema(cur)
            _migrate_existing_schema(cur)
            _create_indexes(cur)
            conn.commit()
            logger.info("database_initialized backend=%s", get_database_backend())
        except Exception:
            conn.rollback()
            logger.exception("database_initialization_failed backend=%s", get_database_backend())
            raise
        finally:
            conn.close()


def check_db_health() -> dict:
    try:
        conn = get_conn()
        try:
            conn.execute("SELECT 1")
            return {"ok": True, "backend": get_database_backend()}
        finally:
            conn.close()
    except Exception:
        logger.exception("db_health_check_failed backend=%s", get_database_backend())
        return {
            "ok": False,
            "backend": get_database_backend(),
            "error": "db_health_failed",
            "message": "数据库状态检查失败，请稍后再试。",
        }
