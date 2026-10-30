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
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from sqlalchemy.orm import Session

from ..core.log import get_logger
from ..models.kv import Kv
from . import llm_router, model_settings
from .prompt_service import get_prompt

log = get_logger("model_health")

SELFCHECK_KV = "model_selfcheck_result"
# R-241 F-08：2 槽 × 3 探针并行（并发 ≤3，避免同厂家 429），每探针 60~90s 墙钟。
SELFCHECK_CONCURRENCY = 3
PROBE_TIMEOUT_SECONDS = 90
# future.result 硬等待比 LLM 墙钟多 5s：先让 OpenAIClient 的超时以可读 LLMError 呈现；
# 只有探针卡在 LLM 之外（异常路径）才落到「探针超时」记录，线程泄漏上限仍是 90s+5s。
PROBE_FUTURE_GRACE_SECONDS = 5

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


def _probe_client(slot: dict) -> llm_router.OpenAIClient:
    """建探针客户端并套用单探针墙钟（R-241 F-08）。

    兼容只有单参签名的 build_client 替身（测试/旧实现）：传参报 TypeError 时退回旧签名再设属性。
    """
    try:
        return llm_router.build_client(slot, timeout_seconds=PROBE_TIMEOUT_SECONDS)
    except TypeError:
        client = llm_router.build_client(slot)
        client.timeout_seconds = PROBE_TIMEOUT_SECONDS
        return client


def _probe_slot(slot: dict, probe: dict, system: str) -> dict:
    """跑一个探针（不碰 DB：提示词由 run_selfcheck 在主线程预先取好，可安全跨线程调用）。"""
    client = _probe_client(slot)
    # 参数归一化：探测也要按厂家下限给足 max_tokens，否则推理模型会被误判为「不兼容」
    budget = llm_router.normalize_max_tokens(slot, 800)
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
    """跑一轮兼容性自检；返回 {slots: {...}, warnings: [...], checked_at}。

    R-241 F-08：2 槽 × 3 探针**并行**（并发 ≤SELFCHECK_CONCURRENCY），每探针 60~90s 墙钟；
    主线程先取探针提示词并 commit，探针期间不占用/不常驻 DB 连接；结果结构与通知文案不变。
    """
    slots = model_settings.resolve_slots(db)
    # 探针提示词在主线程一次取好（避免跨线程共用一个 Session），随后 commit 把连接还给池
    systems: dict[str, str] = {}
    for probe in PROBES:
        prompt_key = probe.get("prompt_key")
        if prompt_key:
            systems[probe["key"]] = get_prompt(prompt_key, db)
    db.commit()

    result: dict = {"slots": {}, "warnings": [], "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "triggered_by": triggered_by}
    # 先并行跑完 6 个探针，再按 model1/model2 × PROBES 的原顺序聚合（输出结构与顺序不变）
    outcomes: dict[tuple[str, str], dict] = {}
    with ThreadPoolExecutor(
        max_workers=min(SELFCHECK_CONCURRENCY, len(PROBES) * len(slots)),
        thread_name_prefix="echo-selfcheck",
    ) as executor:
        jobs: list[tuple[str, dict, float, Future[dict]]] = []
        for name in ("model1", "model2"):
            slot = slots[name]
            for probe in PROBES:
                system = probe.get("system") or systems.get(probe["key"], "")
                started = time.time()
                jobs.append((name, probe, started, executor.submit(_probe_slot, slot, probe, system)))
        for name, probe, started, future in jobs:
            try:
                outcomes[(name, probe["key"])] = future.result(
                    timeout=PROBE_TIMEOUT_SECONDS + PROBE_FUTURE_GRACE_SECONDS
                )
            except FuturesTimeout:
                future.cancel()
                outcomes[(name, probe["key"])] = {
                    "ok": False,
                    "reason": f"探针超过 {PROBE_TIMEOUT_SECONDS}s 未返回，已跳过",
                    "seconds": round(time.time() - started, 1),
                }
                log.warning("模型自检探针超时：%s / %s", name, probe["label"])
    for name in ("model1", "model2"):
        slot = slots[name]
        label = f"{name}（{slot['vendor']}/{slot['model']}）"
        per_slot: dict = {"label": label, "probes": {}, "ok": True}
        for probe in PROBES:
            outcome = outcomes[(name, probe["key"])]
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
