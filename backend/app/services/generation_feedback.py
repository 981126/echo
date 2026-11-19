"""作者改稿、状态与发布反馈学习（R-263）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models.author_generation import AuthorAsset, GenerationRun
from ..models.draft import Draft
from ..models.draft_version import DraftVersion
from . import llm_router
from .author_assets import upsert_asset
from .generation_validators import json_dict
from .prompt_service import get_prompt

AUTHOR_EDIT_LEARN_SYSTEM = """你在学习作者真实的改稿与反馈，不是在创作，也不能修改人设档案。
只从作者最终稿与亲笔评价中提取可复用的事实、观点、经历、结构或表达；负面反馈只说明应避免什么，不能反推作者稳定事实。
每条资产必须附最终稿中逐字连续的 quote；没有可靠内容就返回空数组。
只输出 JSON：{"assets":[{"asset_kind":"fact|viewpoint|experience|structure|expression","content":"一条资产",
"context":{"conditions":"适用条件","signal":"完成|不采用|评价|回退"},"quote":"最终稿原文片段"}]}。
不得补充原文没有的数字、身份、结果或因果。"""


def _latest_version(db: Session, draft_id: int) -> DraftVersion | None:
    return (
        db.query(DraftVersion)
        .filter(DraftVersion.draft_id == draft_id)
        .order_by(DraftVersion.id.desc())
        .first()
    )


def mark_assets_feedback(db: Session, draft: Draft, outcome: str | None) -> int:
    run = (
        db.query(GenerationRun)
        .filter(GenerationRun.draft_id == draft.id)
        .order_by(GenerationRun.id.desc())
        .first()
    )
    if run is None:
        return 0
    evidence = json_dict(run.evidence_json)
    ids = [int(item.get("id")) for item in evidence.get("author_assets") or [] if item.get("id")]
    rows = db.query(AuthorAsset).filter(AuthorAsset.id.in_(ids)).all() if ids else []
    for asset in rows:
        stats = json_dict(asset.usage_stats)
        if outcome:
            stats[outcome] = int(stats.get(outcome) or 0) + 1
        performance = json_dict(draft.performance).get("totals")
        if isinstance(performance, dict):
            stats["performance"] = sum(
                int(performance.get(key) or 0) * weight
                for key, weight in (("plays", 1), ("likes", 5), ("favorites", 3), ("comments", 10))
            )
        asset.usage_stats = json.dumps(stats, ensure_ascii=False)
    db.commit()
    return len(rows)


def learn_from_draft(db: Session, draft: Draft, *, comment: str = "") -> dict[str, int]:
    final = (draft.script or "").strip()
    if not final or draft.creator_id is None:
        return {"created": 0, "rejected": 0, "skipped": 1}
    if draft.status in {"archived", "deleted"}:
        mark_assets_feedback(db, draft, "rejected")
        if not comment.strip():
            return {"created": 0, "rejected": 0, "skipped": 1}
    elif draft.status == "done":
        mark_assets_feedback(db, draft, "completed")
    original = (draft.original_script or "").strip()
    if not comment.strip() and (not original or original == final):
        return {"created": 0, "rejected": 0, "skipped": 1}
    version = _latest_version(db, draft.id)
    client = llm_router.primary_llm(db, "feedback_analysis")
    data = client.chat_json(
        [
            {"role": "system", "content": get_prompt("author_edit_learn", db)},
            {
                "role": "user",
                "content": (
                    f"状态：{draft.status}\nAI/上一版：\n{original}\n\n作者最终稿：\n{final}\n\n"
                    f"作者亲笔评价：{comment or '无'}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=4000,
        require=("assets",),
    )
    stats = {"created": 0, "rejected": 0, "skipped": 0}
    for item in data.get("assets") or []:
        if not isinstance(item, dict):
            stats["rejected"] += 1
            continue
        kind = str(item.get("asset_kind") or "")
        content = str(item.get("content") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if kind not in {"fact", "viewpoint", "experience", "structure", "expression"} or not content or quote not in final:
            stats["rejected"] += 1
            continue
        raw_context = item.get("context")
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        upsert_asset(
            db,
            creator_id=draft.creator_id,
            asset_kind=kind,
            source_kind="draft_edit" if draft.status == "done" else "feedback",
            source_id=f"draft:{draft.id}",
            content=content,
            context=context,
            evidence_refs=[{"draft_id": draft.id, "version_id": version.id if version else None, "quote": quote}],
            status="active" if draft.status == "done" else "candidate",
            quality_score=0.9 if draft.status == "done" else 0.4,
        )
        stats["created"] += 1
    db.commit()
    return stats


def generation_feedback_task(db: Session, payload: dict[str, Any]) -> dict[str, int]:
    draft = db.get(Draft, int(payload.get("draft_id") or 0))
    if draft is None:
        raise ValueError("草稿不存在")
    return learn_from_draft(db, draft, comment=str(payload.get("comment") or ""))


__all__ = ["AUTHOR_EDIT_LEARN_SYSTEM", "generation_feedback_task", "learn_from_draft", "mark_assets_feedback"]
