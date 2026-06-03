import threading

from fastapi import FastAPI

from app.config import ENABLE_DEBUG_ENDPOINTS, TASK_WORKER_ENABLED
from app.db import init_db
from app.routers import care_plan, context, handoff, health, memory, messages, profile, sessions, testing
from app.services.session_tasks import task_worker_loop


init_db()

app = FastAPI()

app.include_router(health.router)
app.include_router(memory.router)
app.include_router(sessions.router)
app.include_router(context.router)
app.include_router(messages.router)
app.include_router(profile.router)
app.include_router(care_plan.router)
app.include_router(handoff.router)
app.include_router(testing.router)

if ENABLE_DEBUG_ENDPOINTS:
    from app.routers import debug

    app.include_router(debug.router)


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
