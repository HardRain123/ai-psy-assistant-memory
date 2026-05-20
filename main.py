from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/memory/{user_id}")
def get_memory(user_id: str):
    return {"user_id": user_id, "memory": []}
