"""R-227 第 2 步：站内真实素材检索。

- **事例层（作者）**：主博主已发布视频的 ASR 转写稿（`corrected_text` 优先）+ 脚本工作台里
  **作者侧**「完成」稿（`AUTHOR_SOURCES`，无 AI 版本才算作者侧）。
- **参考层（对标）**：对标博主的视频转写稿——只作创作参考，**明确标注非本人经历**；
  不进入人设学习/提示词优化（守 D-028）。
- 排除广告视频与空转写；按**选题相关度**取（关键词 bigram 重叠，不做表现加权）；片段级（≤400 字）。
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from ..models.draft import Draft
from ..models.platform import Creator
from ..models.video import Video
from .creator_service import current_creator_id
from .draft_versions import AUTHOR_SOURCES, chains_with_sources

_SPLIT_RE = re.compile(r"[\s，。！？!?,.;:：、|\[\]()（）《》“”\"'…\-—#＃]+")
_SEG_RE = re.compile(r"[^\n。！？!?]+[。！？!?]?")
_MAX_SLICE = 400


def _grams(text: str) -> set[str]:
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


def _score(topic_grams: set[str], text: str) -> int:
    return len(topic_grams & _grams(text))


def _segments(text: str) -> list[str]:
    """把长文切成句/段级片段（≤400 字），按相关度挑用。"""
    out: list[str] = []
    buf = ""
    for seg in _SEG_RE.findall(text or ""):
        seg = seg.strip()
        if not seg:
            continue
        if len(buf) + len(seg) > _MAX_SLICE and buf:
            out.append(buf)
            buf = seg
        else:
            buf += seg
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if s]


def _json_platforms(raw) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(x) for x in data if x] if isinstance(data, list) else []


def _author_segments(db: Session, cid: int | None, topic_grams: set[str], limit: int) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    # 1) 主博主已发布视频的 ASR 转写（corrected 优先）
    q = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        q = q.filter(Video.creator_id == cid)
    for v in q.order_by(Video.id.desc()).limit(300).all():
        tr = v.transcript
        if tr is None:
            continue
        text = (tr.corrected_text or tr.transcript_text or "").strip()
        if not text:
            continue
        title = (v.title or v.filename or "").strip()
        plats = _json_platforms(v.platforms)
        for seg in _segments(text):
            if seg in seen:
                continue
            seen.add(seg)
            items.append(
                {
                    "kind": "asr",
                    "title": title,
                    "platform": plats[0] if plats else "",
                    "text": seg,
                    "score": _score(topic_grams, seg),
                }
            )
    # 2) 脚本工作台「完成」的作者侧稿
    done = db.query(Draft).filter(Draft.status == "done", Draft.script != "")
    if cid:
        done = done.filter(Draft.creator_id == cid)
    drafts = done.order_by(Draft.id.desc()).limit(200).all()
    chains = chains_with_sources(db, drafts)
    for d in drafts:
        author_side = d.source == "manual" or any(
            src in AUTHOR_SOURCES for src, _t in (chains.get(d.id) or [])
        )
        if not author_side:
            continue
        text = (d.script or "").strip()
        if not text:
            continue
        for seg in _segments(text):
            if seg in seen:
                continue
            seen.add(seg)
            items.append(
                {
                    "kind": "draft",
                    "title": (d.title or "").strip(),
                    "platform": "",
                    "text": seg,
                    "score": _score(topic_grams, seg),
                }
            )
    items.sort(key=lambda x: x["score"], reverse=True)
    return [it for it in items if it["score"] > 0][:limit]


def _benchmark_segments(db: Session, cid: int | None, topic_grams: set[str], limit: int) -> list[dict]:
    if not cid:
        return []
    bm_creators = (
        db.query(Creator).filter(Creator.kind == "benchmark", Creator.parent_id == cid).all()
    )
    if not bm_creators:
        return []
    names = {c.id: c.name for c in bm_creators}
    items: list[dict] = []
    seen: set[str] = set()
    q = db.query(Video).filter(Video.is_ad.is_(False), Video.creator_id.in_(list(names.keys())))
    for v in q.order_by(Video.id.desc()).limit(300).all():
        tr = v.transcript
        if tr is None:
            continue
        text = (tr.corrected_text or tr.transcript_text or "").strip()
        if not text:
            continue
        title = (v.title or v.filename or "").strip()
        for seg in _segments(text):
            if seg in seen:
                continue
            seen.add(seg)
            items.append(
                {
                    "kind": "benchmark",
                    "title": title,
                    "blogger": names.get(v.creator_id or 0, ""),
                    "text": seg,
                    "score": _score(topic_grams, seg),
                }
            )
    items.sort(key=lambda x: x["score"], reverse=True)
    return [it for it in items if it["score"] > 0][:limit]


def retrieve_station(
    db: Session,
    topic: str,
    *,
    creator_id: int | None = None,
    author_k: int = 4,
    bench_k: int = 3,
) -> dict:
    """检索站内真实素材（作者事例 + 对标参考），返回 `{author, benchmark, block}`。"""
    cid = creator_id or current_creator_id(db)
    topic_grams = _grams(topic or "")
    if not topic_grams:
        return {"author": [], "benchmark": [], "block": ""}
    author = _author_segments(db, cid, topic_grams, author_k)
    bench = _benchmark_segments(db, cid, topic_grams, bench_k)
    return {"author": author, "benchmark": bench, "block": build_block(author, bench)}


def build_block(author: list[dict], benchmark: list[dict]) -> str:
    if not author and not benchmark:
        return ""
    lines = ["【站内真实素材·优先用「你的」；只提炼观点与事实，不要照抄语气】"]
    asr = [a for a in author if a["kind"] == "asr"]
    drafts = [a for a in author if a["kind"] == "draft"]
    if asr:
        lines.append("你的真实经历/说法（来自你发过的口播）：")
        for i, a in enumerate(asr, 1):
            tag = f"（{a['platform']}）" if a.get("platform") else ""
            lines.append(f"[你{i}]《{a['title'] or '无标题'}》{tag}：{a['text']}")
    if drafts:
        lines.append("你的定稿（脚本工作台·完成）：")
        for i, d in enumerate(drafts, 1):
            lines.append(f"[稿{i}]《{d['title'] or '无标题'}》：{d['text']}")
    if benchmark:
        lines.append("对标博主内容（他人，仅作参考，**禁止写成你的经历**）：")
        for i, b in enumerate(benchmark, 1):
            who = f"（{b['blogger']}）" if b.get("blogger") else ""
            lines.append(f"[对标{i}]《{b['title'] or '无标题'}》{who}：{b['text']}")
    return "\n".join(lines)


def meta(station: dict) -> dict:
    """给 `Draft.quality` 存的可展示元数据（不含长文本）。"""
    def _m(items: list[dict]) -> list[dict]:
        return [
            {k: it.get(k) for k in ("kind", "title", "platform", "blogger") if it.get(k)}
            for it in items
        ]

    return {"author": _m(station.get("author") or []), "benchmark": _m(station.get("benchmark") or [])}
