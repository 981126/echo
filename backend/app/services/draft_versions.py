"""草稿版本留痕（R-156）：定稿快照、版本列表、版本链（供 AI 学习）。

版本链 = 同一草稿历次定稿的正文序列（按时间正序，≥2 条才算）；
没有任何版本时退回「原文案 → 当前正文」（兼容 R-117/R-131 的老行为）。

R-209：版本 ``source`` 分两侧，消费者必须按 source 归因（不能把 AI 的改动当成作者偏好）：
- **作者侧** ``AUTHOR_SOURCES`` = {manual, rollback}（作者定稿 / 作者回退旧版）；
- **AI 侧** ``AI_SOURCES`` = {ai_generate, ai_discuss, ai_rewrite}。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models.draft import Draft
from ..models.draft_version import DraftVersion

# R-209：版本来源两侧划分（改稿差异分析/改稿样本/回退检测都以此归因为准）
AUTHOR_SOURCES = {"manual", "rollback"}
AI_SOURCES = {"ai_generate", "ai_discuss", "ai_rewrite"}


def snapshot_version(
    db: Session,
    draft: Draft,
    source: str = "manual",
    note: str = "",
    content: dict | None = None,
) -> DraftVersion:
    """把草稿当前内容（或用 `content` 覆盖的指定内容）存成一条版本。

    content 可覆盖 title/cover_text/script/tags——用于「洗稿前 ASR」这类
    不是草稿当时状态的快照（R-157）。
    """
    data = {
        "title": draft.title or "",
        "cover_text": draft.cover_text or "",
        "script": draft.script or "",
        "tags": draft.tags or "[]",
    }
    for key in ("title", "cover_text", "script", "tags"):
        if content and key in content and content[key] is not None:
            data[key] = content[key]
    v = DraftVersion(draft_id=draft.id, source=source, note=note, **data)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def finalize_version(
    db: Session,
    draft: Draft,
    source: str = "manual",
    note: str = "",
    content: dict | None = None,
) -> DraftVersion:
    """留一版 + 版本数 ≥2 时触发改稿差异分析（R-157：避免首版空跑）。"""
    v = snapshot_version(db, draft, source=source, note=note, content=content)
    from .diff_analysis import maybe_start_diff_analysis

    maybe_start_diff_analysis(db, draft)
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


def chains_with_sources(db: Session, drafts: list[Draft]) -> dict[int, list[tuple[str, str]]]:
    """R-209：批量取「带 source 的版本链」——``[(source, script)]``，只有真实版本（无 fallback）。

    消费者据此区分「这一版是谁改的」；不足 2 版时不返回（与 chains_for_drafts 的 ≥2 口径一致）。
    """
    ids = [d.id for d in drafts if d.id]
    grouped: dict[int, list[tuple[str, str]]] = {}
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
                grouped.setdefault(r.draft_id, []).append((r.source or "manual", text))
    return {d.id: grouped[d.id] for d in drafts if len(grouped.get(d.id) or []) >= 2}


def pure_manual_map(db: Session, drafts: list[Draft]) -> dict[int, bool]:
    """R-210：「纯手写」判定——AI 从未参与（source=manual 且无讨论记录且无 AI 侧版本）。

    讨论过即使内容已全部回退也不算纯手写（回退行为本身已是 R-209 的学习信号）。
    """
    ids = [d.id for d in drafts if d.id]
    if not ids:
        return {}
    from ..models.discussion import DraftDiscussion

    discussed = {
        r[0]
        for r in db.query(DraftDiscussion.draft_id)
        .filter(DraftDiscussion.draft_id.in_(ids))
        .distinct()
        .all()
    }
    ai_versioned = {
        r[0]
        for r in db.query(DraftVersion.draft_id)
        .filter(DraftVersion.draft_id.in_(ids), DraftVersion.source.in_(sorted(AI_SOURCES)))
        .distinct()
        .all()
    }
    return {
        d.id: bool(d.source == "manual" and d.id not in discussed and d.id not in ai_versioned)
        for d in drafts
    }


def is_pure_manual(db: Session, draft: Draft) -> bool:
    """单个草稿的纯手写判定（R-210）。"""
    return pure_manual_map(db, [draft]).get(draft.id, False)


def latest_comment_map(db: Session, draft_ids: list[int]) -> dict[int, str]:
    """每篇草稿最新一条非空评价文本（R-211「记反馈」），供列表预填/学习上下文引用。"""
    ids = [int(i) for i in draft_ids if i]
    if not ids:
        return {}
    from ..models.feedback import Feedback

    rows = (
        db.query(Feedback.draft_id, Feedback.comment)
        .filter(Feedback.draft_id.in_(ids), Feedback.comment != "")
        .order_by(Feedback.id.desc())
        .all()
    )
    out: dict[int, str] = {}
    for draft_id, comment in rows:
        if draft_id not in out:
            out[draft_id] = (comment or "").strip()
    return out


def version_stages(db: Session, draft: Draft) -> list[str]:
    """单个草稿的版本链（供改稿差异分析用）。"""
    return chains_for_drafts(db, [draft]).get(draft.id, [])
