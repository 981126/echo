"""R-227：生成/洗稿的「可用真实素材」证据层。

第 1 步先接**联网事实**（豆包搜索）；第 2 步会在此叠加站内素材（作者 ASR 转写 + 作者侧定稿 + 对标参考）。
- `build_search_query()`：把选题 + 该入口能拿到的最具体文本拼成搜索词（≤100 字）。
- `filter_relevant()`：按关键词（含中文 bigram）重叠度过滤不相关结果。
- `gather_online()`：联网检索 + 写 `web_search_logs` 留痕（query 原样记录）+ 返回可注入 prompt 的清单。
- 无 key / 失败 → 返回空来源，生成照常（不阻断）。
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.log import get_logger
from ..models.web_search import WebSearchLog
from . import web_search

log = get_logger("evidence")

_MAX_QUERY = 100  # 豆包搜索建议 query 1~100 字
_SPLIT_RE = re.compile(r"[\s，。！？!?,.;:：、|\[\]()（）《》“”\"'…\-—#＃]+")


def build_search_query(topic: str, material: str = "") -> str:
    """构造搜索词：选题 + 该入口能拿到的最具体文本（截断到 100 字）。"""
    topic = (topic or "").strip()
    material = re.sub(r"\s+", " ", (material or "").strip())
    if not material:
        return topic[:_MAX_QUERY].strip()
    room = max(0, _MAX_QUERY - len(topic) - 1)
    return f"{topic} {material[:room]}".strip()


def _grams(text: str) -> set[str]:
    """粗分词：按标点切词，词长>2 时取相邻双字 bigram（对中文友好，零依赖）。"""
    out: set[str] = set()
    for w in _SPLIT_RE.split(text or ""):
        w = w.strip()
        if not w:
            continue
        if len(w) <= 2:
            out.add(w)
        else:
            out.update(w[i : i + 2] for i in range(len(w) - 1))
    return out


def filter_relevant(query: str, sources: list[dict], min_score: int | None = None) -> list[dict]:
    """过滤不相关结果：关键词重叠度低于阈值即丢弃；全不相关返回 []（不硬塞）。

    阈值默认 1（query 很短时）/ 2（较长时）。results 保留原顺序。
    """
    if not sources:
        return []
    q = _grams(query)
    if not q:
        return sources
    thr = min_score if min_score is not None else (1 if len(q) <= 6 else 2)
    out: list[dict] = []
    for s in sources:
        score = len(q & _grams(f"{s.get('title') or ''} {s.get('summary') or ''}"))
        if score >= thr:
            out.append(s)
    return out


def _build_block(sources: list[dict]) -> str:
    lines = [
        "【联网事实素材·仅供引用，必须口语化转述（不要念 URL），不得编造；"
        "不确定的数据不要写成断言，没有把握就讲观点、别硬编】"
    ]
    for i, s in enumerate(sources, 1):
        head = s.get("title") or s.get("site") or ""
        tail = " ".join(x for x in (s.get("site"), s.get("url")) if x)
        lines.append(f"[{i}] {head}" + (f"（{tail}）" if tail else ""))
        summary = (s.get("summary") or "").strip()
        if summary:
            lines.append(f"    {summary[:240]}")
    return "\n".join(lines)


def gather_online(
    db: Session,
    topic: str,
    *,
    material: str = "",
    draft_id: int | None = None,
    creator_id: int | None = None,
    count: int | None = None,
    time_range: str = "",
) -> dict:
    """联网检索选题相关事实（query = 选题 + material）。

    返回 `{"sources": [...], "queries": [...], "block": str}`；无 key 时全空。
    只要发起了搜索（有 query + 有 key）就写 `web_search_logs` 留痕并返回 queries（即使 0 结果）。
    """
    query = build_search_query(topic, material)
    if not query or not web_search.enabled():
        return {"sources": [], "queries": [], "block": ""}
    settings = get_settings()
    want = int(count or settings.web_search_count or 5)
    raw = web_search.search(query, count=want, time_range=time_range, query_rewrite=True)
    sources = filter_relevant(query, raw)
    queries = [{"query": query, "count": want, "time_range": time_range, "raw_count": len(raw)}]
    db.add(
        WebSearchLog(
            draft_id=draft_id,
            creator_id=creator_id,
            query=query,
            time_range=time_range or "",
            results=json.dumps(sources, ensure_ascii=False),
        )
    )
    try:
        db.commit()
    except Exception:  # noqa: BLE001 留痕失败不影响生成
        db.rollback()
        log.exception("联网搜索留痕写入失败")
    return {"sources": sources, "queries": queries, "block": _build_block(sources) if sources else ""}


def resolve_used(sources: list[dict], used_indices) -> list[dict]:
    """把模型声明的引用编号（[1,3]）解析为真实来源，过滤越界编号（防编造来源）。"""
    out: list[dict] = []
    for raw in used_indices or []:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(sources):
            src = sources[idx - 1]
            if src not in out:
                out.append(src)
    return out
