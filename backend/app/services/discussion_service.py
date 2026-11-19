"""洗稿与历史原文讨论的共享留痕（R-263）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models.discussion import DraftDiscussion


def model_label(vendor: str, model_id: str) -> str:
    from .model_settings import VENDORS

    label = (VENDORS.get(vendor or "") or {}).get("label") or ""
    if label and model_id:
        return f"{label} · {model_id}"
    return label or model_id or ""


def llm_model_fields(llm: Any) -> dict[str, str]:
    if llm is None:
        return {"used_slot": "", "vendor": "", "model_id": ""}
    return {
        "used_slot": str(getattr(llm, "used_slot", "") or ""),
        "vendor": str(getattr(llm, "used_vendor", "") or ""),
        "model_id": str(getattr(llm, "used_model", "") or ""),
    }


def add_discussion(
    db: Session,
    draft_id: int,
    round_no: int,
    actor: str,
    kind: str,
    content: str,
    *,
    llm: Any = None,
) -> None:
    db.add(
        DraftDiscussion(
            draft_id=draft_id,
            round=round_no,
            actor=actor,
            kind=kind,
            content=content,
            **llm_model_fields(llm),
        )
    )
    db.commit()


def add_note(db: Session, draft_id: int, round_no: int, text: str) -> None:
    add_discussion(db, draft_id, round_no, "system", "note", text)


def slot_meta(slot: dict) -> dict:
    vendor = str(slot.get("vendor") or "")
    model_id = str(slot.get("model") or "")
    return {
        "slot": str(slot.get("slot") or ""),
        "vendor": vendor,
        "model": model_id,
        "label": model_label(vendor, model_id),
    }


def start_run_header(db: Session, draft_id: int, gen_slot: dict, critic_slot: dict, rounds: int) -> int:
    row = DraftDiscussion(
        draft_id=draft_id,
        round=0,
        actor="system",
        kind="run",
        content=json.dumps(
            {
                "gen": slot_meta(gen_slot),
                "critic": slot_meta(critic_slot),
                "rounds": rounds,
                "rounds_done": None,
                "degraded": None,
            },
            ensure_ascii=False,
        ),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return int(row.id)


def finish_run_header(db: Session, header_id: int, *, rounds_done: int, degraded: bool) -> None:
    row = db.get(DraftDiscussion, header_id)
    if row is None:
        return
    try:
        payload = json.loads(row.content or "{}")
    except json.JSONDecodeError:
        payload = {}
    payload["rounds_done"] = rounds_done
    payload["degraded"] = bool(degraded)
    row.content = json.dumps(payload, ensure_ascii=False)
    db.commit()


def mark_latest_run_reverted(db: Session, draft_id: int) -> bool:
    row = (
        db.query(DraftDiscussion)
        .filter(DraftDiscussion.draft_id == draft_id, DraftDiscussion.kind == "run")
        .order_by(DraftDiscussion.id.desc())
        .first()
    )
    if row is None:
        return False
    try:
        payload = json.loads(row.content or "{}")
    except json.JSONDecodeError:
        payload = {}
    if payload.get("reverted"):
        return False
    payload["reverted"] = True
    row.content = json.dumps(payload, ensure_ascii=False)
    db.commit()
    return True


__all__ = [
    "add_discussion",
    "add_note",
    "finish_run_header",
    "mark_latest_run_reverted",
    "model_label",
    "slot_meta",
    "start_run_header",
]
