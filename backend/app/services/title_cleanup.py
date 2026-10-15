"""R-226：一次性清洗历史标题里的 #话题 标签（Kv 标记保证只跑一次，后台线程执行）。

覆盖 `platform_posts.title` / `works.title` / `videos.title`；只在不改空的前提下清洗，
原始文案仍保留在 `platform_posts.desc` / `platform_posts.raw`。
"""

from __future__ import annotations

import threading

from ..core.log import get_logger
from ..db import SessionLocal
from ..models.kv import Kv
from ..models.platform import PlatformPost
from ..models.video import Video
from ..models.work import Work
from .text_tags import strip_hashtags

DONE_KEY = "r226_title_hashtag_cleanup_done"
log = get_logger("title_cleanup")


def clean_hashtag_titles(db) -> dict:
    """把三张表标题里的 #话题 去掉（去完为空则保留原标题）。返回各表清洗条数。"""
    changed = {"platform_posts": 0, "works": 0, "videos": 0}
    for model, key in ((PlatformPost, "platform_posts"), (Work, "works"), (Video, "videos")):
        for row in db.query(model).all():
            title = row.title or ""
            if "#" not in title and "＃" not in title:
                continue
            cleaned = strip_hashtags(title)
            if cleaned and cleaned != title:
                row.title = cleaned
                changed[key] += 1
    db.commit()
    return changed


def maybe_clean_hashtag_titles_on_startup() -> None:
    """启动时后台跑一次历史标题清洗；已跑过（Kv 标记）则跳过。"""
    probe = SessionLocal()
    try:
        if probe.get(Kv, DONE_KEY) is not None:
            return
    except Exception:  # noqa: BLE001 读标记失败不阻断启动
        probe.rollback()
    finally:
        probe.close()

    def _run() -> None:
        db = SessionLocal()
        try:
            res = clean_hashtag_titles(db)
            db.add(Kv(key=DONE_KEY, value="1"))
            db.commit()
            log.info("R-226 历史标题去话题完成：%s", res)
        except Exception:  # noqa: BLE001 清洗失败保留标记缺失，下次启动可重跑
            db.rollback()
            log.exception("R-226 历史标题去话题失败（下次启动可重跑）")
        finally:
            db.close()

    threading.Thread(target=_run, name="title-hashtag-cleanup", daemon=True).start()
