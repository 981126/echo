"""data/inbox 文件夹监听：拖入视频自动入库并触发导入流水线。"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .config import get_settings
from .core.log import get_logger
from .db import SessionLocal
from .models.video import Video

log = get_logger("watcher")

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v", ".ts"}


def _scan_once(settings) -> None:
    inbox: Path = settings.inbox_dir
    videos_dir: Path = settings.videos_dir
    inbox.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        for path in sorted(inbox.iterdir()):
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
                continue
            new_name = f"{uuid.uuid4().hex[:8]}_{path.name}"
            dest = videos_dir / new_name
            if db.query(Video).filter(Video.filename == new_name).first() is not None:
                continue
            # R-134：先入库成功再移动文件——原实现先移走后入库，入库失败会让文件"消失"（inbox 没了、库里也没有）
            video = Video(filename=new_name)
            db.add(video)
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("inbox 入库失败，文件保留在 inbox 待重试：%s", path)
                continue
            try:
                path.replace(dest)
            except Exception:  # noqa: BLE001
                log.exception("inbox 文件移动失败，回滚入库记录：%s", path)
                try:
                    db.delete(video)
                    db.commit()
                except Exception:  # noqa: BLE001
                    db.rollback()
                    log.exception("回滚入库记录失败：%s", new_name)
    finally:
        db.close()


def start_inbox_watcher(interval_seconds: float = 10.0) -> None:
    settings = get_settings()

    def loop() -> None:
        while True:
            try:
                _scan_once(settings)
            except Exception:  # noqa: BLE001  监听循环不允许退出，但必须留痕（R-133）
                log.exception("inbox 扫描失败")
            time.sleep(interval_seconds)

    threading.Thread(target=loop, daemon=True).start()
