"""echo 后端入口。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import chat, drafts, metrics, persona, pipeline, requirements, review, tasks, topics, videos
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
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"], dependencies=API_DEPENDENCIES)
app.include_router(chat.router, prefix="/api/chat", tags=["chat"], dependencies=API_DEPENDENCIES)
app.include_router(
    requirements.router, prefix="/api/requirements", tags=["requirements"], dependencies=API_DEPENDENCIES
)
app.include_router(topics.router, prefix="/api/topics", tags=["topics"], dependencies=API_DEPENDENCIES)
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"], dependencies=API_DEPENDENCIES)
app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"], dependencies=API_DEPENDENCIES)
app.include_router(review.router, prefix="/api/review", tags=["review"], dependencies=API_DEPENDENCIES)


@app.get("/health")
def health():
    return {"status": "ok"}


# 托管前端构建产物（存在时挂载；/api 路由已先行注册，不受影响）
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
