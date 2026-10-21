from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import get_db, init_db
from app.errors import register_error_handlers
from app.routers import auth, me, public, questions, stats, surveys

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
PAGES_DIR = FRONTEND_DIR / "pages"


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
app.include_router(stats.router)
app.include_router(me.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------- 前端页面（与 docs/需求分析与界面设计.md 中的页面一一对应） ----------

app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")

PAGE_ROUTES = {
    "/": "list.html",                          # 我的问卷列表
    "/login": "login.html",                    # 登录 / 注册
    "/surveys/{survey_id}": "detail.html",     # 问卷管理页
    "/surveys/{survey_id}/edit": "editor.html",
    "/surveys/{survey_id}/preview": "fill.html",
    "/surveys/{survey_id}/share": "share.html",
    "/surveys/{survey_id}/stats": "stats.html",
    "/survey/{slug}": "fill.html",             # 填写者入口
    "/me/responses/{response_id}": "myresponse.html",  # 我的答卷（只读）
}


def _page(filename: str):
    def handler():
        return FileResponse(PAGES_DIR / filename, headers={"Cache-Control": "no-cache"})
    return handler


for _path, _file in PAGE_ROUTES.items():
    app.add_api_route(_path, _page(_file), methods=["GET"], include_in_schema=False)
