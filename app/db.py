import logging
import sqlite3
import threading
from contextlib import contextmanager
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
    if sqlite_path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL;")
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
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            risk_level TEXT NOT NULL DEFAULT 'none',
            created_at TEXT NOT NULL
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


def _migrate_existing_schema(cur):
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
    ensure_column(cur, "session_messages", "risk_level", "risk_level TEXT NOT NULL DEFAULT 'none'")
    ensure_column(cur, "care_plans", "created_at", "created_at TEXT")
    ensure_column(cur, "session_task_history", "result", "result TEXT")
    ensure_column(cur, "session_task_history", "message", "message TEXT")
    ensure_column(cur, "handoff_documents", "is_low_content", "is_low_content INTEGER NOT NULL DEFAULT 0")
    ensure_column(cur, "handoff_documents", "content_quality", "content_quality TEXT NOT NULL DEFAULT 'formal'")
    ensure_column(cur, "handoff_documents", "generated_reason", "generated_reason TEXT")
    ensure_column(cur, "handoff_documents", "source_session_count", "source_session_count INTEGER NOT NULL DEFAULT 1")

    cur.execute("UPDATE sessions SET session_id = id WHERE session_id IS NULL OR session_id = ''")
    cur.execute("UPDATE sessions SET created_at = started_at WHERE created_at IS NULL")
    cur.execute("UPDATE sessions SET updated_at = started_at WHERE updated_at IS NULL")
    cur.execute("UPDATE sessions SET risk_level = 'none' WHERE risk_level IS NULL OR risk_level = ''")
    cur.execute("UPDATE sessions SET summary_type = 'formal' WHERE summary_type IS NULL OR summary_type = ''")
    cur.execute("UPDATE memories SET session_id = '' WHERE session_id IS NULL")
    cur.execute("UPDATE memories SET updated_at = created_at WHERE updated_at IS NULL")
    cur.execute("UPDATE memories SET confidence = 'medium' WHERE confidence IS NULL OR confidence = ''")
    cur.execute("UPDATE session_summaries SET updated_at = created_at WHERE updated_at IS NULL")
    cur.execute("UPDATE user_profiles SET created_at = updated_at WHERE created_at IS NULL")
    cur.execute("UPDATE care_plans SET created_at = updated_at WHERE created_at IS NULL")


def _create_indexes(cur):
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_started ON sessions(user_id, started_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_open_auto_close ON sessions(status, auto_close_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_user_created ON memories(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_created ON session_messages(session_id, created_at)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_session_task_unique ON session_task(session_id, task_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_session_task_status ON session_task(status, scheduled_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_task_history_session ON session_task_history(session_id, created_at)")
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_default_unique
        ON handoff_documents(session_id, format, generated_by)
        """
    )


def init_db():
    with db_lock:
        conn = get_conn()
        try:
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
    except Exception as exc:
        return {"ok": False, "backend": get_database_backend(), "error": str(exc)}
