"""R-244 数据看板接口契约。"""

from __future__ import annotations

from pydantic import BaseModel


class RefreshIn(BaseModel):
    """作品「更新数据」：force=True 跳过 6 小时缓存检查。"""

    force: bool = False
