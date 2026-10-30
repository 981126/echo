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

from ..config import get_settings
from ..core.log import get_logger
from . import model_settings
from .llm import LLMError, LLMUnusableOutput, OpenAIClient, accepts_timeout

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
    "video_review": "视频复盘",
    "ideas": "选题灵感",
    "draft_meta": "标题封面标签生成",
    "misc": "AI 调用",
}

# R-240 M6：feature → **单次** LLM 调用的墙钟预算（秒）。只收紧、不放宽（.tmp/audit/infra.md F-02）：
# - 全局 `ECHO_LLM_TIMEOUT_SECONDS`（默认 600）仍是硬上限，最终取 min(本表, 全局)；
# - 交互类：chat 90（用户等回答）、ideas 30（选题灵感，接口同步返回）、draft_meta 90；
# - JSON 小任务：video_tags / diff / feedback_analysis / persona_compare 120；correct 180、
#   persona_updates 180（复核：历史 Kimi 路由下单次 p90≈110s，120s 临界 → 留给 1.6× 余量）；
# - ideas 100（复核：历史 Kimi 语义聚类 p50≈79s，原 30s 会大概率超时回退本地聚类/原文；
#   与 opportunity._ask_groups 的 100s 软超时对齐，仍比旧 600s 收紧 6×）；
# - 提示词/对标/复盘：prompt_optimize 240（优化本身要重写整段提示词）、prompt_eval 180、
#   benchmark 240、video_review 180；
# - 人设长输出：persona_init 300 / persona_merge 360（合并要归纳多篇提炼结果，R-142 实测
#   Kimi 12000 预算单次 180.3s，用 misc=120 会误杀→降级→再失败；故按长输出档放宽）；
# - 生成/讨论：generation / debate / rework / rewrite 360（R-142 实测 Kimi 12000 预算单次 180.3s，
#   留 2× 余量；生成链路单次最多 3 次尝试 → 最坏 1080s，而原来 600×3=1800s）；
# - misc 120 兜底（表里没有的功能）。
# 取值动机：单次逻辑调用最坏 = 主模型 2 次 + 降级 1 次，feature 预算把最坏墙钟压到 3×预算。
FEATURE_TIMEOUTS: dict[str, int] = {
    "chat": 90,
    "correct": 180,
    "video_tags": 120,
    "persona_init": 300,
    "persona_merge": 360,
    "persona_updates": 180,
    "persona_compare": 120,
    "ideas": 100,
    "draft_meta": 90,
    "diff": 120,
    "feedback_analysis": 120,
    "prompt_optimize": 240,
    "prompt_eval": 180,
    "benchmark": 240,
    "video_review": 180,
    "generation": 360,
    "debate": 360,
    "rework": 360,
    "rewrite": 360,
    "misc": 120,
}
DEFAULT_FEATURE_TIMEOUT = 120
# 客户端下限（OpenAIClient 同样夹到 ≥30，避免把预算配成 0/负数，见 R-142）。
MIN_CALL_TIMEOUT_SECONDS = 30


def feature_timeout_seconds(feature: str, requested: int | None = None) -> int:
    """单次调用的墙钟预算（秒）：feature 表 → 全局上限 → 调用方剩余 deadline，三者取 min。"""
    budget = int(FEATURE_TIMEOUTS.get(feature or "", DEFAULT_FEATURE_TIMEOUT))
    global_limit = int(
        getattr(get_settings(), "llm_timeout_seconds", 0) or 0
    ) or OpenAIClient.DEFAULT_TIMEOUT_SECONDS
    budget = min(budget, global_limit)
    if requested is not None:
        budget = min(budget, int(requested))
    return max(MIN_CALL_TIMEOUT_SECONDS, budget)


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


def build_client(slot: dict, timeout_seconds: int | None = None) -> OpenAIClient:
    """按槽位快照建客户端（纯快照，不读 settings）。

    `timeout_seconds` 是本次调用的单次墙钟预算（R-240 M6）；不传则沿用全局 ECHO_LLM_TIMEOUT_SECONDS。
    """
    return OpenAIClient(
        base_url=slot.get("base_url", ""),
        api_key=slot.get("api_key", ""),
        model=slot.get("model", ""),
        supports_temperature=bool(slot.get("supports_temperature", True)),
        timeout_seconds=timeout_seconds,
    )


def _client_with_timeout(slot: dict, timeout_seconds: int) -> OpenAIClient:
    """建本次调用的客户端并套用墙钟预算。

    兼容只有单参签名的旧实现/测试替身（`build_client` 新增可选参数后不能强求所有替换实现同步）：
    传参报 TypeError 时退回旧签名，再在实例上覆盖 `timeout_seconds`（即单次上限）。
    """
    if accepts_timeout(build_client):
        return build_client(slot, timeout_seconds=timeout_seconds)
    # 旧单参替身：先按旧签名构造，再在实例上覆盖单次上限（不改变任何调用语义）
    client = build_client(slot)
    client.timeout_seconds = timeout_seconds
    return client


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
    """一次批读配置 → 派生 slots + 生成方/评审方（R-240 S4：20~21 条 KV → 1 条 `key IN`）。"""
    config = model_settings.get_model_config(db)
    return RouteSnapshot(
        model_settings.resolve_slots(db, config),
        *model_settings.generation_roles(db, config),
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

    def _run(
        self,
        method: str,
        kwargs: dict,
        validate: Callable[[Any], str],
        timeout_seconds: int | None = None,
    ) -> Any:
        """主模型 → 降级模型；`validate` 返回失败原因，空串表示通过。

        「输出不合法」再试一次时把 `max_tokens` 翻倍（R-139/R-142）：推理模型的思考会吃满预算导致
        正文为空，这是「重试/降级后像退化了」最常见的伪装。每个槽位各自套用自己的厂家下限；
        连接级瞬时错误（连接重置等）同类重试一次再降级，避免把网络抖动记成模型降级。

        R-240 M6：每次 attempt 都带 feature 墙钟预算（`min(本功能预算, 全局上限, 调用方剩余 deadline)`），
        重试/降级语义与异常类型保持不变，只是不再允许单次 attempt 跑满 600s。
        """
        started = time.time()
        problems: list[str] = []
        base_budget = int(kwargs.get("max_tokens") or 0)
        per_call_timeout = feature_timeout_seconds(self.feature, timeout_seconds)
        for slot, allow_retry in self._attempts():
            budget = base_budget
            for i in range(2 if allow_retry else 1):
                if i:
                    budget = min(budget * 2, MAX_TOKENS_CEILING)  # 预算翻倍后再试
                # R-240 复核修复（BUG-3）：每次 attempt 用「总预算 - 已耗时」的剩余值建客户端，
                # 否则主模型 2 次 + 降级 1 次会各拿满一次预算（chat 的 120s 软 deadline 会被放大）。
                elapsed = int(time.time() - started)
                remaining = max(MIN_CALL_TIMEOUT_SECONDS, per_call_timeout - elapsed)
                client = _client_with_timeout(slot, remaining)
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
        timeout_seconds: int | None = None,
    ) -> dict:
        """带 tools 的原始调用（AI 对话用）；返回 message 字典（含 tool_calls）。

        `timeout_seconds` 是调用方给的剩余墙钟（如 chat 的 deadline-now，R-240 M6），
        最终与 feature 预算/全局上限取 min。
        """
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

        return self._run("chat_completion", kwargs, validate, timeout_seconds)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
        timeout_seconds: int | None = None,
    ) -> str:
        if json_mode:
            return json.dumps(
                self.chat_json(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                ),
                ensure_ascii=False,
            )
        mt = normalize_max_tokens(self.route.slot(self.primary_slot_name), max_tokens)

        def validate(out: Any) -> str:
            return "" if str(out or "").strip() else "返回空正文"

        return str(
            self._run(
                "chat",
                {"messages": messages, "temperature": temperature, "max_tokens": mt},
                validate,
                timeout_seconds,
            )
        )

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
        require: tuple[str, ...] = (),
        timeout_seconds: int | None = None,
    ) -> dict:
        """JSON 调用；`require` 是本次功能的输出契约字段（缺失即不合法 → 降级）。"""
        mt = normalize_max_tokens(self.route.slot(self.primary_slot_name), max_tokens)

        def validate(out: Any) -> str:
            if not isinstance(out, dict):
                return "不是 JSON 对象"
            missing = [k for k in require if out.get(k) in (None, "", [], {})]
            return ("缺少契约字段：" + "、".join(missing)) if missing else ""

        return self._run(
            "chat_json",
            {"messages": messages, "temperature": temperature, "max_tokens": mt},
            validate,
            timeout_seconds,
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
    primary: str | None = None,
) -> RoutedLLM:
    """非脚本生成的 AI 功能统一入口：主用槽位 → 另一槽位兜底。

    R-229：`primary` 可显式指定主用槽位（如生成方）。
    R-232：`primary` 缺省时按**功能路由**解析（AI 设置里每功能选模型1/模型2，
    存 app_kv，默认 model1；prompt_opt 组默认跟随生成方）。
    """
    if primary is None:
        primary = model_settings.feature_route(db, feature)
    fallback = "model2" if primary == "model1" else "model1"
    return RoutedLLM(
        feature,
        _snapshot_any(db),
        primary=primary,
        fallback=fallback,
        notifier=notifier,
        target=target,
    )


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
    "FEATURE_TIMEOUTS",
    "RouteSnapshot",
    "RoutedLLM",
    "build_client",
    "feature_label",
    "feature_timeout_seconds",
    "llm_from_snapshot",
    "normalize_max_tokens",
    "primary_llm",
    "reset_notify_cooldown",
    "snapshot",
]
