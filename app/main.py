import threading

from fastapi import Depends, FastAPI

from app.config import ENABLE_DEBUG_ENDPOINTS, TASK_WORKER_ENABLED
from app.db import init_db, transaction
from app.errors import install_exception_handlers
from app.routers import admin, auth, care_plan, context, dify, handoff, health, memory, messages, profile, screening, sessions, testing
from app.security import require_backend_token
from app.services.auth import bootstrap_admin
from app.services.session_tasks import task_worker_loop


init_db()
with transaction() as cur:
    bootstrap_admin(cur)

app = FastAPI()
install_exception_handlers(app)

protected = [Depends(require_backend_token)]

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(memory.router, dependencies=protected)
app.include_router(sessions.router, dependencies=protected)
app.include_router(context.router, dependencies=protected)
app.include_router(dify.router, dependencies=protected)
app.include_router(messages.router, dependencies=protected)
app.include_router(profile.router, dependencies=protected)
app.include_router(care_plan.router, dependencies=protected)
app.include_router(handoff.router, dependencies=protected)
app.include_router(screening.router, dependencies=protected)
app.include_router(testing.router)

if ENABLE_DEBUG_ENDPOINTS:
    from app.routers import debug

    app.include_router(debug.router, dependencies=protected)


task_worker_started = False


@app.on_event("startup")
def start_task_worker():
    global task_worker_started

    if not TASK_WORKER_ENABLED:
        return

    if task_worker_started:
        return

    t = threading.Thread(target=task_worker_loop, daemon=True)
    t.start()
    task_worker_started = True
