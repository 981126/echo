"""平台额度/预算助手（R-061-C 剩余）：自 platform_sync 拆出，行为不变。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.pipeline import today_key
from ...models.kv import Kv

BUDGET_KEY = "tikhub_budget_limit"


class BudgetExceeded(RuntimeError):
    pass


def get_budget(db: Session) -> dict:
    limit = get_settings().tikhub_daily_budget
    row = db.get(Kv, BUDGET_KEY)
    if row and str(row.value).isdigit():
        limit = int(row.value)
    key = today_key()
    used_row = db.get(Kv, f"tikhub_budget_used:{key}")
    used = int(used_row.value) if used_row and str(used_row.value).isdigit() else 0
    return {"limit": limit, "used": used, "remaining": max(0, limit - used), "date": key}


def set_budget(db: Session, limit: int) -> dict:
    limit = max(1, min(limit, 10_000_000))
    row = db.get(Kv, BUDGET_KEY)
    if row is None:
        row = Kv(key=BUDGET_KEY, value=str(limit))
        db.add(row)
    else:
        row.value = str(limit)
    db.commit()
    return get_budget(db)


def _charge(db: Session, count: int = 1) -> None:
    """计一次请求；超预算抛 BudgetExceeded。"""
    budget = get_budget(db)
    if budget["used"] + count > budget["limit"]:
        raise BudgetExceeded(
            f"今日 TikHub 请求预算已用完（{budget['used']}/{budget['limit']}），已停止本轮同步"
        )
    row = db.get(Kv, f"tikhub_budget_used:{budget['date']}")
    if row is None:
        row = Kv(key=f"tikhub_budget_used:{budget['date']}", value=str(budget["used"] + count))
        db.add(row)
    else:
        row.value = str(budget["used"] + count)
    db.commit()
