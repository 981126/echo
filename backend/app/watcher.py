"""data/inbox 文件夹监听：拖入视频自动入库并触发导入流水线。"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .config import get_settings
from .db import SessionLocal
from .models.video import Video

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
            path.replace(dest)
            if db.query(Video).filter(Video.filename == new_name).first() is None:
                video = Video(filename=new_name)
                db.add(video)
                db.commit()  # R-033：只入库不自动转写，编辑页手动「语音转文字」
    finally:
        db.close()


def start_inbox_watcher(interval_seconds: float = 10.0) -> None:
    settings = get_settings()

    def loop() -> None:
        while True:
            try:
                _scan_once(settings)
            except Exception:  # noqa: BLE001  监听循环不允许退出
                pass
            time.sleep(interval_seconds)

    threading.Thread(target=loop, daemon=True).start()
