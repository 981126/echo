"""发布后表现回填（R-189）：把已发布草稿的表现按日刷新到 drafts.performance。

草稿绑定素材（video_id）后，素材的云端作品互动数据可归因到「这篇稿子的表现」。
每日定时刷新一次，前端列表直接读到，无需逐条请求。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.draft import Draft


def performance_for_video(db: Session, video_id: int) -> dict | None:
    """聚合某素材各平台最新互动；无数据返回 None。"""
    from ..models.video import Video
    from .metrics import _platform_breakdown

    video = db.get(Video, video_id)
    if video is None:
        return None
    rows = _platform_breakdown(db, video)
    totals = {"plays": 0, "likes": 0, "favorites": 0, "comments": 0}
    has = False
    for r in rows:
        for k in totals:
            if r.get(k) is not None:
                has = True
                totals[k] += int(r.get(k) or 0)
    if not has:
        return None
    return {
        "video_id": video_id,
        "video_title": video.title or "",
        "platforms": rows,
        "totals": totals,
        "refreshed_at": _app_now().isoformat(),
    }


def refresh_published_performance(db: Session, creator_id: int | None = None) -> int:
    """刷新所有「已发布且绑定素材」草稿的表现，返回更新条数。"""
    import json

    q = db.query(Draft).filter(Draft.status.in_(["used", "done"]), Draft.video_id.isnot(None))
    if creator_id:
        q = q.filter(Draft.creator_id == creator_id)
    updated = 0
    for d in q.all():
        perf = performance_for_video(db, int(d.video_id or 0))
        if perf is None:
            continue
        d.performance = json.dumps(perf, ensure_ascii=False)
        updated += 1
    if updated:
        db.commit()
    return updated
