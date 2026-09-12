"""模型槽位配置（R-138）：模型1/模型2（厂家 + 模型 + API Key）、生成方/评审方、ASR 服务商与模型。

- 配置存 `app_kv` → **保存即生效**（无需重启）。
- **API Key 明文存本地 DB**（作者 2026-09-11 明确选择，接受"备份会带明文 Key"的代价）；
  界面需提示风险，且仓库外的 `echo_resource/backups` 要做好权限控制。
- 厂家目录写在代码里：以后接入新供应商只需在 `VENDORS` 加一条，UI 自动出现。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.kv import Kv

# ---------- 厂家目录（唯一事实源） ----------
VENDORS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "default_model": "deepseek-flash",
        "supports_temperature": True,
        "min_max_tokens": 400,
        "key_env": "deepseek_api_key",
        "base_env": "deepseek_base_url",
        "key_hint": "platform.deepseek.com 的 API Key（sk-…）",
    },
    "kimi": {
        "label": "Kimi（月之暗面）",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k2.6"],
        "default_model": "kimi-k2.6",
        # 推理模型只接受 temperature=1；给小 max_tokens 会把预算耗在思考上导致正文为空
        "supports_temperature": False,
        "min_max_tokens": 3000,
        "key_env": "kimi_api_key",
        "base_env": "kimi_base_url",
        "key_hint": "platform.moonshot.cn 的 API Key（sk-…）",
    },
}

ASR_MODES: dict[str, str] = {
    "aliyun": "阿里云 FileTrans",
    "siliconflow": "硅基流动",
    "mock": "模拟（不调用真实 ASR）",
}
ASR_SILICONFLOW_MODELS = ["Qwen/Qwen3-ASR-1.7B", "FunAudioLLM/SenseVoiceSmall"]

SLOT_KEYS = {
    "model1": ("model1_vendor", "model1_model", "model1_key"),
    "model2": ("model2_vendor", "model2_model", "model2_key"),
}
ROLES = ("model1", "model2")


class ModelConfigError(ValueError):
    """配置非法：API 层转 400，带可读原因。"""


# ---------- KV 读写 ----------


def _kv_get(db: Session, key: str) -> str:
    row = db.get(Kv, key)
    return (row.value or "").strip() if row is not None else ""


def _kv_set(db: Session, key: str, value: str) -> None:
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=value))
    else:
        row.value = value


def env_key_for(vendor: str) -> str:
    """该厂家在 .env 里的 Key（DB 未配置时的回退）。"""
    settings = get_settings()
    field = (VENDORS.get(vendor) or {}).get("key_env") or ""
    return str(getattr(settings, field, "") or "")


def env_base_url_for(vendor: str) -> str:
    settings = get_settings()
    field = (VENDORS.get(vendor) or {}).get("base_env") or ""
    return str(getattr(settings, field, "") or (VENDORS.get(vendor) or {}).get("base_url") or "")


def _default_slot(slot: str) -> tuple[str, str]:
    """默认槽位：模型1=DeepSeek（现状主力），模型2=Kimi（现状降级/评审）。"""
    return ("deepseek", "deepseek-flash") if slot == "model1" else ("kimi", "kimi-k2.6")


def get_model_config(db: Session) -> dict:
    """读取当前配置（含旧 generation_model 的无感迁移）。"""
    config: dict = {}
    migrated = False
    for slot, (kv_vendor, kv_model, kv_key) in SLOT_KEYS.items():
        vendor = _kv_get(db, kv_vendor)
        model = _kv_get(db, kv_model)
        if not vendor:
            dv, dm = _default_slot(slot)
            vendor, model, migrated = dv, dm, True
        config[slot] = {"vendor": vendor, "model": model or VENDORS.get(vendor, {}).get("default_model", ""), "key": _kv_get(db, kv_key)}

    gen_role = _kv_get(db, "gen_role")
    referee_role = _kv_get(db, "referee_role")
    if not gen_role:
        # 旧值映射：原先 generation_model=deepseek 表示生成方用 DeepSeek，=kimi 表示生成方用 Kimi
        legacy = (_kv_get(db, "generation_model") or get_settings().generation_model or "kimi").lower()
        gen_role = "model1" if legacy == "deepseek" else "model2"
        migrated = True
    if not referee_role:
        referee_role = "model2" if gen_role == "model1" else "model1"
        migrated = True

    asr_mode = _kv_get(db, "asr_mode") or get_settings().asr_mode
    asr_model = _kv_get(db, "asr_model") or get_settings().siliconflow_asr_model

    config.update(
        {
            "gen_role": gen_role if gen_role in ROLES else "model2",
            "referee_role": referee_role if referee_role in ROLES else "model1",
            "asr_mode": asr_mode,
            "asr_model": asr_model,
            "migrated_from_legacy": migrated,
        }
    )
    return config


def save_model_config(db: Session, payload: dict) -> dict:
    """保存并校验；非法配置抛 ModelConfigError（API 转 400）。"""
    for slot, (kv_vendor, kv_model, kv_key) in SLOT_KEYS.items():
        item = payload.get(slot) or {}
        vendor = str(item.get("vendor") or "").strip()
        if vendor not in VENDORS:
            raise ModelConfigError(f"{slot} 的厂家不受支持：{vendor or '（空）'}；可选：{'/'.join(VENDORS)}")
        model = str(item.get("model") or "").strip() or VENDORS[vendor]["default_model"]
        if len(model) > 120:
            raise ModelConfigError(f"{slot} 的模型名过长")
        key = str(item.get("key") or "").strip()
        if len(key) > 300:
            raise ModelConfigError(f"{slot} 的 API Key 过长")
        if not key and not env_key_for(vendor):
            raise ModelConfigError(f"{slot}（{VENDORS[vendor]['label']}）既没填 API Key，.env 里也没有对应 Key")

    gen_role = str(payload.get("gen_role") or "").strip()
    referee_role = str(payload.get("referee_role") or "").strip()
    if gen_role not in ROLES or referee_role not in ROLES:
        raise ModelConfigError("生成方/评审方只能选 模型1 或 模型2")

    asr_mode = str(payload.get("asr_mode") or "").strip()
    if asr_mode not in ASR_MODES:
        raise ModelConfigError(f"ASR 服务商不受支持：{asr_mode or '（空）'}；可选：{'/'.join(ASR_MODES)}")
    asr_model = str(payload.get("asr_model") or "").strip()
    settings = get_settings()
    if asr_mode == "siliconflow":
        if not asr_model:
            raise ModelConfigError("选择硅基流动时必须填写 ASR 模型（如 Qwen/Qwen3-ASR-1.7B）")
        if not settings.siliconflow_api_key:
            raise ModelConfigError("选择硅基流动前请先在 .env 配置 ECHO_SILICONFLOW_API_KEY")
    if asr_mode == "aliyun" and not (settings.aliyun_asr_access_key_id and settings.aliyun_asr_app_key):
        raise ModelConfigError("选择阿里云 ASR 前请先在 .env 配置 ECHO_ALIYUN_ASR_ACCESS_KEY_ID / ECHO_ALIYUN_ASR_APP_KEY")

    for slot, (kv_vendor, kv_model, kv_key) in SLOT_KEYS.items():
        item = payload[slot]
        _kv_set(db, kv_vendor, str(item["vendor"]).strip())
        _kv_set(db, kv_model, str(item.get("model") or VENDORS[item["vendor"]]["default_model"]).strip())
        _kv_set(db, kv_key, str(item.get("key") or "").strip())
    _kv_set(db, "gen_role", gen_role)
    _kv_set(db, "referee_role", referee_role)
    _kv_set(db, "asr_mode", asr_mode)
    _kv_set(db, "asr_model", asr_model)
    db.commit()
    return get_model_config(db)


# ---------- 解析（供 llm_router / transcription 实时使用） ----------


def resolve_slots(db: Session) -> dict[str, dict]:
    """解析出两个槽位的完整信息（base_url / api_key / 参数约束）。Key 优先 DB，回退 .env。"""
    config = get_model_config(db)
    out: dict[str, dict] = {}
    for slot in ROLES:
        item = config[slot]
        vendor = item["vendor"]
        meta = VENDORS[vendor]
        out[slot] = {
            "slot": slot,
            "vendor": vendor,
            "vendor_label": meta["label"],
            "model": item["model"] or meta["default_model"],
            "api_key": item["key"] or env_key_for(vendor),
            "base_url": env_base_url_for(vendor) or meta["base_url"],
            "supports_temperature": bool(meta["supports_temperature"]),
            "min_max_tokens": int(meta["min_max_tokens"]),
        }
    return out


def generation_roles(db: Session) -> tuple[str, str]:
    """(生成方槽位, 评审方槽位)。"""
    config = get_model_config(db)
    return config["gen_role"], config["referee_role"]


def asr_config(db: Session) -> dict:
    """ASR 运行时配置（Kv 优先，回退 .env）→ 保证界面保存后立即生效。"""
    config = get_model_config(db)
    return {"mode": config["asr_mode"], "model": config["asr_model"]}


def topics_count(db: Session, default: int = 2) -> int:
    """每日自动生成篇数（R-138 同 tab 可配）。

    优先级：界面保存的 `app_kv` > `.env` 的 `ECHO_PIPELINE_TOPICS_COUNT` > default。
    双模型讨论成本 = 篇数 × 轮次 × 2，建议 1–2 篇。
    """
    raw = _kv_get(db, "pipeline_topics_count")
    try:
        n = int(raw) if raw else int(getattr(get_settings(), "pipeline_topics_count", default) or default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, 10))


def save_topics_count(db: Session, value: int) -> int:
    n = max(1, min(int(value), 10))
    _kv_set(db, "pipeline_topics_count", str(n))
    db.commit()
    return n


__all__ = [
    "VENDORS",
    "ASR_MODES",
    "ASR_SILICONFLOW_MODELS",
    "ROLES",
    "ModelConfigError",
    "get_model_config",
    "save_model_config",
    "resolve_slots",
    "generation_roles",
    "asr_config",
    "topics_count",
    "save_topics_count",
]
