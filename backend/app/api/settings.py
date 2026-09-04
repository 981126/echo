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
