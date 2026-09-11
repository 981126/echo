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
    ensure_budget(db, count)
    budget = get_budget(db)
    row = db.get(Kv, f"tikhub_budget_used:{budget['date']}")
    if row is None:
        db.add(Kv(key=f"tikhub_budget_used:{budget['date']}", value=str(budget["used"] + count)))
    else:
        row.value = str(budget["used"] + count)
    db.commit()


def ensure_budget(db: Session, count: int = 1) -> None:
    """预算预检（R-135）：不足直接抛，避免"先发请求、后计费"让超预算那次请求已经花出去。"""
    budget = get_budget(db)
    if budget["remaining"] < count:
        raise BudgetExceeded(
            f"今日 TikHub 请求预算已用完（{budget['used']}/{budget['limit']}），未发起新请求"
        )
