"""需求管理接口契约。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementOut(BaseModel):
    id: str  # R-001
    title: str
    status: str
    summary: str = ""
    path: str = ""


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = ""


class RequirementUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=20)
