"""R-244 数据看板接口契约。"""

from __future__ import annotations

from pydantic import BaseModel


class RefreshIn(BaseModel):
    """作品「更新数据」：force=True 跳过 6 小时缓存检查。"""

    force: bool = False


class RetentionBackfillIn(BaseModel):
    """R-265 留存曲线补齐：scope=missing（全部待补）/ recent（发布 7 天内）。"""

    scope: str = "missing"
    limit: int = 300
