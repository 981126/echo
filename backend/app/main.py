"""echo 后端入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from .api import benchmark, chat, creators, douyin_review, drafts, events, inspiration, library, works, notifications, opportunities, persona, pipeline, platform, prompts, settings, tasks, topics, uploads, videos
from .config import get_settings
from .db import engine
from .core.log import get_logger, setup_logging
from .core.request_metrics import RequestTimingMiddleware, install_sql_counter
from .migrations import run_migrations
from .scheduler import setup_scheduler
from .tasks import mark_interrupted_tasks_on_startup
from .watcher import start_inbox_watcher

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()  # R-133：全后端此前零日志，失败不可观测
    run_migrations()
    mark_interrupted_tasks_on_startup()  # R-089：重启后清理遗留 running 任务
    # R-208：一次性按规则清理历史积压的人设待确认建议（Kv 标记保证只跑一次，后台线程）
    from .services.ingest import maybe_auto_confirm_backlog_on_startup

    maybe_auto_confirm_backlog_on_startup()
    # R-226：一次性清洗历史标题里的 #话题（Kv 标记幂等，后台线程）
    from .services.title_cleanup import maybe_clean_hashtag_titles_on_startup

    maybe_clean_hashtag_titles_on_startup()
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
    expose_headers=["X-Response-Time"],
)

app.add_middleware(RequestTimingMiddleware)
install_sql_counter(engine)
# R-243：全站响应压缩（SSE text/event-stream 与图片/字体等已被 starlette 默认排除）
app.add_middleware(GZipMiddleware, minimum_size=1024)


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
app.include_router(douyin_review.router, prefix="/api/douyin-review", tags=["douyin-review"], dependencies=API_DEPENDENCIES)


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
            thumbs.make_thumb(src, thumb, width)  # 失败/坏图 → 下面回退
        if not thumb.is_file() and width != 400:
            # R-243：目标宽度生成不可用（如运行环境无写权限）时，回退已预热的 w400 缩略图，
            # 仍比原图小一个数量级；w400 也没有才回落原图。
            fallback = thumbs.thumb_file(root, name, 400)
            if fallback.is_file():
                thumb = fallback
        if thumb.is_file():
            return FileResponse(
                thumb,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=604800"},
            )
    return FileResponse(src, headers={"Cache-Control": "public, max-age=86400"})


class _CachedStaticFiles(StaticFiles):
    """R-243：静态资源带缓存头；hashed 资源（assets/）可 immutable，html/入口保持回源校验。"""

    def __init__(self, *args, cache_control: str, immutable_assets: bool = False, **kwargs):
        self._cache_control = cache_control
        self._immutable_assets = immutable_assets
        super().__init__(*args, **kwargs)

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            if self._immutable_assets and str(path).startswith("assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = self._cache_control
        return response


app.mount(
    "/covers",
    _CachedStaticFiles(directory=str(_settings.covers_dir), cache_control="public, max-age=86400"),
    name="covers",
)
_settings.videos_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/media/videos",
    _CachedStaticFiles(directory=str(_settings.videos_dir), cache_control="public, max-age=86400"),
    name="media_videos",
)
app.mount(
    "/uploads",
    _CachedStaticFiles(directory=str(_settings.uploads_dir), cache_control="public, max-age=86400"),
    name="uploads",
)

# 托管前端构建产物（存在时挂载；/api 路由已先行注册，不受影响）
# R-208：老前端 frontend/ 已下线，根路径直接托管 frontend_v2（React）
_FRONTEND_V2_DIST = Path(__file__).resolve().parents[2] / "frontend_v2" / "dist"
if _FRONTEND_V2_DIST.exists():
    app.mount(
        "/",
        _CachedStaticFiles(
            directory=str(_FRONTEND_V2_DIST),
            html=True,
            cache_control="no-cache",
            immutable_assets=True,
        ),
        name="static_v2",
    )
