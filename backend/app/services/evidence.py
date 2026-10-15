"""R-227：生成/洗稿的「可用真实素材」证据层。

第 1 步先接**联网事实**（豆包搜索）；第 2 步会在此叠加站内素材（作者 ASR 转写 + 作者侧定稿 + 对标参考）。
- `gather_online()`：按选题联网检索事实，写 `web_search_logs` 留痕，返回可注入 prompt 的清单与结构化来源。
- 无 key / 失败 → 返回空来源，生成照常（不阻断）。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.log import get_logger
from ..models.web_search import WebSearchLog
from . import web_search

log = get_logger("evidence")

_MAX_QUERY = 100  # 豆包搜索建议 query 1~100 字


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
    draft_id: int | None = None,
    creator_id: int | None = None,
    count: int | None = None,
    time_range: str = "",
) -> dict:
    """联网检索选题相关事实。

    返回 `{"sources": [...], "queries": [...], "block": str}`；无 key/失败时 sources 为空、block 为空串。
    """
    query = (topic or "").strip()[:_MAX_QUERY]
    if not query or not web_search.enabled():
        return {"sources": [], "queries": [], "block": ""}
    settings = get_settings()
    want = int(count or settings.web_search_count or 5)
    sources = web_search.search(query, count=want, time_range=time_range)
    queries = [{"query": query, "count": want, "time_range": time_range}] if sources else []
    if sources:
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
