"""灵感池相关度（R-072）：组装“当前人设关键词 + 红线词”，给热榜/评论打分标注。"""

from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from ..core.ideas import score_title, topic_expansion, words_of

_TAG_RE = re.compile(r"[#＃]([^\s#＃，。！？!?、]+)")


def persona_profile(db: Session) -> dict:
    """基于当前主博主组装相关度画像：keywords（命中=相关）、avoid（命中=红线剔除）。"""
    from ..models.persona import PersonaTag
    from ..models.video import Video
    from .creator_service import current_creator_id

    keywords: list[str] = []
    avoid: list[str] = []
    cid = current_creator_id(db)
    if cid:
        tags = (
            db.query(PersonaTag)
            .filter(PersonaTag.creator_id == cid, PersonaTag.status == "confirmed")
            .all()
        )
        for t in tags:
            text = f"{t.label or ''} {t.description or ''}".strip()
            if not text:
                continue
            layer = getattr(t, "layer", "") or ""
            if t.category == "redline" or layer == "forbidden":
                avoid.extend(words_of(text))
            elif layer == "stance" or t.category == "topic":
                # R-196：内容立场（stance）全文提词参与相关度；赛道词同样计入
                keywords.extend(words_of(text))

        videos = (
            db.query(Video)
            .filter(Video.creator_id == cid, Video.is_ad.is_(False), Video.status == "published")
            .all()
        )
        videos.sort(key=lambda v: (v.published_at or v.planned_publish_at or v.created_at or datetime.min), reverse=True)
        videos = videos[:30]
        topics: set[str] = set()
        hashtags: list[str] = []
        for v in videos:
            try:
                m = json.loads(v.main_topics or "[]") if isinstance(v.main_topics, str) else (v.main_topics or [])
                topics.update(x for x in m if x)
            except json.JSONDecodeError:
                pass
            for m in _TAG_RE.findall(v.title or ""):
                tag = m.strip().replace("[话题]", "").replace("]", "").strip()
                if tag:
                    hashtags.append(tag)
        keywords.extend(topic_expansion(topics))
        keywords.extend(w for w in hashtags if len(w) <= 12)

    def _uniq(items: list[str]) -> list[str]:
        out: list[str] = []
        for k in items:
            k = (k or "").strip().lower()
            if k and k not in out:
                out.append(k)
        return out

    return {"keywords": _uniq(keywords), "avoid": _uniq(avoid), "active": bool(keywords)}


def annotate_items(db: Session, items: list[dict], profile: dict | None = None) -> list[dict]:
    """给每条 {title:…} 打分：score 相关词命中数；matched=是否相关；
    redlined=命中红线（调用方决定是否剔除）；无人设时全部 matched（中性不误标）。"""
    p = profile or persona_profile(db)
    out: list[dict] = []
    for it in items or []:
        title = it.get("title") or ""
        sc = score_title(title, keywords=p["keywords"], avoid=p["avoid"])
        out.append(
            {
                **it,
                "score": max(0, sc),
                "matched": (not p["active"]) or sc > 0,
                "redlined": sc < 0,
            }
        )
    return out
