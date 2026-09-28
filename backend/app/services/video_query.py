"""本地素材可见性口径（R-107 / R-179）。

`/api/videos`（素材列表）与 `/api/library`（素材库统一分页）必须完全同口径，
否则两处规则会漂移（R-179 把合并/筛选搬到服务端时特意抽出来）：
- `creator_id` 为 0 时取当前主博主；
- 排除绑定到**已禁用账号**作品的本地素材（R-107）。
"""

from __future__ import annotations

from sqlalchemy.orm import Query, Session

from ..models.platform import CreatorAccount, PlatformPost
from ..models.video import Video
from .creator_service import current_creator_id


def visible_videos_query(db: Session, creator_id: int = 0) -> Query:
    """按可见性口径返回 Video 查询（未排序、未分页）。"""
    q = db.query(Video)
    cid = creator_id or current_creator_id(db)
    if not cid:
        return q
    q = q.filter(Video.creator_id == cid)
    off_acc_ids = [
        r[0]
        for r in db.query(CreatorAccount.id)
        .filter(CreatorAccount.creator_id == cid, CreatorAccount.enabled.is_(False))
        .all()
    ]
    if off_acc_ids:
        off_rows = (
            db.query(PlatformPost.local_video_id, PlatformPost.platform, PlatformPost.platform_post_id)
            .filter(PlatformPost.account_id.in_(off_acc_ids))
            .all()
        )
        off_vid_ids = {r.local_video_id for r in off_rows if r.local_video_id}
        off_keys = {f"{r.platform}:{r.platform_post_id}" for r in off_rows if r.platform_post_id}
        if off_vid_ids:
            q = q.filter(~Video.id.in_(off_vid_ids))
        for k in off_keys:
            q = q.filter(Video.platform_post_id != k)
    return q
