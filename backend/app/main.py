"""echo 后端入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import chat, creators, drafts, events, works, metrics, notifications, persona, pipeline, platform, prompts, requirements, review, settings, tasks, topics, uploads, videos
from .config import get_settings
from .db import init_db
from .scheduler import setup_scheduler
from .watcher import start_inbox_watcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    setup_scheduler()
    start_inbox_watcher()
    yield


app = FastAPI(title="echo", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(x_access_token: str = Header(default="")) -> None:
    settings = get_settings()
    if settings.access_token and x_access_token != settings.access_token:
        raise HTTPException(status_code=401, detail="无效访问令牌")


API_DEPENDENCIES = [Depends(require_token)]

app.include_router(videos.router, prefix="/api/videos", tags=["videos"], dependencies=API_DEPENDENCIES)
app.include_router(persona.router, prefix="/api/persona", tags=["persona"], dependencies=API_DEPENDENCIES)
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"], dependencies=API_DEPENDENCIES)
app.include_router(events.router, prefix="/api", tags=["events"], dependencies=API_DEPENDENCIES)
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"], dependencies=API_DEPENDENCIES)
app.include_router(chat.router, prefix="/api/chat", tags=["chat"], dependencies=API_DEPENDENCIES)
app.include_router(
    requirements.router, prefix="/api/requirements", tags=["requirements"], dependencies=API_DEPENDENCIES
)
app.include_router(topics.router, prefix="/api/topics", tags=["topics"], dependencies=API_DEPENDENCIES)
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"], dependencies=API_DEPENDENCIES)
app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"], dependencies=API_DEPENDENCIES)
app.include_router(review.router, prefix="/api/review", tags=["review"], dependencies=API_DEPENDENCIES)
app.include_router(uploads.router, prefix="/api/uploads", tags=["uploads"], dependencies=API_DEPENDENCIES)
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"], dependencies=API_DEPENDENCIES)
app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"], dependencies=API_DEPENDENCIES)
app.include_router(settings.router, prefix="/api/settings", tags=["settings"], dependencies=API_DEPENDENCIES)
app.include_router(creators.router, prefix="/api/creators", tags=["creators"], dependencies=API_DEPENDENCIES)
app.include_router(platform.router, prefix="/api/platform", tags=["platform"], dependencies=API_DEPENDENCIES)
app.include_router(works.router, prefix="/api/works", tags=["works"], dependencies=API_DEPENDENCIES)


@app.get("/health")
def health():
    return {"status": "ok"}


# 静态资源：作者上传的封面 / 编辑器插图（data/ 下，dev 用相对路径）
_settings = get_settings()
_settings.covers_dir.mkdir(parents=True, exist_ok=True)
_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/covers", StaticFiles(directory=str(_settings.covers_dir)), name="covers")
app.mount("/uploads", StaticFiles(directory=str(_settings.uploads_dir)), name="uploads")

# 托管前端构建产物（存在时挂载；/api 路由已先行注册，不受影响）
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
