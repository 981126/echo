"""人设档案接口契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PersonaTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    description: str = ""
    dimension: str = ""
    category: str = "style"
    source: str = "ai"
    status: str = "suggested"
    version: int = 1
    created_at: datetime


class PersonaTagCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    description: str = ""
    dimension: str = ""
    category: str = "style"  # style | topic | redline | phrase
    source: str = "manual"


class PersonaDecision(BaseModel):
    status: str = Field(pattern="^(confirmed|rejected)$")


class PersonaTagUpdate(BaseModel):
    label: str = Field(default="", min_length=1, max_length=100)
    description: str = ""
    dimension: str = ""
    category: str = Field(default="style", pattern="^(style|topic|redline|phrase)$")


class PersonaCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str = "increment"
    source_count: int = 0
    coverage: float = 0.0
    semantic: float | None = None
    passed: bool = True
    fallback: bool = False
    detail: str = "{}"
    created_at: datetime
