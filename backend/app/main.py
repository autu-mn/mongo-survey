from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import get_db, init_db
from app.errors import register_error_handlers
from app.routers import auth, public, questions, surveys


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_db())
    yield


app = FastAPI(title="MongoDB 问卷系统", version="1.0.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(auth.router)
app.include_router(surveys.router)
app.include_router(questions.router)
app.include_router(public.router)
app.include_router(public.preview_router)


@app.get("/health")
def health():
    return {"status": "ok"}
