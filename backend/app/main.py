from fastapi import FastAPI

app = FastAPI(title="MongoDB 问卷系统", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}
