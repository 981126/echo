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
    "请像人类主编一样做一次「总结去重」，并把结果按**四层**归类输出。\n"
    "四层定义（务必分清，不要混淆）：\n"
    "- core_dna 核心人格与语言 DNA：最稳定、最能把这个作者和别人区分开的**写作口吻**特征"
    "（语气、句式习惯、标志性表达、底层态度）。只保留 6-10 条。\n"
    "- stance 内容立场与可信经历：作者在选题上的观点/立场/亲身经历（如学历、收入、行业判断、价值取舍），可随创作演化。\n"
    "- mode 创作模式：作者常用的内容形态（如 犀利干货 / 个人独白 / 热点评论 / 实验复盘）。\n"
    "- forbidden 真正禁区：**只收「发布风险 / 法律合规 / 商业边界」三类**——"
    "(a) 平台会限流或封号的表达/操作；(b) 与自身商业利益冲突的边界（接广告范围、收费·卖课·带人边界）；"
    "(c) 法律或明显道德风险。个人生活习惯、工作态度、投资/饮食选择、一次性做法都不算禁区；"
    "观点与策略属于 stance。没有就给空数组，**宁少勿滥（0-8 条）**。\n"
    "要求：\n"
    "1. 合并近义与重复，只保留原文有依据的信号，不凑空泛大词。\n"
    "2. description 一句话（≤40 字）；evidence 只留 1 条最典型原文短句（≤30 字）。\n"
    "3. 只输出 JSON，不要解释、不要复述输入：\n"
    '{"core_dna":[{"label":"...","description":"...","evidence":"..."}],'
    '"stance":[{"label":"...","description":"...","evidence":"..."}],'
    '"mode":[{"label":"...","description":"...","evidence":"..."}],"forbidden":["作者绝不做/不说的行为"]}'
)

PERSONA_UPDATES_SYSTEM = (
    "你是人设画像的迭代专家。输入：作者的「当前四层档案」(JSON) 和「一篇新文案的提炼结果」(JSON)。"
    "请把新信号增量并入档案，输出更新后的完整四层档案。\n"
    "四层：core_dna 核心人格与语言 DNA（6-10 条，写作口吻层面）/ stance 内容立场与可信经历 / "
    "mode 创作模式 / forbidden 真正的禁区（**只收发布风险·法律合规·商业边界三类**；"
    "个人习惯、工作态度、投资/饮食选择都不算，观点策略归 stance）。\n"
    "要求：1) 新增新特质；2) 用更具体的描述/证据强化已有特质；3) 与新文案冲突时以新文案为准修正（不凭空删档案）；"
    "4) 只依据两份输入判断，不脑补；description ≤40 字、evidence ≤30 字。\n"
    "只输出 JSON，不要解释、不要复述输入：\n"
    '{"core_dna":[{"label":"...","description":"...","evidence":"..."}],'
    '"stance":[...],"mode":[...],"forbidden":["..."]}'
)

# R-182：人设四层。语句/态度→core_dna，观点立场/经历→stance，内容形态→mode，行为禁区→forbidden。
CORE_DNA = "core_dna"
STANCE = "stance"
MODE = "mode"
FORBIDDEN = "forbidden"
LAYERS = (CORE_DNA, STANCE, MODE, FORBIDDEN)
LAYER_LABELS: dict[str, str] = {
    CORE_DNA: "核心DNA",
    STANCE: "内容立场",
    MODE: "创作模式",
    FORBIDDEN: "禁区",
}
_CORE_DIMENSIONS = {"语气", "口头禅", "结构"}
_STANCE_DIMENSIONS = {"价值观", "专业", "受众", "选题", "领域"}


def _default_layer(dimension: str) -> str:
    """模型没给 layer 时按维度粗分层（保守默认 stance）。"""
    d = (dimension or "").strip()
    if d in _CORE_DIMENSIONS:
        return CORE_DNA
    if d in _STANCE_DIMENSIONS:
        return STANCE
    return STANCE


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
    """从当前主博主高表现素材里挑短句候选（R-030③ 金句库）。

    R-240 S3：`selectinload(Video.transcript)` + 一次批量取最新指标，消除 1+N 查询
    （原实现每条素材一次 transcript 懒加载 + 一次 MetricsSnapshot 查询）；输出顺序/内容不变。
    """
    from sqlalchemy.orm import selectinload

    from ..models.video import Video
    from .creator_service import current_creator_id
    from .generation import _engagement_map

    cid = current_creator_id(db)
    q = (
        db.query(Video)
        .options(selectinload(Video.transcript))
        .filter(Video.is_ad.is_(False))
    )
    if cid:
        q = q.filter(Video.creator_id == cid)
    videos = q.all()
    engagements = _engagement_map(db, videos)
    rows = []
    for v in videos:
        if not v.transcript:
            continue
        text = v.transcript.corrected_text or v.transcript.transcript_text
        if not text:
            continue
        rows.append((engagements.get(v.id, 0), v.title or "", text))
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


def _tag_item(item: object, layer: str) -> dict | None:
    """把四层输出里的一个条目规范成内部 tag（兼容字符串与对象）。"""
    if isinstance(item, dict):
        label = str(item.get("label", "")).strip()
        if not label:
            return None
        return {
            "label": label[:100],
            "description": str(item.get("description", "")).strip(),
            "dimension": str(item.get("dimension", "")).strip()[:30],
            "evidence": str(item.get("evidence", "")).strip()[:_MAX_EVIDENCE],
            "layer": layer,
        }
    label = str(item).strip()
    if not label:
        return None
    return {"label": label[:100], "description": "", "dimension": "", "evidence": "", "layer": layer}


def parse_layered_result(data: dict) -> dict:
    """解析四层输出（R-182）；模型若仍按扁平 tags/redlines 返回，则按维度粗分层兜底。

    返回 {"tags":[{label,description,dimension,evidence,layer}], "redlines":[...]}。
    """
    result: dict = {"tags": [], "redlines": []}
    for layer in (CORE_DNA, STANCE, MODE):
        for item in data.get(layer) or []:
            tag = _tag_item(item, layer)
            if tag:
                result["tags"].append(tag)
    # 兼容模型忽略分层、仍用扁平 tags 的情况
    if not result["tags"]:
        for item in data.get("tags") or []:
            if isinstance(item, dict):
                dim = str(item.get("dimension", "")).strip()[:30]
                tag = _tag_item(item, _default_layer(dim))
                if tag:
                    tag["dimension"] = dim
                    result["tags"].append(tag)
            else:
                tag = _tag_item(item, STANCE)
                if tag:
                    result["tags"].append(tag)
    for redline in data.get("forbidden") or data.get("redlines") or []:
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
    """把 incoming 的信息并入 cur：保留更完整的描述/证据，补齐空维度/分层。"""
    if len(incoming.get("description", "")) > len(cur.get("description", "")):
        cur["description"] = incoming["description"]
    if len(incoming.get("evidence", "")) > len(cur.get("evidence", "")):
        cur["evidence"] = incoming["evidence"]
    if not cur.get("dimension") and incoming.get("dimension"):
        cur["dimension"] = incoming["dimension"]
    if not cur.get("layer") and incoming.get("layer"):
        cur["layer"] = incoming["layer"]


def dedupe_profile(profile: dict) -> dict:
    """机械近义去重（不花 LLM）：标签/红线各自按 label_match 归并，保留更完整的描述。"""
    tags: list[dict] = []
    for item in (profile or {}).get("tags") or []:
        label = str(item.get("label", "")).strip() if isinstance(item, dict) else str(item).strip()
        if not label:
            continue
        dimension = str(item.get("dimension", "")).strip()[:30] if isinstance(item, dict) else ""
        incoming = {
            "label": label[:100],
            "description": str(item.get("description", "")).strip() if isinstance(item, dict) else "",
            "dimension": dimension,
            "evidence": str(item.get("evidence", "")).strip()[:_MAX_EVIDENCE] if isinstance(item, dict) else "",
            "layer": (str(item.get("layer", "")).strip() if isinstance(item, dict) else "") or _default_layer(dimension),
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
            if isinstance(item, dict):
                tags.append({**item, "layer": item.get("layer") or _default_layer(str(item.get("dimension", "")))})
            else:
                tags.append({"label": str(item), "layer": STANCE})
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
        """按功能取主用槽位 + 另一槽位兜底的客户端（注入的 llm 优先）。

        R-232：主用槽位走功能路由（app_kv 可选模型1/模型2；人设 4 引擎同属
        persona 组，一处下拉全部生效），默认 model1。
        """
        if self._injected is not None:
            return self._injected
        primary = llm_router.model_settings.feature_route(self._db, feature)
        fallback = "model2" if primary == "model1" else "model1"
        client = llm_router.RoutedLLM(feature, self._route(), primary=primary, fallback=fallback)
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

    def _llm_merge(self, key: str, parts: list[dict], parser=parse_persona_result) -> dict[str, Any] | None:
        """调 LLM 做归纳合并；失败/空结果返回 None（由调用方决定降级策略）。

        R-182：`parser` 决定解析口径——人设归纳用 `parse_layered_result`（四层）。
        """
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
        result = parser(data)
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
            merged = self._llm_merge("persona_merge", clean, parser=parse_layered_result)
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
                merged_parts.append(self._llm_merge("persona_merge", [chunk], parser=parse_layered_result) or chunk)
            reduced = collect_profile(merged_parts)
            if _profile_size(reduced) >= _profile_size(profile):
                break
            profile = reduced
        final = self._llm_merge("persona_merge", [profile], parser=parse_layered_result)
        return dedupe_profile(final) if final is not None else profile

    def merge_incremental(self, current: dict, new_part: dict) -> dict:
        """增量合并：把新文案信号并入当前档案，产出更新后的完整档案（R-128/R-182 四层）。"""
        parts = [current or empty_profile(), new_part or empty_profile()]
        merged = self._llm_merge("persona_updates", parts, parser=parse_layered_result)
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
