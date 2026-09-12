"""双模型兼容性自检（R-139）：保存模型配置后，用极简样例各跑一次模型1/模型2。

目的：保证「模型1、2 都深度学习过同一套系统数据」不是空话——
- 两个模型吃**同一套提示词与上下文组装**；
- 参数按厂家归一化（不支持 temperature 的不传、max_tokens 抬到厂家下限）；
- 用每个功能的**极简样例**验证输出契约，不兼容时在设置页告警「模型2 在 X 功能上不兼容」。

只做很小的调用（每个槽位 3 次），保存设置后异步跑，不阻塞界面。
结果写 `app_kv`（key: `model_selfcheck_result`），由 `GET /api/settings/models` 带回前端。
"""

from __future__ import annotations

import json
import time

from sqlalchemy.orm import Session

from ..core.log import get_logger
from ..models.kv import Kv
from . import llm_router, model_settings
from .prompt_service import get_prompt

log = get_logger("model_health")

SELFCHECK_KV = "model_selfcheck_result"

# 极简样例：每个探测项 = (标签, 调用方式, 系统提示词, user 消息, 契约字段)
PROBES: list[dict] = [
    {
        "key": "chat",
        "label": "文本对话",
        "mode": "chat",
        "system": "你是测试助手。只回复两个字：正常。",
        "user": "回复两个字。",
        "text": True,
    },
    {
        "key": "video_tags",
        "label": "视频预打标（JSON 契约）",
        "mode": "json",
        "system": None,  # 用该功能的真实提示词
        "prompt_key": "video_tags",
        "user": "大家好，今天聊聊面试里的自我介绍怎么做。",
        "require": ["main_topics"],
    },
    {
        "key": "json_basic",
        "label": "JSON 输出能力",
        "mode": "json",
        "system": '只输出 JSON：{"ok":true}，不要解释。',
        "user": "输出 JSON。",
        "require": ["ok"],
    },
]


def _probe_slot(slot: dict, probe: dict, db: Session) -> dict:
    client = llm_router.build_client(slot)
    # 参数归一化：探测也要按厂家下限给足 max_tokens，否则推理模型会被误判为「不兼容」
    budget = llm_router.normalize_max_tokens(slot, 800)
    system = probe.get("system") or get_prompt(probe.get("prompt_key") or "", db)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": probe["user"]}]
    started = time.time()
    try:
        if probe["mode"] == "json":
            data = client.chat_json(messages, temperature=0.0, max_tokens=budget)
            missing = [k for k in probe.get("require") or [] if data.get(k) in (None, "", [], {})]
            if missing:
                return {
                    "ok": False,
                    "reason": "缺少契约字段：" + "、".join(missing),
                    "seconds": round(time.time() - started, 1),
                }
        else:
            text = (client.chat(messages, temperature=0.0, max_tokens=budget) or "").strip()
            if not text:
                return {"ok": False, "reason": "返回空正文", "seconds": round(time.time() - started, 1)}
        return {"ok": True, "reason": "", "seconds": round(time.time() - started, 1)}
    except Exception as exc:  # noqa: BLE001 探测失败就是要记录的结论
        return {
            "ok": False,
            "reason": f"{type(exc).__name__}: {str(exc)[:150]}",
            "seconds": round(time.time() - started, 1),
        }


def run_selfcheck(db: Session, *, triggered_by: str = "save") -> dict:
    """跑一轮兼容性自检；返回 {slots: {...}, warnings: [...], checked_at}。"""
    slots = model_settings.resolve_slots(db)
    result: dict = {"slots": {}, "warnings": [], "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "triggered_by": triggered_by}
    for name in ("model1", "model2"):
        slot = slots[name]
        label = f"{name}（{slot['vendor']}/{slot['model']}）"
        per_slot: dict = {"label": label, "probes": {}, "ok": True}
        for probe in PROBES:
            outcome = _probe_slot(slot, probe, db)
            per_slot["probes"][probe["key"]] = {"label": probe["label"], **outcome}
            if not outcome["ok"]:
                per_slot["ok"] = False
                result["warnings"].append(f"{label} 在「{probe['label']}」上不兼容：{outcome['reason']}")
        result["slots"][name] = per_slot
    result["ok"] = not result["warnings"]
    save_result(db, result)
    if result["ok"]:
        log.info("双模型兼容性自检通过：%s", ", ".join(result["slots"][n]["label"] for n in result["slots"]))
    else:
        log.warning("双模型兼容性自检发现问题：%s", "；".join(result["warnings"]))
    return result


def save_result(db: Session, result: dict) -> None:
    row = db.get(Kv, SELFCHECK_KV)
    payload = json.dumps(result, ensure_ascii=False)
    if row is None:
        db.add(Kv(key=SELFCHECK_KV, value=payload))
    else:
        row.value = payload
    db.commit()


def last_result(db: Session) -> dict | None:
    row = db.get(Kv, SELFCHECK_KV)
    if row is None or not (row.value or "").strip():
        return None
    try:
        data = json.loads(row.value)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


__all__ = ["PROBES", "SELFCHECK_KV", "last_result", "run_selfcheck", "save_result"]
