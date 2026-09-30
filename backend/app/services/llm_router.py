"""统一模型路由与降级层（R-139）。

设计要点：
1. **默认模型1 主用，出问题降级模型2**：除脚本生成（走双模型讨论）外的所有 AI 功能都走这里。
   降级触发条件：报错 / 超时 / 空正文 / 输出不合法（JSON 解析失败或缺契约字段）。
2. **两个模型吃同一份上下文**：调用方只组装一次 messages，路由层原样喂给两个模型，
   因此模型1/2 的输入完全一致（不会出现「降级后像退化了」）。
3. **参数按厂家归一化**：`supports_temperature=False` 的推理模型不传 temperature；
   `min_max_tokens` 兜底（推理模型拿到小 max_tokens 会把预算耗在思考上 → 正文为空）。
4. **降级可见**：日志 + 站内通知（带冷却，避免同一故障刷屏）+ `RoutedLLM.degraded` 供调用方标记。
5. **线程安全**：只持有普通 dict 快照，不持有 SQLAlchemy Session；通知自己开短连接。
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

import httpx

from ..core.log import get_logger
from . import model_settings
from .llm import LLMError, LLMUnusableOutput, OpenAIClient

log = get_logger("llm_router")

# 功能名 → 中文标签（通知/日志用）
FEATURE_LABELS: dict[str, str] = {
    "generation": "脚本生成",
    "persona_init": "人设提取",
    "persona_merge": "人设合并",
    "persona_updates": "人设增量校验",
    "persona_compare": "人设对齐校验",
    "video_tags": "视频预打标",
    "correct": "转写校对",
    "chat": "AI 对话",
    "diff": "差异分析",
    "feedback_analysis": "反馈学习",
    "prompt_optimize": "提示词优化",
    "prompt_eval": "金样本评测",
    "benchmark": "对标分析",
    "ideas": "选题灵感",
    "misc": "AI 调用",
}

# 单次调用 max_tokens 上限（防手写参数把成本打爆）。
# R-142：推理模型的思考会让「预算翻倍重试」把值推高，封顶给到 32000 仍留有余地。
MAX_TOKENS_CEILING = 32000
# 连接级瞬时错误（连接被重置/写失败等）同类重试 1 次，避免把网络抖动当成模型降级；
# 超时（ReadTimeout）不重试——重试只会把等待翻倍。
RETRYABLE_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)
# 同一功能降级通知冷却（秒）：故障持续时不刷屏
NOTIFY_COOLDOWN_SECONDS = 1800
_LAST_NOTIFY: dict[str, float] = {}


def feature_label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature or "AI 调用")


def _slot_label(slot: dict) -> str:
    return f"{slot.get('slot', '')}({slot.get('vendor', '')}/{slot.get('model', '')})"


def reset_notify_cooldown() -> None:
    """测试/配置变更后允许立刻再通知一次。"""
    _LAST_NOTIFY.clear()


def normalize_max_tokens(slot: dict, max_tokens: int) -> int:
    """按厂家归一化 max_tokens：不低于该厂家下限、不超过全局上限。"""
    floor = int(slot.get("min_max_tokens") or 0)
    return min(max(int(max_tokens or 0), floor, 1), MAX_TOKENS_CEILING)


def build_client(slot: dict) -> OpenAIClient:
    """按槽位快照建客户端（纯快照，不读 settings）。"""
    return OpenAIClient(
        base_url=slot.get("base_url", ""),
        api_key=slot.get("api_key", ""),
        model=slot.get("model", ""),
        supports_temperature=bool(slot.get("supports_temperature", True)),
    )


class RouteSnapshot:
    """一次任务内固定不变的模型配置快照（可安全跨线程使用，无 DB 会话）。"""

    def __init__(self, slots: dict[str, dict], gen_role: str, referee_role: str):
        self.slots = slots
        self.gen_role = gen_role
        self.referee_role = referee_role

    def slot(self, name: str) -> dict:
        return self.slots[name]

    def generation_pair(self) -> tuple[dict, dict]:
        """（生成方槽位, 评审方槽位）；两方允许是同一个槽位。"""
        return self.slots[self.gen_role], self.slots[self.referee_role]


def snapshot(db: Session) -> RouteSnapshot:
    return RouteSnapshot(
        model_settings.resolve_slots(db),
        *model_settings.generation_roles(db),
    )


def _default_notify(feature: str, detail: str, target: str) -> None:
    """默认降级通知：写站内通知（自己开短连接，避免跨线程共用 Session）。"""
    now = time.time()
    if now - _LAST_NOTIFY.get(feature, 0.0) < NOTIFY_COOLDOWN_SECONDS:
        return
    _LAST_NOTIFY[feature] = now
    try:
        from ..db import SessionLocal
        from ..tasks import push_notification

        db = SessionLocal()
        try:
            push_notification(
                db,
                kind="llm_fallback",
                status="failed",
                title=f"模型1 调用失败，已降级模型2（{feature_label(feature)}）",
                message=detail[:200],
                target=target,
            )
        finally:
            db.close()
    except Exception:  # noqa: BLE001 通知失败不能影响主流程
        log.exception("降级通知写入失败")


class RoutedLLM:
    """模型1 主用 + 模型2 降级，接口与 `OpenAIClient` 兼容。

    - `chat(...)` / `chat_json(...)` 与 `OpenAIClient` 同签名（`chat_json` 多一个 `require` 契约字段）；
    - 调用成功后 `used_slot` / `used_vendor` / `used_model` 是实际出结果的模型；
    - 降级发生时 `degraded=True`、`last_error` 记录主模型失败原因。
    """

    def __init__(
        self,
        feature: str,
        route: RouteSnapshot,
        *,
        primary: str = "model1",
        fallback: str | None = "model2",
        notifier: Callable[[str, str, str], None] | None = None,
        target: str = "/prompts",
    ):
        self.feature = feature
        self.route = route
        self.primary_slot_name = primary
        self.fallback_slot_name = fallback
        self._notifier = notifier or _default_notify
        self.target = target
        self.degraded = False
        self.last_error = ""
        first = route.slot(primary)
        self.used_slot = first["slot"]
        self.used_vendor = first["vendor"]
        self.used_model = first["model"]

    # ---------- 对外信息 ----------
    @property
    def model(self) -> str:
        return self.used_model

    def routing(self) -> dict:
        return {
            "feature": self.feature,
            "primary": _slot_label(self.route.slot(self.primary_slot_name)),
            "used": f"{self.used_slot}({self.used_vendor}/{self.used_model})",
            "degraded": self.degraded,
            "error": self.last_error[:200],
        }

    # ---------- 内部 ----------
    def _mark(self, slot: dict) -> None:
        self.used_slot = slot["slot"]
        self.used_vendor = slot["vendor"]
        self.used_model = slot["model"]

    def _degrade(self, reason: str, elapsed: float) -> None:
        self.degraded = True
        self.last_error = reason
        detail = (
            f"功能：{feature_label(self.feature)}；原因：{reason[:160]}；"
            f"耗时：{elapsed:.1f}s；主模型：{_slot_label(self.route.slot(self.primary_slot_name))}；"
            f"已改用：{_slot_label(self.route.slot(self.fallback_slot_name or self.primary_slot_name))}"
        )
        log.warning("模型降级：%s", detail)
        try:
            self._notifier(self.feature, detail, self.target)
        except Exception:  # noqa: BLE001
            log.exception("降级通知回调失败")

    def _attempts(self):
        """(槽位, 是否允许因「输出不合法」再试一次)：主模型允许重试 1 次，降级模型只试 1 次。"""
        names = [self.primary_slot_name]
        if self.fallback_slot_name and self.fallback_slot_name != self.primary_slot_name:
            names.append(self.fallback_slot_name)
        for i, name in enumerate(names):
            yield self.route.slot(name), i == 0

    def _run(self, method: str, kwargs: dict, validate: Callable[[Any], str]) -> Any:
        """主模型 → 降级模型；`validate` 返回失败原因，空串表示通过。

        「输出不合法」再试一次时把 `max_tokens` 翻倍（R-139/R-142）：推理模型的思考会吃满预算导致
        正文为空，这是「重试/降级后像退化了」最常见的伪装。每个槽位各自套用自己的厂家下限；
        连接级瞬时错误（连接重置等）同类重试一次再降级，避免把网络抖动记成模型降级。
        """
        started = time.time()
        problems: list[str] = []
        base_budget = int(kwargs.get("max_tokens") or 0)
        for slot, allow_retry in self._attempts():
            client = build_client(slot)
            budget = base_budget
            for i in range(2 if allow_retry else 1):
                if i:
                    budget = min(budget * 2, MAX_TOKENS_CEILING)  # 预算翻倍后再试
                attempt_kwargs = dict(kwargs)
                if "max_tokens" in kwargs:
                    attempt_kwargs["max_tokens"] = normalize_max_tokens(slot, budget)
                try:
                    out = getattr(client, method)(**attempt_kwargs)
                except LLMUnusableOutput as exc:
                    # 输出不可用但服务正常 → 值得抬预算重试（推理模型的思考长度有随机性）
                    problems.append(f"{_slot_label(slot)} 输出不可用：{exc}")
                    continue
                except LLMError as exc:
                    problems.append(f"{_slot_label(slot)} 报错：{exc}")
                    break  # 协议层错误（无 Key / 服务不可用）不重试，直接降级
                except RETRYABLE_TRANSPORT_ERRORS as exc:
                    # 连接被重置这类瞬时问题：同类重试一次（不翻预算），仍失败才降级
                    problems.append(f"{_slot_label(slot)} 连接异常：{type(exc).__name__}: {exc}")
                    if i == 0 and allow_retry:
                        continue
                    break
                except Exception as exc:  # noqa: BLE001 超时/HTTP/其它错误
                    problems.append(f"{_slot_label(slot)} 调用失败：{type(exc).__name__}: {exc}")
                    break
                reason = validate(out)
                if not reason:
                    self._mark(slot)
                    if slot["slot"] != self.primary_slot_name:
                        self._degrade("；".join(problems) or "主模型不可用", time.time() - started)
                    return out
                problems.append(f"{_slot_label(slot)} 输出不合法：{reason}")
        raise LLMError(
            f"[{feature_label(self.feature)}] 模型1/2 均未产出可用结果：" + "；".join(problems[-4:])
        )

    # ---------- 与 OpenAIClient 兼容的接口 ----------
    def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: list[dict] | None = None,
    ) -> dict:
        """带 tools 的原始调用（AI 对话用）；返回 message 字典（含 tool_calls）。"""
        mt = normalize_max_tokens(self.route.slot(self.primary_slot_name), max_tokens)
        kwargs: dict = {"messages": messages, "temperature": temperature, "max_tokens": mt}
        if tools:
            kwargs["tools"] = tools

        def validate(out: Any) -> str:
            if not isinstance(out, dict):
                return "返回结构异常"
            if str(out.get("content") or "").strip() or out.get("tool_calls"):
                return ""
            return "返回空正文"

        return self._run("chat_completion", kwargs, validate)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        if json_mode:
            return json.dumps(self.chat_json(messages, temperature=temperature, max_tokens=max_tokens), ensure_ascii=False)
        mt = normalize_max_tokens(self.route.slot(self.primary_slot_name), max_tokens)

        def validate(out: Any) -> str:
            return "" if str(out or "").strip() else "返回空正文"

        return str(
            self._run(
                "chat", {"messages": messages, "temperature": temperature, "max_tokens": mt}, validate
            )
        )

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
        require: tuple[str, ...] = (),
    ) -> dict:
        """JSON 调用；`require` 是本次功能的输出契约字段（缺失即不合法 → 降级）。"""
        mt = normalize_max_tokens(self.route.slot(self.primary_slot_name), max_tokens)

        def validate(out: Any) -> str:
            if not isinstance(out, dict):
                return "不是 JSON 对象"
            missing = [k for k in require if out.get(k) in (None, "", [], {})]
            return ("缺少契约字段：" + "、".join(missing)) if missing else ""

        return self._run(
            "chat_json", {"messages": messages, "temperature": temperature, "max_tokens": mt}, validate
        )


def _snapshot_any(db: Session | None) -> RouteSnapshot:
    """没有可用会话时自己开一个短连接取快照（线程池/AI 对话等场景）。"""
    if db is not None:
        return snapshot(db)
    from ..db import SessionLocal

    own = SessionLocal()
    try:
        return snapshot(own)
    finally:
        own.close()


def primary_llm(
    db: Session | None,
    feature: str,
    *,
    notifier: Callable[[str, str, str], None] | None = None,
    target: str = "/prompts",
) -> RoutedLLM:
    """非脚本生成的 AI 功能统一入口：模型1 主用 → 模型2 降级。"""
    return RoutedLLM(feature, _snapshot_any(db), notifier=notifier, target=target)


def llm_from_snapshot(
    route: RouteSnapshot,
    feature: str,
    *,
    notifier: Callable[[str, str, str], None] | None = None,
    target: str = "/prompts",
) -> RoutedLLM:
    """线程池场景用：先 `snapshot(db)`，再在每个线程里用它建客户端。"""
    return RoutedLLM(feature, route, notifier=notifier, target=target)


__all__ = [
    "FEATURE_LABELS",
    "RouteSnapshot",
    "RoutedLLM",
    "build_client",
    "feature_label",
    "llm_from_snapshot",
    "normalize_max_tokens",
    "primary_llm",
    "reset_notify_cooldown",
    "snapshot",
]
