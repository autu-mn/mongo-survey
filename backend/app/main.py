from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import get_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_db())
    yield


app = FastAPI(title="MongoDB 问卷系统", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}
