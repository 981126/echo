"""模型槽位配置（R-138）：模型1/模型2（厂家 + 模型 + API Key）、生成方/评审方、ASR 服务商与模型。

- 配置存 `app_kv` → **保存即生效**（无需重启）。
- **API Key 明文存本地 DB**（作者 2026-09-11 明确选择）；界面需提示风险并限制数据库访问权限。
- 厂家目录写在代码里：以后接入新供应商只需在 `VENDORS` 加一条，UI 自动出现。
"""

from __future__ import annotations

from collections.abc import Iterable

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
        # V4.1 Flash 也是**推理模型**：max_tokens 同时含思考与正文，给小了会「思考吃光预算、正文为空」。
        # R-143 起「每个功能要多少」由 budget_settings.SLOTS 按任务标定（可配置），
        # 这里的下限只是**安全网**：兜住「有人随手写 300」这类情况，不再用它替代按任务标定。
        "min_max_tokens": 4000,
        "key_env": "deepseek_api_key",
        "base_env": "deepseek_base_url",
        "key_hint": "platform.deepseek.com 的 API Key（sk-…）",
    },
    "kimi": {
        "label": "Kimi（月之暗面）",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k2.6"],
        "default_model": "kimi-k2.6",
        # 推理模型只接受 temperature=1；给小 max_tokens 会把预算耗在思考上导致正文为空。
        # 实测：长上下文下 Kimi 修订任务的思考达 6971 字（≈4600+ tokens）且正文为空；
        # 预算 12000 时单次调用实测要 180.3s（所以 read 超时与墙钟同值，见 llm.py）。
        # 下限同 DeepSeek：只是安全网，按任务标定见 budget_settings.SLOTS。
        "supports_temperature": False,
        "min_max_tokens": 4000,
        "key_env": "kimi_api_key",
        "base_env": "kimi_base_url",
        "key_hint": "platform.moonshot.cn 的 API Key（sk-…）",
    },
}

ASR_MODES: dict[str, str] = {
    "aliyun": "阿里云 FileTrans",
    "siliconflow": "硅基流动",
    "tencent": "腾讯云录音文件识别",
    "mock": "模拟（不调用真实 ASR）",
}
ASR_SILICONFLOW_MODELS = ["Qwen/Qwen3-ASR-1.7B", "FunAudioLLM/SenseVoiceSmall"]
# 腾讯云录音文件识别引擎（R-200）：大模型2.0 / 大模型1.0 / 通用
ASR_TENCENT_MODELS = ["16k_zh_en_2.0", "16k_zh_en", "16k_zh"]
ASR_TENCENT_DEFAULT = "16k_zh_en_2.0"

SLOT_KEYS = {
    "model1": ("model1_vendor", "model1_model", "model1_key"),
    "model2": ("model2_vendor", "model2_model", "model2_key"),
}
ROLES = ("model1", "model2")
# R-240 S4：一次 `key IN (...)` 读全部模型配置键（原来每次 AI 调用 20~21 条 point query）。
_CONFIG_KEYS: tuple[str, ...] = tuple(
    key for slot_keys in SLOT_KEYS.values() for key in slot_keys
) + ("gen_role", "referee_role", "generation_model", "asr_mode", "asr_model")


class ModelConfigError(ValueError):
    """配置非法：API 层转 400，带可读原因。"""


# ---------- KV 读写 ----------


def _kv_get(db: Session, key: str) -> str:
    row = db.get(Kv, key)
    return (row.value or "").strip() if row is not None else ""


def _kv_get_many(db: Session, keys: Iterable[str]) -> dict[str, str]:
    """一次 `key IN (...)` 批量读配置（R-240 S4）。

    返回已 strip 的值；缺失键**不在**结果里（调用方用 `.get(key, "")`）。
    只做批读、不做缓存，因此「保存设置立即生效」语义不变。
    """
    rows = db.query(Kv.key, Kv.value).filter(Kv.key.in_(list(keys))).all()
    return {str(key): (value or "").strip() for key, value in rows}


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


def default_asr_model(mode: str) -> str:
    """按服务商给出默认 ASR 模型（避免切服务商后沿用上一家的模型名）。"""
    settings = get_settings()
    if mode == "siliconflow":
        return settings.siliconflow_asr_model
    if mode == "tencent":
        return (getattr(settings, "tencent_asr_engine_model", "") or ASR_TENCENT_DEFAULT).strip()
    return ""


def _coerce_asr_model(mode: str, model: str) -> str:
    """修正模型名：腾讯引擎必须命中白名单，缺失则回退该服务商默认。"""
    model = (model or "").strip()
    if mode == "tencent" and model not in ASR_TENCENT_MODELS:
        return ASR_TENCENT_DEFAULT
    return model or default_asr_model(mode)


def get_model_config(db: Session, config: dict | None = None) -> dict:
    """读取当前配置（含旧 generation_model 的无感迁移）。

    `config` 传入已解析结果时直接复用（R-240 S4：同一请求只解析一次），
    所以同请求的 `resolve_*`/`asr_config` 不会再各查一遍 KV；不跨请求缓存。
    """
    if config is not None:
        return config
    kv = _kv_get_many(db, _CONFIG_KEYS)
    config = {}
    migrated = False
    for slot, (kv_vendor, kv_model, kv_key) in SLOT_KEYS.items():
        vendor = kv.get(kv_vendor, "")
        model = kv.get(kv_model, "")
        if not vendor:
            dv, dm = _default_slot(slot)
            vendor, model, migrated = dv, dm, True
        config[slot] = {
            "vendor": vendor,
            "model": model or VENDORS.get(vendor, {}).get("default_model", ""),
            "key": kv.get(kv_key, ""),
        }

    gen_role = kv.get("gen_role", "")
    referee_role = kv.get("referee_role", "")
    if not gen_role:
        # 旧值映射：原先 generation_model=deepseek 表示生成方用 DeepSeek，=kimi 表示生成方用 Kimi
        legacy = (kv.get("generation_model", "") or get_settings().generation_model or "kimi").lower()
        gen_role = "model1" if legacy == "deepseek" else "model2"
        migrated = True
    if not referee_role:
        referee_role = "model2" if gen_role == "model1" else "model1"
        migrated = True

    asr_mode = kv.get("asr_mode", "") or get_settings().asr_mode
    asr_model = _coerce_asr_model(asr_mode, kv.get("asr_model", ""))

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
    if asr_mode == "tencent":
        asr_model = asr_model or ASR_TENCENT_DEFAULT
        if asr_model not in ASR_TENCENT_MODELS:
            raise ModelConfigError(
                f"腾讯云 ASR 引擎不受支持：{asr_model}；可选：{'/'.join(ASR_TENCENT_MODELS)}"
            )
        if not (settings.tencent_asr_secret_id and settings.tencent_asr_secret_key):
            raise ModelConfigError(
                "选择腾讯云 ASR 前请先在 .env 配置 ECHO_TENCENT_ASR_SECRET_ID / ECHO_TENCENT_ASR_SECRET_KEY"
            )

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


def resolve_slots(db: Session, config: dict | None = None) -> dict[str, dict]:
    """解析出两个槽位的完整信息（base_url / api_key / 参数约束）。Key 优先 DB，回退 .env。

    `config` 可传 `get_model_config` 的已解析结果复用（R-240 S4：避免同请求重复批读）。
    """
    config = get_model_config(db, config)
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


def generation_roles(db: Session, config: dict | None = None) -> tuple[str, str]:
    """(生成方槽位, 评审方槽位)；`config` 可复用已解析配置（R-240 S4）。"""
    config = get_model_config(db, config)
    return config["gen_role"], config["referee_role"]


# ---------- R-232：功能级模型路由（AI 设置里每个非生成功能选主用槽位） ----------

# 组 = 界面展示粒度：人设 4 引擎合一、提示词优化+金样本评测合一、灵感与其他合一。
# feature 名字与 llm_router.primary_llm(feature) / persona.llm_for(feature) 的调用一致。
FEATURE_GROUPS: dict[str, dict] = {
    "chat": {"label": "AI 对话", "features": ("chat",)},
    "persona": {
        "label": "人设引擎",
        "features": ("persona_init", "persona_merge", "persona_updates", "persona_compare"),
    },
    "video_tags": {"label": "视频预打标", "features": ("video_tags",)},
    "correct": {"label": "转写校对", "features": ("correct",)},
    "diff": {"label": "差异分析", "features": ("diff",)},
    "prompt_opt": {"label": "提示词优化与评测", "features": ("prompt_optimize", "prompt_eval")},
    "benchmark": {"label": "对标分析", "features": ("benchmark",)},
    "video_review": {"label": "视频复盘", "features": ("video_review",)},
    "feedback": {"label": "反馈学习", "features": ("feedback_analysis",)},
    "draft_meta": {"label": "标题封面标签", "features": ("draft_meta",)},
    "misc": {"label": "灵感与其他", "features": ("ideas", "misc")},
}
_FEATURE_GROUP: dict[str, str] = {f: g for g, meta in FEATURE_GROUPS.items() for f in meta["features"]}
# 默认值：全 model1（= R-232 前的现状）；提示词优化组默认跟随生成方（R-229 语义）。
FEATURE_ROUTE_DEFAULTS: dict[str, str] = {g: ("gen" if g == "prompt_opt" else "model1") for g in FEATURE_GROUPS}


def feature_route(db: Session | None, feature: str, config: dict | None = None) -> str:
    """功能主用槽位（app_kv `feature_route_<组>`；缺省按 FEATURE_ROUTE_DEFAULTS）。

    prompt_opt 组特殊值 `gen` = 跟随生成方（R-229；生成方对调后优化自动跟着换）。
    返回值恒为 model1/model2——`gen` 在解析时展开，调用方拿到的永远是具体槽位。
    `config` 可传已解析配置复用（R-240 S4：`gen` 展开不再重复批读模型配置）。
    """
    group = _FEATURE_GROUP.get(feature or "", "misc")
    raw = _kv_get(db, f"feature_route_{group}") if db is not None else ""
    if not raw:
        raw = FEATURE_ROUTE_DEFAULTS[group]
    if raw == "gen":
        if group == "prompt_opt":
            if config is not None:
                return config["gen_role"]
            if db is not None:
                gen_role, _critic = generation_roles(db)
                return gen_role
        return "model1"
    return raw if raw in ROLES else "model1"


def save_feature_routes(db: Session, routes: dict[str, str]) -> None:
    """保存功能路由；值限 model1/model2（prompt_opt 组额外允许 gen），非法抛 ModelConfigError。"""
    for group, val in routes.items():
        if group not in FEATURE_GROUPS:
            raise ModelConfigError(f"未知的功能路由：{group}")
        allowed = {"model1", "model2"} | ({"gen"} if group == "prompt_opt" else set())
        val = (val or "").strip()
        if val not in allowed:
            raise ModelConfigError(
                f"「{FEATURE_GROUPS[group]['label']}」的路由必须是 {' / '.join(sorted(allowed))}，收到：{val!r}"
            )
        _kv_set(db, f"feature_route_{group}", val)
    db.commit()


def asr_config(db: Session, config: dict | None = None) -> dict:
    """ASR 运行时配置（Kv 优先，回退 .env）→ 保证界面保存后立即生效。

    `config` 可复用已解析配置（R-240 S4：`ingest` 等调用方不必再批读一遍）。
    """
    config = get_model_config(db, config)
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
    "ASR_TENCENT_MODELS",
    "ASR_TENCENT_DEFAULT",
    "ROLES",
    "ModelConfigError",
    "get_model_config",
    "save_model_config",
    "resolve_slots",
    "generation_roles",
    "FEATURE_GROUPS",
    "FEATURE_ROUTE_DEFAULTS",
    "feature_route",
    "save_feature_routes",
    "asr_config",
    "default_asr_model",
    "topics_count",
    "save_topics_count",
]
