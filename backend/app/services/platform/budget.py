"""平台额度/预算助手（R-061-C 剩余）：自 platform_sync 拆出，行为不变。"""

from __future__ import annotations

import threading

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.pipeline import today_key
from ...models.kv import Kv

BUDGET_KEY = "tikhub_budget_limit"

# R-163：并行消费者会并发读改写同一 Kv 计数，进程内加锁串行化，避免「读旧值→写旧值+1」导致超发。
# R-241：计数改为单条原子 SQL（INSERT ... ON CONFLICT DO UPDATE）后，锁仍保留用于「预检 + 计费」的
# 组合原子性（同一进程内不会出现两个线程都通过预检再各加一次的情况），事务数从 3~4 降到 1。
_BUDGET_LOCK = threading.RLock()


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
    """计 count 次请求；超预算抛 BudgetExceeded（文案/语义与 R-163 一致）。

    R-241：由「多次 SELECT + ORM UPDATE + commit」改为**单条原子 SQL**：
        INSERT INTO app_kv(key, value) VALUES (:k, CAST(:n AS TEXT))
        ON CONFLICT (key) DO UPDATE
        SET value = CAST(CAST(app_kv.value AS BIGINT) + :n AS TEXT)
        RETURNING value
    行不存在时直接写入 n（等价 0+n），行存在时在数据库内完成加法 → 并发不丢计数；
    `RETURNING` 拿回加后值做**超卖兜底**（预检可能读到同 Session 旧值），超过上限则回滚
    本次增量并抛 BudgetExceeded → 硬保证「预算不超发」。每 count 1 事务。
    """
    count = max(1, int(count))
    with _BUDGET_LOCK:
        ensure_budget(db, count)
        budget = get_budget(db)  # 命中 Session 缓存：limit 正确（used 仅用于异常文案）
        limit = max(0, int(budget["limit"]))
        key = f"tikhub_budget_used:{today_key()}"
        new_used = int(
            db.execute(
                text(
                    "INSERT INTO app_kv (key, value) VALUES (:k, CAST(:n AS TEXT)) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = CAST(CAST(app_kv.value AS BIGINT) + :n AS TEXT) "
                    "RETURNING value"
                ),
                {"k": key, "n": count},
            ).scalar_one()
        )
        if new_used > limit:
            # 预检读到旧值时仍可能越过上限：原子加后回滚本次增量，保持「不超发」硬约束。
            db.rollback()
            raise BudgetExceeded(
                f"今日 TikHub 请求预算已用完（{new_used - count}/{limit}），未发起新请求"
            )
        db.commit()


def ensure_budget(db: Session, count: int = 1) -> None:
    """预算预检（R-135）：不足直接抛，避免"先发请求、后计费"让超预算那次请求已经花出去。"""
    with _BUDGET_LOCK:
        budget = get_budget(db)
        if budget["remaining"] < count:
            raise BudgetExceeded(
                f"今日 TikHub 请求预算已用完（{budget['used']}/{budget['limit']}），未发起新请求"
            )
