"""echo 后端入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import benchmark, chat, creators, drafts, events, inspiration, library, works, notifications, opportunities, persona, pipeline, platform, prompts, settings, tasks, topics, uploads, videos
from .config import get_settings
from .core.log import get_logger, setup_logging
from .db import init_db
from .scheduler import setup_scheduler
from .tasks import mark_interrupted_tasks_on_startup
from .watcher import start_inbox_watcher

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()  # R-133：全后端此前零日志，失败不可观测
    # R-145：启动即自动升级，所以升级前先自动备份（有待应用的结构变更时才做，失败不阻断启动）
    from .core import schema_guard
    from .db import engine

    pending = schema_guard.pending_upgrade(engine)
    if pending:
        changed = list(pending.get("missing_tables") or []) + list(pending.get("missing_columns") or [])
        log.warning("检测到待应用的结构变更（%s），升级前先自动备份", "、".join(changed) or "未知")
        schema_guard.auto_backup_before_upgrade(engine)
    init_db()
    # R-144 B：结构自检（模型声明的列 vs 实际库）——缺列时日志 + 站内通知，绝不阻塞启动
    schema_guard.run_startup_check(engine)
    mark_interrupted_tasks_on_startup()  # R-089：重启后清理遗留 running 任务
    from .services.pipeline import mark_stale_pipeline_runs_on_startup

    mark_stale_pipeline_runs_on_startup()  # R-133：流水线 running 卡死自愈
    setup_scheduler()
    start_inbox_watcher()
    # R-179：历史封面补缩略图（后台线程，幂等；首次约几分钟，之后秒过）
    from .core import thumbs

    thumbs.prewarm_async(_settings.covers_dir, 400, logger=log)
    log.info("echo 后端启动完成")
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
app.include_router(benchmark.router, prefix="/api/benchmark", tags=["benchmark"], dependencies=API_DEPENDENCIES)
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"], dependencies=API_DEPENDENCIES)
app.include_router(chat.router, prefix="/api/chat", tags=["chat"], dependencies=API_DEPENDENCIES)
app.include_router(topics.router, prefix="/api/topics", tags=["topics"], dependencies=API_DEPENDENCIES)
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"], dependencies=API_DEPENDENCIES)
app.include_router(uploads.router, prefix="/api/uploads", tags=["uploads"], dependencies=API_DEPENDENCIES)
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"], dependencies=API_DEPENDENCIES)
app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"], dependencies=API_DEPENDENCIES)
app.include_router(settings.router, prefix="/api/settings", tags=["settings"], dependencies=API_DEPENDENCIES)
app.include_router(creators.router, prefix="/api/creators", tags=["creators"], dependencies=API_DEPENDENCIES)
app.include_router(platform.router, prefix="/api/platform", tags=["platform"], dependencies=API_DEPENDENCIES)
app.include_router(works.router, prefix="/api/works", tags=["works"], dependencies=API_DEPENDENCIES)
app.include_router(library.router, prefix="/api/library", tags=["library"], dependencies=API_DEPENDENCIES)
app.include_router(opportunities.router, prefix="/api/opportunities", tags=["opportunities"], dependencies=API_DEPENDENCIES)
app.include_router(inspiration.router, prefix="/api/inspiration", tags=["inspiration"], dependencies=API_DEPENDENCIES)


@app.get("/health")
def health():
    return {"status": "ok"}


# 静态资源：作者上传的封面 / 编辑器插图（data/ 下，dev 用相对路径）
_settings = get_settings()
_settings.covers_dir.mkdir(parents=True, exist_ok=True)
_settings.uploads_dir.mkdir(parents=True, exist_ok=True)


@app.get("/covers/{name:path}", include_in_schema=False)
def cover_file(name: str, w: int | None = None):
    """封面：带 `?w=` 时按需生成缩略图并落盘缓存（R-179），否则原图。

    必须注册在 `/covers` 静态挂载**之前**（Starlette 按注册顺序匹配）；缩图失败一律回落原图。
    """
    from fastapi.responses import FileResponse

    from .core import thumbs

    root = _settings.covers_dir.resolve()
    src = (root / name.replace("\\", "/").lstrip("/")).resolve()
    if not str(src).startswith(str(root)) or not src.is_file():
        raise HTTPException(status_code=404, detail="封面不存在")
    width = thumbs.clamp_width(w)
    if width and src.suffix.lower() in thumbs.IMAGE_EXTS:
        thumb = thumbs.thumb_file(root, name, width)
        if not thumb.is_file():
            thumbs.make_thumb(src, thumb, width)  # 失败/坏图 → 下面回落原图
        if thumb.is_file():
            return FileResponse(
                thumb,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=604800"},
            )
    return FileResponse(src, headers={"Cache-Control": "public, max-age=86400"})


app.mount("/covers", StaticFiles(directory=str(_settings.covers_dir)), name="covers")
_settings.videos_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media/videos", StaticFiles(directory=str(_settings.videos_dir)), name="media_videos")
app.mount("/uploads", StaticFiles(directory=str(_settings.uploads_dir)), name="uploads")

# 托管前端构建产物（存在时挂载；/api 路由已先行注册，不受影响）
# R-164：全新前端 frontend_v2（React）挂 /v2，与老前端并存互不影响
_FRONTEND_V2_DIST = Path(__file__).resolve().parents[2] / "frontend_v2" / "dist"
if _FRONTEND_V2_DIST.exists():
    app.mount("/v2", StaticFiles(directory=str(_FRONTEND_V2_DIST), html=True), name="static_v2")
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
