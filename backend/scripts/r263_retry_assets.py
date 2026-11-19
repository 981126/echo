"""R-263：只重试首轮失败的 ASR，并分批聚合结构/表达资产。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models.author_generation import AuthorAsset
from app.models.task import BackgroundTask
from app.models.video import Video
from app.services.author_assets import build_programmatic_style_assets, extract_assets_from_videos, transcript_text
from app.services.creator_service import current_creator_id


def _retry_one(video_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if video is None:
            return {"video_id": video_id, "status": "missing"}
        result = extract_assets_from_videos(db, [video])
        return {"video_id": video_id, "status": "succeeded", **result}
    except Exception as exc:  # noqa: BLE001 单篇重试失败单独记录
        db.rollback()
        return {"video_id": video_id, "status": "failed", "error": str(exc)[:400]}
    finally:
        db.close()


def main() -> None:
    db = SessionLocal()
    try:
        creator_id = current_creator_id(db)
        if creator_id is None:
            raise RuntimeError("没有当前主博主")
        task = (
            db.query(BackgroundTask)
            .filter(BackgroundTask.kind == "author_assets")
            .order_by(BackgroundTask.id.desc())
            .first()
        )
        if task is None:
            raise RuntimeError("没有首轮资产重建任务")
        initial = json.loads(task.result or "{}")
        error_ids = [int(item["video_id"]) for item in initial.get("errors") or [] if item.get("video_id")]
        videos = (
            db.query(Video)
            .options(selectinload(Video.transcript))
            .filter(Video.creator_id == creator_id, Video.is_ad.is_(False))
            .order_by(Video.id)
            .all()
        )
        usable = [video for video in videos if transcript_text(video)]
    finally:
        db.close()

    retry_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="r263-asset-retry") as executor:
        futures = {executor.submit(_retry_one, video_id): video_id for video_id in error_ids}
        for future in as_completed(futures):
            retry_results.append(future.result())

    aggregate_results: list[dict[str, Any]] = []
    for index in range(0, min(len(usable), 12), 4):
        batch = usable[index : index + 4]
        db = SessionLocal()
        try:
            result = extract_assets_from_videos(db, batch, aggregate=True)
            aggregate_results.append({"video_ids": [video.id for video in batch], **result})
        except Exception as exc:  # noqa: BLE001 聚合失败单独记录
            db.rollback()
            aggregate_results.append(
                {"video_ids": [video.id for video in batch], "status": "failed", "error": str(exc)[:400]}
            )
        finally:
            db.close()

    db = SessionLocal()
    try:
        build_programmatic_style_assets(db, creator_id, usable[:12])
        grouped: dict[str, int] = {}
        for kind, status in (
            db.query(AuthorAsset.asset_kind, AuthorAsset.status)
            .filter(AuthorAsset.creator_id == creator_id)
            .all()
        ):
            key = f"{kind}:{status}"
            grouped[key] = grouped.get(key, 0) + 1
        report = {
            "total": len(usable),
            "initial": initial,
            "retry": {
                "succeeded": sum(item.get("status") == "succeeded" for item in retry_results),
                "failed": sum(item.get("status") == "failed" for item in retry_results),
                "results": retry_results,
            },
            "aggregate": aggregate_results,
            "counts": grouped,
        }
        path = Path(__file__).resolve().parents[2] / "data" / "backups" / "r263-asset-rebuild-report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)
    finally:
        db.close()


if __name__ == "__main__":
    main()
