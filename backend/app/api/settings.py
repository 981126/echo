"""AI 设置（R-023/R-108/R-138）：模型1/2 槽位、生成方/评审方、ASR、讨论轮次、每日篇数。

配置全部存 `app_kv`，保存即生效（无需重启）。旧 `/generation-model` 接口保留以兼容。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.log import get_logger
from ..db import get_db
from ..models.kv import Kv
from ..services import budget_settings, model_health, model_settings

router = APIRouter()
log = get_logger("settings")

MODES = ["deepseek", "kimi", "random", "alternate"]


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(deepseek|kimi|random|alternate)$")


class RoundsIn(BaseModel):
    rounds: int = Field(default=5, ge=1, le=10)


class SlotIn(BaseModel):
    vendor: str
    model: str = ""
    key: str = ""


class ModelsIn(BaseModel):
    model1: SlotIn
    model2: SlotIn
    gen_role: str
    referee_role: str
    asr_mode: str
    asr_model: str = ""
    debate_rounds: int | None = Field(default=None, ge=1, le=10)
    topics_count: int | None = Field(default=None, ge=1, le=10)
    # R-143：各功能推理预算（键见 budget_settings.SLOTS）；reset_budgets=true 一键回默认。
    # 故意用 object 而不是 int：让「非整数」也走 budget_settings 的校验，
    # 与「未知键 / 越界」统一返回 400 + 中文可读原因（而不是 FastAPI 的 422 英文结构）。
    budgets: dict[str, object] | None = None
    reset_budgets: bool = False


def _effective_key(config_slot: dict, vendor: str) -> tuple[bool, bool]:
    """返回 (是否已配置有效 Key, 是否来自 .env)。"""
    if config_slot.get("key"):
        return True, False
    return bool(model_settings.env_key_for(vendor)), True


def _models_payload(db: Session) -> dict:
    config = model_settings.get_model_config(db)
    slots: dict[str, dict] = {}
    for slot in ("model1", "model2"):
        item = dict(config[slot])
        vendor = item["vendor"]
        has_key, from_env = _effective_key(item, vendor)
        item["base_url"] = model_settings.env_base_url_for(vendor)
        item["key_present"] = has_key
        item["key_from_env"] = from_env
        item["vendor_label"] = model_settings.VENDORS[vendor]["label"]
        item["key_hint"] = model_settings.VENDORS[vendor]["key_hint"]
        slots[slot] = item

    return {
        **slots,
        "gen_role": config["gen_role"],
        "referee_role": config["referee_role"],
        "asr": {
            "mode": config["asr_mode"],
            "model": config["asr_model"],
            "options": model_settings.ASR_MODES,
            "siliconflow_models": model_settings.ASR_SILICONFLOW_MODELS,
            "tencent_models": model_settings.ASR_TENCENT_MODELS,
        },
        "debate_rounds": get_rounds(db)["rounds"],
        "topics_count": model_settings.topics_count(db),
        "vendors": {
            vid: {
                "label": meta["label"],
                "models": meta["models"],
                "default_model": meta["default_model"],
                "key_hint": meta["key_hint"],
                "has_env_key": bool(model_settings.env_key_for(vid)),
            }
            for vid, meta in model_settings.VENDORS.items()
        },
        "warnings": [
            "API Key 以明文保存在本地数据库（app_kv）；备份文件会包含明文 Key，请限制备份目录权限。",
            "修改后立即生效，无需重启。",
            *([f"双模型兼容性自检：{w}" for w in (model_health.last_result(db) or {}).get("warnings", [])]),
        ],
        "selfcheck": model_health.last_result(db),
        "budgets": budget_settings.budget_map(db),  # R-143：各功能推理预算
        "migrated_from_legacy": bool(config.get("migrated_from_legacy")),
    }


def _selfcheck_task(db: Session, payload: dict) -> dict:
    """后台任务：保存模型配置后跑一次双模型兼容性自检（R-139）。"""
    res = model_health.run_selfcheck(db, triggered_by=str(payload.get("triggered_by") or "save"))
    if res["ok"]:
        return {"message": "模型1/2 在样例功能上均兼容"}
    return {"message": "发现问题：" + "；".join(res["warnings"])[:200]}


@router.get("/models", response_model=dict)
def get_models(db: Session = Depends(get_db)):
    """AI 设置 → 模型设置：当前模型1/2、生成方/评审方、ASR、轮次、每日篇数。"""
    return _models_payload(db)


@router.put("/models", response_model=dict)
def put_models(payload: ModelsIn, db: Session = Depends(get_db)):
    """保存模型设置；非法配置返回 400 并给出可读原因。保存后立即生效。"""
    try:
        model_settings.save_model_config(db, payload.model_dump())
    except model_settings.ModelConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.debate_rounds is not None:
        set_rounds(RoundsIn(rounds=payload.debate_rounds), db)
    if payload.topics_count is not None:
        model_settings.save_topics_count(db, payload.topics_count)
    # R-143：推理预算（非法输入 400）
    try:
        if payload.reset_budgets:
            budget_settings.reset_budgets(db)
        elif payload.budgets:
            budget_settings.save_budgets(db, payload.budgets)
    except budget_settings.BudgetConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # R-139：保存后异步跑一次双模型兼容性自检（不阻塞界面；结果回到 GET /models 的 selfcheck）
    try:
        from ..tasks import start_task

        start_task("model_selfcheck", {"triggered_by": "save"}, _selfcheck_task)
    except Exception as exc:  # noqa: BLE001 入队失败不能影响保存本身
        log.warning("双模型兼容性自检入队失败：%s", exc)
    return _models_payload(db)


@router.get("/asr", response_model=dict)
def get_asr_config(db: Session = Depends(get_db)):
    """当前 ASR 服务商与模型（R-138 起读运行时配置，随设置页实时变化）。"""
    cfg = model_settings.asr_config(db)
    return {"mode": cfg["mode"], "model": cfg["model"]}


# ---------- 兼容旧接口（前端已改用 /models） ----------
@router.get("/generation-model", response_model=dict)
def get_mode(db: Session = Depends(get_db)):
    """旧接口：把「生成方」映射回 deepseek/kimi 以便展示。"""
    slots = model_settings.resolve_slots(db)
    gen_role, _ref = model_settings.generation_roles(db)
    gen_vendor = slots[gen_role]["vendor"]
    return {"mode": "deepseek" if gen_vendor == "deepseek" else "kimi", "modes": MODES, "detailed": True}


@router.put("/generation-model", response_model=dict)
def set_mode(payload: ModeIn, db: Session = Depends(get_db)):
    """旧接口：deepseek/kimi 映射为对应槽位当生成方；random/alternate 已下线。"""
    if payload.mode in ("random", "alternate"):
        raise HTTPException(
            status_code=400,
            detail="随机/轮流策略已下线；请在「AI 设置 → 模型设置」里直接选择生成方与评审方",
        )
    slots = model_settings.resolve_slots(db)
    target = next((slot for slot in ("model1", "model2") if slots[slot]["vendor"] == payload.mode), None)
    if target is None:
        raise HTTPException(status_code=400, detail=f"没有厂家为 {payload.mode} 的模型槽位，请先在「模型设置」里配置")
    row = db.get(Kv, "gen_role")
    if row is None:
        db.add(Kv(key="gen_role", value=target))
    else:
        row.value = target
    db.commit()
    return {"mode": payload.mode}


@router.get("/debate-rounds", response_model=dict)
def get_rounds(db: Session = Depends(get_db)):
    row = db.get(Kv, "debate_rounds")
    rounds = int(row.value) if row and str(row.value).isdigit() else int(get_settings().debate_rounds or 5)
    return {"rounds": max(1, min(rounds, 10)), "min": 1, "max": 10}


@router.put("/debate-rounds", response_model=dict)
def set_rounds(payload: RoundsIn, db: Session = Depends(get_db)):
    row = db.get(Kv, "debate_rounds")
    if row is None:
        db.add(Kv(key="debate_rounds", value=str(payload.rounds)))
    else:
        row.value = str(payload.rounds)
    db.commit()
    return {"rounds": payload.rounds}
