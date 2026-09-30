"""各功能 LLM 预算配置（R-143）。

**为什么需要**：R-142 把「评审总是降级」的根因定位到「推理预算被拍成了 4000」，
并用实测最坏值 + 校准护栏把值固定下来。但每次都要改代码才能调预算并不合理，
所以把**各功能预算**做成「AI 设置」里的可配置项（存 `app_kv`，保存即生效）。

**关键语义**
- `max_tokens` 是**上限**不是消费额：只按实际生成量计费，给足几乎不增成本（见 R-142 评估）。
- 生效值 = `max(用户设置, 厂家下限)`：厂家下限是防「思考吃光正文」的护栏（有校准护栏测试保护），
  用户把值调得更小时会被抬到下限，且界面显示的是**真实生效值**，不制造错觉。
- 上限由 `llm_router.MAX_TOKENS_CEILING` 兜住，避免手滑写成天文数字。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..core.log import get_logger
from ..models.kv import Kv
from . import model_settings

log = get_logger("budget_settings")

KV_KEY = "ai_budget_overrides"

# 单值下限/上限（越界直接拒绝，避免写进 0 / 天文数字）
HARD_MIN = 256


class BudgetConfigError(ValueError):
    """预算配置非法：API 层转 400，带可读原因。"""


# 可配置项（唯一事实源）。只暴露「长输出 / 长思考」类调用：
# 短 JSON 类（广告判定 300、语义复核 500…）故意很小，暴露只会被改坏。
SLOTS: dict[str, dict] = {
    "debate_initial": {
        "label": "脚本初稿",
        "default": 12000,
        "desc": "生成方起草初稿（标题/封面字/脚本/平台外壳）",
    },
    "debate_critique": {
        "label": "脚本评审",
        "default": 14000,
        "desc": "评审方挑刺（R-142 实测最坏思考 8023 tokens，这里留了余量）",
    },
    "debate_revise": {
        "label": "脚本修订/红线收口",
        "default": 16000,
        "desc": "按评审意见重写整篇、以及命中红线时的收口修订（口癖/高频词覆盖率仅诊断，不触发重写）",
    },
    "rewrite": {
        "label": "对标洗稿",
        "default": 12000,
        "desc": "按人设改写对标素材（整篇稿）",
    },
    "benchmark_analyze": {
        "label": "对标可讲分析",
        "default": 4000,
        "desc": "判断对标选题作者能不能讲（输出较短）",
    },
    "persona_merge": {
        "label": "人设归纳合并",
        "default": 8000,
        "desc": "把逐篇提炼结果归纳成一份人设档案（长上下文）",
    },
    "correct": {
        "label": "转写校对",
        "default": 12000,
        "desc": "输出整篇修正后的转写稿（长输出）",
    },
    "prompt_optimize": {
        "label": "提示词优化",
        "default": 8000,
        "desc": "产出候选提示词（含变更说明）",
    },
    "chat": {
        "label": "AI 对话",
        "default": 8000,
        "desc": "AI 对话单轮回答（含工具调用）",
    },
}


def ceiling() -> int:
    from .llm_router import MAX_TOKENS_CEILING

    return int(MAX_TOKENS_CEILING)


def floor() -> int:
    """厂家下限（取各厂家下限的最小值）：任何厂家都不会低于它，所以它是「保证不被截断」的底线。"""
    floors = [int(meta.get("min_max_tokens") or 0) for meta in model_settings.VENDORS.values()]
    return min(floors) if floors else HARD_MIN


def _default(key: str) -> int:
    slot = SLOTS.get(key)
    if slot is None:
        raise BudgetConfigError(f"未知的预算项：{key}")
    return int(slot["default"])


# ---------- 读写 ----------


def _kv_get(db: Session) -> dict:
    row = db.get(Kv, KV_KEY)
    if row is None or not (row.value or "").strip():
        return {}
    try:
        data = json.loads(row.value)
    except json.JSONDecodeError:
        log.warning("预算覆盖配置不是合法 JSON，已按默认值处理")
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in data.items():
        if key in SLOTS:
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                continue
    return out


def _kv_set(db: Session, overrides: dict) -> None:
    row = db.get(Kv, KV_KEY)
    value = json.dumps(overrides, ensure_ascii=False)
    if row is None:
        db.add(Kv(key=KV_KEY, value=value))
    else:
        row.value = value
    db.commit()


def _session(db: Session | None):
    """没有会话时自己开一个短连接（线程池/无 db 的调用点用）。"""
    if db is not None:
        return db, False
    from ..db import SessionLocal

    return SessionLocal(), True


def budget_for(db: Session | None, key: str) -> int:
    """生效预算 = `max(用户设置 / 代码默认, 厂家下限)`。"""
    own_db, should_close = _session(db)
    try:
        requested = _kv_get(own_db).get(key, _default(key))
    finally:
        if should_close:
            own_db.close()
    return max(int(requested), floor())


def budget_map(db: Session | None = None) -> dict[str, dict]:
    """给接口/前端用的完整视图（含生效值与说明）。"""
    own_db, should_close = _session(db)
    try:
        overrides = _kv_get(own_db)
    finally:
        if should_close:
            own_db.close()
    lo, hi = floor(), ceiling()
    out: dict[str, dict] = {}
    for key, slot in SLOTS.items():
        requested = int(overrides.get(key, slot["default"]))
        out[key] = {
            "label": slot["label"],
            "desc": slot["desc"],
            "default": int(slot["default"]),
            "requested": requested,
            "value": max(requested, lo),
            "floor": lo,
            "ceiling": hi,
            "custom": key in overrides,
        }
    return out


def save_budgets(db: Session, payload: dict) -> dict[str, dict]:
    """保存预算覆盖；非法输入抛 BudgetConfigError（API 转 400）。"""
    if not isinstance(payload, dict):
        raise BudgetConfigError("budgets 必须是对象：{预算项: 整数}")
    hi = ceiling()
    overrides = _kv_get(db)
    for key, raw in payload.items():
        if key not in SLOTS:
            raise BudgetConfigError(f"未知的预算项：{key}；可选：{'、'.join(SLOTS)}")
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise BudgetConfigError(f"{SLOTS[key]['label']} 的预算必须是整数，收到：{raw!r}") from exc
        if value < HARD_MIN or value > hi:
            raise BudgetConfigError(
                f"{SLOTS[key]['label']} 的预算需在 {HARD_MIN}～{hi} 之间，收到 {value}"
            )
        overrides[key] = value
    _kv_set(db, overrides)
    return budget_map(db)


def reset_budgets(db: Session) -> dict[str, dict]:
    """清空全部覆盖，回到代码默认。"""
    _kv_set(db, {})
    return budget_map(db)


__all__ = [
    "HARD_MIN",
    "SLOTS",
    "BudgetConfigError",
    "budget_for",
    "budget_map",
    "ceiling",
    "floor",
    "reset_budgets",
    "save_budgets",
]
