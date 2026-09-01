"""echo 后端入口。"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .api import persona, tasks, videos
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


app = FastAPI(title="echo", version="0.1.0", lifespan=lifespan)

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


@app.get("/health")
def health():
    return {"status": "ok"}
