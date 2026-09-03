"""批量导入 data/videos 下的历史视频并转写（M1：历史 50 条）。

用法：
    cd backend && pip install -r requirements.txt
    python scripts/transcribe_all.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models.video import Video  # noqa: E402
from app.services.ingest import import_video_task  # noqa: E402
from app.tasks import start_task  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v", ".ts"}


def main() -> None:
    init_db()
    settings = get_settings()
    videos_dir = settings.videos_dir
    videos_dir.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        files = sorted(
            p for p in videos_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS
        )
        created = 0
        for path in files:
            if db.query(Video).filter(Video.filename == path.name).first() is not None:
                continue
            video = Video(filename=path.name)
            db.add(video)
            db.commit()
            db.refresh(video)
            start_task("import_video", {"video_id": video.id}, import_video_task)
            created += 1
            print(f"已登记并触发转写: {path.name}")
        print(f"完成：新增 {created} 条，共 {len(files)} 个视频文件")
    finally:
        db.close()


if __name__ == "__main__":
    main()
