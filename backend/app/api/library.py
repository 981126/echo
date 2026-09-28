"""素材库统一列表接口（R-179）。

一个请求就是一页卡片：本地素材 + 云端作品合并去重、按日期倒序、游标分页；
筛选/搜索/计数一并下推（前端不再全量拉取 + 内存过滤）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import library_service
from ..services.library_service import CardFilters

router = APIRouter()


@router.get("", response_model=dict)
def library_cards(
    creator_id: int = 0,
    cursor: str = "",
    limit: int = 20,
    platforms: list[str] = Query(default=[]),
    status: str = "",
    video: str = "",
    ad: str = "",
    kw: str = "",
    tags: list[str] = Query(default=[]),
    likes_min: int | None = None,
    likes_max: int | None = None,
    db: Session = Depends(get_db),
):
    """素材库卡片页（每批默认 20 条）。

    返回 `{total, filtered_total, facets:{tags}, items, next_cursor, has_more}`：
    - `total` 是**未筛选**的卡片总数，`filtered_total` 是当前筛选命中的总数（页头「共 N · 筛选后 M」）；
    - `next_cursor` 原样回传即可取下一批；后台同步插入新条目也不会重复/漏条（游标按 `(date,kind,id)` 定位）；
    - `facets.tags` 是标签多选的候选（来自全部卡片，不受当前筛选影响）。
    """
    return library_service.page(
        db,
        creator_id=creator_id,
        filters=CardFilters(
            platforms=[p for p in platforms if p],
            status=status,
            video=video,
            ad=ad,
            kw=kw,
            tags=[t for t in tags if t],
            likes_min=likes_min,
            likes_max=likes_max,
        ),
        cursor=library_service.decode_cursor(cursor),
        limit=limit,
    )
