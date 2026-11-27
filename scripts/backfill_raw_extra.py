#!/usr/bin/env python3
"""R-270：把抖音 `platform_posts.raw` 里已有、但没落库的统计字段补进 `extra`。

背景：抖音作品 raw 里本来就带 `download_count / recommend_count / forward_count /
admire_count / live_watch_count`，解析器只落了 5 个主指标。本脚本只读本地 raw、
不调用任何第三方接口（0 请求），把缺的键合并进该作品**最新一条** `platform_post_stats.extra`。

幂等：只补缺失键；重复执行不会重复写。
用法（仓库根目录）：
    PYTHONPATH=backend python3 scripts/backfill_raw_extra.py --dry-run
    PYTHONPATH=backend python3 scripts/backfill_raw_extra.py --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models.platform import PlatformPost, PlatformPostStat  # noqa: E402

RAW_KEYS = {
    "download_count": "downloads",
    "recommend_count": "recommends",
    "forward_count": "forwards",
    "admire_count": "admires",
    "live_watch_count": "live_watch",
}


def _numbers(raw: str) -> dict[str, int]:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    statistics = data.get("statistics") if isinstance(data, dict) else None
    if not isinstance(statistics, dict):
        return {}
    out: dict[str, int] = {}
    for source_key, target_key in RAW_KEYS.items():
        try:
            value = int(statistics.get(source_key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[target_key] = value
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="补抖音 raw 里的未解析统计字段到 platform_post_stats.extra")
    parser.add_argument("--dry-run", action="store_true", help="只统计待补条数，不写库")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条作品（0=全部）")
    args = parser.parse_args()

    db = SessionLocal()
    scanned = touched = 0
    try:
        query = db.query(PlatformPost).filter(PlatformPost.platform == "douyin", PlatformPost.raw.isnot(None))
        if args.limit > 0:
            query = query.limit(args.limit)
        for post in query.all():
            scanned += 1
            numbers = _numbers(post.raw)
            if not numbers:
                continue
            stat = (
                db.query(PlatformPostStat)
                .filter_by(post_id=post.id)
                .order_by(PlatformPostStat.stat_date.desc())
                .first()
            )
            if stat is None:
                continue
            try:
                extra = json.loads(stat.extra or "{}")
            except (TypeError, ValueError):
                extra = {}
            missing = {key: value for key, value in numbers.items() if key not in extra}
            if not missing:
                continue
            touched += 1
            if args.dry_run:
                continue
            extra.update(missing)
            stat.extra = json.dumps(extra, ensure_ascii=False)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()
    print(f"扫描 {scanned} 条，待补/已补 {touched} 条" + ("（dry-run 未写库）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
