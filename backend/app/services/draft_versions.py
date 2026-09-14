"""草稿版本留痕（R-156）：定稿快照、版本列表、版本链（供 AI 学习）。

版本链 = 同一草稿历次定稿的正文序列（按时间正序，≥2 条才算）；
没有任何版本时退回「原文案 → 当前正文」（兼容 R-117/R-131 的老行为）。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models.draft import Draft
from ..models.draft_version import DraftVersion


def snapshot_version(db: Session, draft: Draft, source: str = "manual", note: str = "") -> DraftVersion:
    """把草稿当前内容存成一条版本（正文 + 标题 + 封面字 + 标签）。"""
    v = DraftVersion(
        draft_id=draft.id,
        title=draft.title or "",
        cover_text=draft.cover_text or "",
        script=draft.script or "",
        tags=draft.tags or "[]",
        source=source,
        note=note,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def list_versions(db: Session, draft_id: int) -> list[DraftVersion]:
    """按时间正序返回版本（前端再自行倒序展示）。"""
    return (
        db.query(DraftVersion)
        .filter(DraftVersion.draft_id == draft_id)
        .order_by(DraftVersion.id)
        .all()
    )


def version_payload(v: DraftVersion) -> dict:
    try:
        tags = json.loads(v.tags or "[]")
    except (TypeError, ValueError):
        tags = []
    return {
        "id": v.id,
        "draft_id": v.draft_id,
        "title": v.title or "",
        "cover_text": v.cover_text or "",
        "script": v.script or "",
        "tags": tags if isinstance(tags, list) else [],
        "source": v.source or "manual",
        "note": v.note or "",
        "created_at": v.created_at.isoformat() if v.created_at else "",
    }


def chains_for_drafts(db: Session, drafts: list[Draft]) -> dict[int, list[str]]:
    """批量取「版本链」：≥2 条版本用版本正文；否则退回 original_script → script。"""
    ids = [d.id for d in drafts if d.id]
    grouped: dict[int, list[str]] = {}
    if ids:
        rows = (
            db.query(DraftVersion)
            .filter(DraftVersion.draft_id.in_(ids))
            .order_by(DraftVersion.id)
            .all()
        )
        for r in rows:
            text = (r.script or "").strip()
            if text:
                grouped.setdefault(r.draft_id, []).append(text)
    out: dict[int, list[str]] = {}
    for d in drafts:
        chain = grouped.get(d.id) or []
        if len(chain) >= 2:
            out[d.id] = chain
            continue
        original = (d.original_script or "").strip()
        current = (d.script or "").strip()
        out[d.id] = [original, current] if original and current else []
    return out


def version_stages(db: Session, draft: Draft) -> list[str]:
    """单个草稿的版本链（供改稿差异分析用）。"""
    return chains_for_drafts(db, [draft]).get(draft.id, [])
