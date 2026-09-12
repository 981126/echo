"""人设服务：逐篇提取 → AI 归纳合并 → 增量合并 → 语义比对（R-126/R-128）。

提示词只给「方向盘」：明确角色与观察方向，把维度与措辞的自由度交给模型，
程序只解析固定字段（tags/redlines），不锁死条数与措辞。

所有 LLM 调用在未配置密钥时安全降级（返回空/机械合并结果），保证开发/测试离线可跑。
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, cast

from sqlalchemy.orm import Session

from ..core.topics import normalize_topics
from . import budget_settings, llm_router
from .prompt_service import get_prompt
from .llm import LLMError

PERSONA_INIT_SYSTEM = (
    "你是自媒体人设分析专家，长期为同一位作者做「人设画像」。"
    "现在只给你这位作者的**一篇**真实口播/文案转写稿，请你像人类观察者一样，"
    "从这一篇里读出作者身上真实存在的人设信号。\n"
    "可以从这些角度自由观察（只是方向，不限于此，也不要求每篇都覆盖）：\n"
    "- 说话语气与节奏（直接/温和/犀利/幽默/自嘲…）\n"
    "- 价值观与立场（为什么做这件事、在意什么、反对什么）\n"
    "- 口头禅 / 高频表达 / 称呼方式\n"
    "- 选题偏好与专业领域\n"
    "- 目标受众是谁、把观众当成什么人\n"
    "- 内容结构与叙事习惯（怎么开场、怎么收尾、爱不爱举例）\n"
    "- 明确的禁忌与边界（作者说了不做/不说的）\n"
    "要求：\n"
    "1. 只提炼这篇稿子里**真实出现**的信号，不要脑补、不要凑数；宁可少而准。\n"
    "2. label 用你自己觉得最贴切的短词，长度不限；description 说清这个特质在这篇里怎么体现。\n"
    "3. 提炼几条由你决定，只要每条都有依据。\n"
    "4. 只输出 JSON，不要解释：\n"
    '{"tags":[{"label":"简短标签","description":"一句话描述","dimension":"语气|价值观|口头禅|选题|受众|结构|专业|其他","evidence":"原文短句"}],'
    '"redlines":["作者明确不做的表达或内容"]}'
)

PERSONA_MERGE_SYSTEM = (
    "你是人设画像的总编。下面给你同一位作者多篇文案各自提炼出的人设信号（JSON 数组）。"
    "请你像人类主编一样做一次「总结去重」：把重复、近义、可以合并的信号归并成一份**精炼**的人设档案。\n"
    "要求：\n"
    "1. 合并近义与重复（例如「说话直接」「不绕弯子」「犀利」应归并为一条），保留最准确的措辞与最具体的描述。\n"
    "2. 只保留在原文里有依据的信号；不要为了凑数合并出空泛的大词。\n"
    "3. 维度由你决定，可参考：语气/价值观/口头禅/选题/受众/结构/专业/其他。\n"
    "4. 输出必须精炼：tags 控制在 20-35 条、redlines 控制在 15 条以内；"
    "description 用一句话（≤40 字），evidence 只留 1 条最典型短句（≤30 字），不要罗列。\n"
    "5. 只输出 JSON，不要解释、不要复述输入：\n"
    '{"tags":[{"label":"...","description":"...","dimension":"...","evidence":"..."}],"redlines":["..."]}'
)

PERSONA_UPDATES_SYSTEM = (
    "你是人设画像的迭代专家。给你作者「当前人设档案」和「一篇新文案的提炼结果」，"
    "请把新信号增量并入档案，产出更新后的完整档案。\n"
    "要求：\n"
    "1. 新增：档案里没有的新特质，补进去。\n"
    "2. 强化：已有特质的更具体描述或证据，用它替换原来更模糊的描述。\n"
    "3. 修正：与档案冲突的信号，以新文案的真实内容为准调整（不要凭空删档案）。\n"
    "4. 只依据两份输入的真实内容判断，不要脑补；输出保持精炼：tags 控制在 20-35 条、"
    "redlines 控制在 15 条以内，description ≤40 字、evidence ≤30 字。\n"
    "5. 只输出 JSON，不要解释、不要复述输入：\n"
    '{"tags":[{"label":"...","description":"...","dimension":"...","evidence":"..."}],"redlines":["..."]}'
)

PERSONA_COMPARE_SYSTEM = (
    "你是人设档案质检员。给你两份同一位作者的人设档案：A=增量更新得到的档案，B=从全部素材从头重算得到的档案。"
    "请判断 A 与 B 在「人设覆盖度」上是否等价，只输出 JSON："
    '{"score":0-100,"reason":"一句话说明差距"}。'
    "score 100 表示 A 完整覆盖 B（措辞不同但语义相同算覆盖）；B 里有而 A 完全缺失的重要特质越多，分数越低。"
)


VIDEO_TAGS_SYSTEM = (
    "你是视频内容标注助手。根据视频转写稿输出 JSON："
    '{"main_topics":["求职|面试|赚钱|知识|其他"],"is_ad":false,'
    '"tags":["简短标签1","简短标签2"]}'
    "main_topics 为赛道数组（可多个，至少一个）；is_ad 表示是否为商务广告"
    "（口播中明显推广产品/品牌）。只输出 JSON。"
)


_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_MAX_EVIDENCE = 200
# 归纳合并：单次送进模型的人设条目数 / 全局归纳最多接受的篇数（R-128）
_MERGE_BATCH = 30
GLOBAL_MERGE_MAX_PARTS = 120


def _norm_label(label: str) -> str:
    """去重键：去首尾/连续空白 + 小写（中文不受影响）。"""
    return " ".join((label or "").split()).lower()


def _split_phrases(text: str, limit: int) -> list[str]:
    out: list[str] = []
    seen = set()
    for part in _SENT_SPLIT.split(text or ""):
        part = part.strip()
        if 6 <= len(part) <= 40 and part not in seen and not part.startswith(("我", "这", "那", "你", "今天", "然后", "就是", "其实")):
            seen.add(part)
            out.append(part)
        if len(out) >= limit:
            break
    return out


def suggest_phrase_candidates(db, limit: int = 12) -> list[dict]:
    """从当前主博主高表现素材里挑短句候选（R-030③ 金句库）。"""
    from ..models.metrics import MetricsSnapshot
    from ..models.video import Video
    from .creator_service import current_creator_id

    cid = current_creator_id(db)
    q = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        q = q.filter(Video.creator_id == cid)
    rows = []
    for v in q.all():
        if not v.transcript:
            continue
        text = v.transcript.corrected_text or v.transcript.transcript_text
        if not text:
            continue
        eng = 0
        snap = (
            db.query(MetricsSnapshot)
            .filter(MetricsSnapshot.video_id == v.id)
            .order_by(MetricsSnapshot.snapshot_date.desc())
            .first()
        )
        if snap:
            eng = snap.plays + snap.likes * 5 + snap.favorites * 3 + snap.comments * 10
        rows.append((eng, v.title or "", text))
    rows.sort(key=lambda x: x[0], reverse=True)
    candidates: list[dict] = []
    seen = set()
    for eng, title, text in rows[:40]:
        for ph in _split_phrases(text, limit=5):
            if ph in seen:
                continue
            seen.add(ph)
            candidates.append({"text": ph, "source_title": title, "engagement": eng})
        if len(candidates) >= limit:
            break
    return candidates


def empty_profile() -> dict:
    return {"tags": [], "redlines": []}


def parse_persona_result(data: dict) -> dict:
    """把模型返回的 tags/redlines 清洗为内部结构（字段固定，内容自由）。"""
    result = empty_profile()
    for item in data.get("tags") or []:
        if not isinstance(item, dict):
            label = str(item).strip()
            if label:
                result["tags"].append({"label": label, "description": "", "dimension": "", "evidence": ""})
            continue
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        result["tags"].append(
            {
                "label": label[:100],
                "description": str(item.get("description", "")).strip(),
                "dimension": str(item.get("dimension", "")).strip()[:30],
                "evidence": str(item.get("evidence", "")).strip()[:_MAX_EVIDENCE],
            }
        )
    for redline in data.get("redlines") or []:
        text = str(redline).strip()
        if text:
            result["redlines"].append(text[:200])
    return result


def label_match(a: str, b: str) -> bool:
    """同义/近义判定：规范化后相等、互相包含，或字符相似度 ≥0.6。"""
    na, nb = _norm_label(a), _norm_label(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.6


def _better(cur: dict, incoming: dict) -> None:
    """把 incoming 的信息并入 cur：保留更完整的描述/证据，补齐空维度。"""
    if len(incoming.get("description", "")) > len(cur.get("description", "")):
        cur["description"] = incoming["description"]
    if len(incoming.get("evidence", "")) > len(cur.get("evidence", "")):
        cur["evidence"] = incoming["evidence"]
    if not cur.get("dimension") and incoming.get("dimension"):
        cur["dimension"] = incoming["dimension"]


def dedupe_profile(profile: dict) -> dict:
    """机械近义去重（不花 LLM）：标签/红线各自按 label_match 归并，保留更完整的描述。"""
    tags: list[dict] = []
    for item in (profile or {}).get("tags") or []:
        label = str(item.get("label", "")).strip() if isinstance(item, dict) else str(item).strip()
        if not label:
            continue
        incoming = {
            "label": label[:100],
            "description": str(item.get("description", "")).strip() if isinstance(item, dict) else "",
            "dimension": str(item.get("dimension", "")).strip()[:30] if isinstance(item, dict) else "",
            "evidence": str(item.get("evidence", "")).strip()[:_MAX_EVIDENCE] if isinstance(item, dict) else "",
        }
        for cur in tags:
            if label_match(label, cur["label"]):
                _better(cur, incoming)
                break
        else:
            tags.append(incoming)
    redlines: list[str] = []
    for redline in (profile or {}).get("redlines") or []:
        text = str(redline).strip()[:200]
        if not text:
            continue
        if not any(label_match(text, cur) for cur in redlines):
            redlines.append(text)
    return {"tags": tags, "redlines": redlines}


def collect_profile(parts: list[dict]) -> dict:
    """把多篇提炼结果摊平并机械去重（LLM 不可用时的兜底合并）。"""
    tags: list[dict] = []
    redlines: list[str] = []
    for part in parts or []:
        for item in (part or {}).get("tags") or []:
            tags.append(item if isinstance(item, dict) else {"label": str(item)})
        redlines.extend((part or {}).get("redlines") or [])
    return dedupe_profile({"tags": tags, "redlines": redlines})


def merge_mechanical(parts: list[dict]) -> dict:
    """兼容旧名：摊平 + 近义去重。"""
    return collect_profile(parts)


def _profile_size(profile: dict) -> int:
    return len((profile or {}).get("tags") or []) + len((profile or {}).get("redlines") or [])


def _profile_chunks(profile: dict, size: int) -> list[dict]:
    """把档案切成每块 ≤size 条的多个小档案（红线单独成块），供分批归纳。"""
    tags = list((profile or {}).get("tags") or [])
    chunks = [{"tags": tags[i : i + size], "redlines": []} for i in range(0, len(tags), size)]
    redlines = list((profile or {}).get("redlines") or [])
    if redlines:
        chunks.append({"tags": [], "redlines": redlines})
    return chunks or [profile]


class PersonaService:
    """人设相关 AI 能力（R-139：默认模型1 主用 → 模型2 降级）。

    - 传 `llm=` 走注入（测试/显式指定）；
    - 传 `db=` 时先取一次模型配置快照再调用（快照可安全跨线程，见 `llm_router`）；
    - 都不传时也用快照（自己开短连接取），因此 `PersonaService()` 的老写法仍然可用。
    """

    def __init__(self, llm=None, db: Session | None = None):
        self._injected = llm
        self._db = db
        self._snapshot: llm_router.RouteSnapshot | None = None
        self._active: llm_router.RoutedLLM | None = None
        self.last_routing: dict = {}

    def _route(self) -> llm_router.RouteSnapshot:
        if self._snapshot is None:
            if self._db is not None:
                self._snapshot = llm_router.snapshot(self._db)
            else:
                from ..db import SessionLocal

                db = SessionLocal()
                try:
                    self._snapshot = llm_router.snapshot(db)
                finally:
                    db.close()
        return self._snapshot

    def llm_for(self, feature: str) -> Any:
        """按功能取模型1 主用 + 模型2 降级的客户端（注入的 llm 优先）。"""
        if self._injected is not None:
            return self._injected
        client = llm_router.RoutedLLM(feature, self._route())
        self._active = client
        return client

    @property
    def llm(self) -> Any:
        """兼容旧写法（`service.llm.chat_json(...)`）：等价于 feature=misc。"""
        return self.llm_for("misc")

    def call_json(self, feature: str, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """按功能调 JSON（模型1 主用 → 模型2 降级），并记录本次实际使用的模型。"""
        client = self.llm_for(feature)
        try:
            return client.chat_json(messages, **kwargs)
        finally:
            if isinstance(client, llm_router.RoutedLLM):
                self.last_routing = client.routing()

    def analyze_one(self, transcript: str) -> dict:
        """单篇文案提炼人设（R-126）：一次调用只喂一篇；LLMError 由调用方逐篇兜底。"""
        messages = [
            {"role": "system", "content": get_prompt("persona_init")},
            {"role": "user", "content": transcript or ""},
        ]
        data = self.call_json("persona_init", messages)
        return parse_persona_result(data)

    def _llm_merge(self, key: str, parts: list[dict]) -> dict[str, Any] | None:
        """调 LLM 做归纳合并；失败/空结果返回 None（由调用方决定降级策略）。"""
        user = "待归纳的人设信号（JSON 数组）：\n" + json.dumps(parts, ensure_ascii=False)
        try:
            data = self.call_json(
                key,
                [
                    {"role": "system", "content": get_prompt(key)},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=budget_settings.budget_for(self._db, "persona_merge"),
            )
        except Exception:  # noqa: BLE001 外部服务任何异常都降级，不拖垮整条管线
            return None
        result = parse_persona_result(data)
        if not result["tags"] and not result["redlines"]:
            return None
        return result

    def merge_full(self, parts: list[dict]) -> dict:
        """全量归纳合并：把每篇提炼结果「总结去重」成一份人设档案（R-128 第1条）。

        实测结论：把「每篇提炼结果」原样喂给模型时，它能站在全局视角把 65 篇压成约 40 条；
        而先机械摊平成一个几百条的扁平列表再喂，模型反而压不住、输出还会超 max_tokens 被截断。
        因此：
        1) 优先一次全局归纳（直接喂每篇提炼结果）；
        2) 全局失败或篇数过多时，退回「机械近义去重 + 分批归纳 + 再机械去重」的稳健路径。
        """
        clean = [p for p in (parts or []) if p]
        if not clean:
            return empty_profile()
        if len(clean) <= GLOBAL_MERGE_MAX_PARTS:
            merged = self._llm_merge("persona_merge", clean)
            if merged is not None:
                return dedupe_profile(merged)
        profile = collect_profile(clean)
        if _profile_size(profile) == 0:
            return empty_profile()
        for _ in range(3):
            if _profile_size(profile) <= _MERGE_BATCH:
                break
            chunks = _profile_chunks(profile, _MERGE_BATCH)
            if len(chunks) <= 1:
                break
            merged_parts: list[dict] = []
            for chunk in chunks:
                merged_parts.append(self._llm_merge("persona_merge", [chunk]) or chunk)
            reduced = collect_profile(merged_parts)
            if _profile_size(reduced) >= _profile_size(profile):
                break
            profile = reduced
        final = self._llm_merge("persona_merge", [profile])
        return dedupe_profile(final) if final is not None else profile

    def merge_incremental(self, current: dict, new_part: dict) -> dict:
        """增量合并：把新文案信号并入当前档案，产出更新后的完整档案（R-128 第2条）。"""
        parts = [current or empty_profile(), new_part or empty_profile()]
        merged = self._llm_merge("persona_updates", parts)
        if merged is None:
            return collect_profile(parts)
        return dedupe_profile(merged)

    def compare_profiles(self, a: dict, b: dict) -> dict:
        """语义复核：A(增量) 与 B(全量) 的等价度打分（0-100）；失败返回 score=None。"""
        user = (
            "A 增量档案：\n"
            + json.dumps(a or empty_profile(), ensure_ascii=False)
            + "\n\nB 全量档案：\n"
            + json.dumps(b or empty_profile(), ensure_ascii=False)
        )
        try:
            data = self.call_json(
                "persona_compare",
                [
                    {"role": "system", "content": get_prompt("persona_compare")},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=500,
            )
        except Exception:  # noqa: BLE001 语义复核失败不阻断（仅按覆盖率判定）
            return {"score": None, "reason": "语义复核不可用（AI 服务异常），本次仅按集合覆盖率判定"}
        try:
            score = float(cast(Any, data.get("score")))
        except (TypeError, ValueError):
            return {"score": None, "reason": "语义复核返回异常，本次仅按集合覆盖率判定"}
        score = max(0.0, min(100.0, score))
        return {"score": score, "reason": str(data.get("reason", "")).strip()}

    def suggest_video_tags(self, transcript: str) -> dict:
        """AI 预打标签：赛道（可多选）/ 是否广告 / 自定义标签。"""
        messages = [
            {"role": "system", "content": get_prompt("video_tags")},
            {"role": "user", "content": transcript},
        ]
        try:
            data = self.call_json("video_tags", messages)
        except LLMError:
            data = {}
        values = data.get("main_topics") or data.get("main_topic") or []
        return {
            "main_topics": normalize_topics(values),
            "is_ad": bool(data.get("is_ad", False)),
            "tags": [str(t).strip() for t in data.get("tags") or [] if str(t).strip()],
        }
