import os
import sys
import tempfile
from pathlib import Path


TEST_DB = Path(tempfile.gettempdir()) / "mvp-test.db"

os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB}")
os.environ.setdefault("TASK_WORKER_ENABLED", "false")
os.environ.setdefault("ENABLE_DEBUG_ENDPOINTS", "false")
os.environ.setdefault("AUTH_SECRET", "test-auth-secret")
os.environ.setdefault("BACKEND_SHARED_TOKEN", "test-backend-token")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin-password")

if "app.main" not in sys.modules:
    for path in [TEST_DB, TEST_DB.with_name("mvp-test.db-wal"), TEST_DB.with_name("mvp-test.db-shm")]:
        if path.exists():
            path.unlink()
