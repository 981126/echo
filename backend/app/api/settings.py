"""生成设置（R-023）：主力/生成模型策略 deepseek | kimi | random | alternate。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models.kv import Kv

router = APIRouter()

MODES = ["deepseek", "kimi", "random", "alternate"]


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(deepseek|kimi|random|alternate)$")


class RoundsIn(BaseModel):
    rounds: int = Field(default=5, ge=1, le=10)


@router.get("/asr", response_model=dict)
def get_asr_config():
    """当前 ASR 服务商与模型（供前端展示真实来源，R-112）。"""
    st = get_settings()
    return {"mode": st.asr_mode, "model": st.siliconflow_asr_model}


@router.get("/generation-model", response_model=dict)
def get_mode(db: Session = Depends(get_db)):
    row = db.get(Kv, "generation_model")
    mode = (row.value if row else "") or get_settings().generation_model
    return {"mode": mode, "modes": MODES}


@router.put("/generation-model", response_model=dict)
def set_mode(payload: ModeIn, db: Session = Depends(get_db)):
    row = db.get(Kv, "generation_model")
    if row is None:
        row = Kv(key="generation_model", value=payload.mode)
        db.add(row)
    else:
        row.value = payload.mode
    db.commit()
    return {"mode": payload.mode}


@router.get("/debate-rounds", response_model=dict)
def get_rounds(db: Session = Depends(get_db)):
    row = db.get(Kv, "debate_rounds")
    rounds = int(row.value) if row and str(row.value).isdigit() else int(
        get_settings().debate_rounds or 5
    )
    return {"rounds": max(1, min(rounds, 10)), "min": 1, "max": 10}


@router.put("/debate-rounds", response_model=dict)
def set_rounds(payload: RoundsIn, db: Session = Depends(get_db)):
    row = db.get(Kv, "debate_rounds")
    if row is None:
        row = Kv(key="debate_rounds", value=str(payload.rounds))
        db.add(row)
    else:
        row.value = str(payload.rounds)
    db.commit()
    return {"rounds": payload.rounds}
