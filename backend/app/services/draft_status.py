"""草稿 AI 长任务状态（R-173）。

讨论 / 洗稿 / 回炉 / AI 生成草稿 共用一个状态键，供**草稿卡片**与**讨论 tab**显示
「谁在思考、第几轮」，也让"从素材库发起的洗稿"在脚本工作台可见（R-173 前只有抽屉
里自己点的讨论才知道进度）。

存放位置：`app_kv`（不新增表、不新增字段）
    key   = ``draft_ai:{draft_id}``
    value = JSON ``{"state","kind","note","actor","phase","round","rounds","at"}``

- ``state``：``running``（在跑）/ ``failed``（失败或中断，卡片显示「上次讨论中断」）；
  跑完由 :func:`clear` 删除（前端据此判定"讨论结束"）。
- 读取兼容 R-173 之前的旧键 ``debate:{draft_id}``（纯文案），启动自愈时清理旧键。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..models.kv import Kv

KEY_PREFIX = "draft_ai:"
LEGACY_PREFIX = "debate:"

# 前端展示用（卡片/状态条的中文类型名）
KIND_LABELS = {
    "debate": "双模型讨论",
    "discuss": "双模型讨论",
    "rewrite": "洗稿讨论",
    "rework": "回炉重写",
    "generate": "AI 生成",
    "feedback": "学习分析",  # R-211：完成/不采用触发的反馈学习
}

DEFAULT_NOTE = "AI 处理中…"


def key_of(draft_id: int | None) -> str:
    return f"{KEY_PREFIX}{int(draft_id or 0)}"


def _now_iso() -> str:
    from ..core.timeutil import now

    return now().isoformat(timespec="seconds")


def set_running(
    db: Session,
    draft_id: int | None,
    note: str,
    *,
    kind: str = "debate",
    actor: str = "",
    phase: str = "",
    round_no: int | None = None,
    rounds: int | None = None,
) -> None:
    """记录「正在做什么」。同一草稿重复调用即覆盖（新任务接管旧状态）。"""
    _write(
        db,
        draft_id,
        {
            "state": "running",
            "kind": kind,
            "note": note or DEFAULT_NOTE,
            "actor": actor,
            "phase": phase,
            "round": round_no,
            "rounds": rounds,
            "at": _now_iso(),
        },
    )


def set_failed(
    db: Session,
    draft_id: int | None,
    note: str,
    *,
    kind: str = "debate",
    actor: str = "",
    phase: str = "",
) -> None:
    """记录失败/中断：保留标记（卡片显示「上次讨论中断（可重新讨论）」），不再转圈。"""
    _write(
        db,
        draft_id,
        {
            "state": "failed",
            "kind": kind,
            "note": note or "讨论中断",
            "actor": actor,
            "phase": phase,
            "round": None,
            "rounds": None,
            "at": _now_iso(),
        },
    )


def clear(db: Session, draft_id: int | None) -> None:
    """任务正常跑完：删除状态（前端据此判定结束）。"""
    if not draft_id:
        return
    row = db.get(Kv, key_of(draft_id))
    if row is not None:
        db.delete(row)
        db.commit()


def _write(db: Session, draft_id: int | None, payload: dict[str, Any]) -> None:
    if not draft_id:
        return
    key = key_of(draft_id)
    value = json.dumps(payload, ensure_ascii=False)
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value
    # 写新键时顺手清掉 R-173 之前的旧键，避免它被后续读取「兜底」出来
    legacy = db.get(Kv, f"{LEGACY_PREFIX}{int(draft_id)}")
    if legacy is not None:
        db.delete(legacy)
    db.commit()


def normalize(raw: Any) -> dict[str, Any] | None:
    """把 Kv 原始值归一成状态字典；兼容 R-173 之前的「纯文案」值。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    data: Any = None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    if not isinstance(data, dict):
        data = {"state": "running", "kind": "debate", "note": text}
    state = str(data.get("state") or "running").strip() or "running"
    return {
        "state": state,
        "kind": str(data.get("kind") or "debate"),
        "note": str(data.get("note") or ""),
        "actor": str(data.get("actor") or ""),
        "phase": str(data.get("phase") or ""),
        "round": data.get("round"),
        "rounds": data.get("rounds"),
        "at": str(data.get("at") or ""),
        "running": state == "running",
    }


def read(db: Session, draft_id: int | None) -> dict[str, Any] | None:
    """单个草稿的状态；没有则 None。"""
    if not draft_id:
        return None
    row = db.get(Kv, key_of(draft_id))
    if row is None:
        row = db.get(Kv, f"{LEGACY_PREFIX}{int(draft_id)}")
    return normalize(row.value if row is not None else None)


def read_many(db: Session, draft_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """批量读取（列表页一次查询，避免 N+1）；新键优先于旧键。"""
    ids = [int(i) for i in draft_ids if i]
    if not ids:
        return {}
    keys = [f"{KEY_PREFIX}{i}" for i in ids] + [f"{LEGACY_PREFIX}{i}" for i in ids]
    rows = db.query(Kv).filter(Kv.key.in_(keys)).all()
    current: dict[int, dict[str, Any]] = {}
    legacy: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.key.startswith(KEY_PREFIX):
            target, raw = current, row.key[len(KEY_PREFIX) :]
        else:
            target, raw = legacy, row.key[len(LEGACY_PREFIX) :]
        try:
            did = int(raw)
        except ValueError:
            continue
        state = normalize(row.value)
        if state is not None:
            target[did] = state
    legacy.update(current)
    return {i: legacy[i] for i in ids if i in legacy}


def reset_stale_on_startup(db: Session) -> int:
    """服务重启自愈（R-173）：残留 ``running`` 改判「讨论中断」，并清理 R-173 之前的旧键。

    否则洗稿/讨论中途重启后，草稿卡片会永久转圈（原先只有 `draft_discuss` 路径清了状态）。
    """
    n = 0
    for row in db.query(Kv).filter(Kv.key.like(f"{KEY_PREFIX}%")).all():
        state = normalize(row.value)
        if state is not None and state["state"] == "running":
            state["state"] = "failed"
            state["note"] = "服务重启，任务中断"
            state["round"] = None
            state["rounds"] = None
            row.value = json.dumps(state, ensure_ascii=False)
            n += 1
    for row in db.query(Kv).filter(Kv.key.like(f"{LEGACY_PREFIX}%")).all():
        db.delete(row)
    db.commit()
    return n


__all__ = [
    "KIND_LABELS",
    "clear",
    "key_of",
    "normalize",
    "read",
    "read_many",
    "reset_stale_on_startup",
    "set_failed",
    "set_running",
]
