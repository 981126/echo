from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeIn(BaseModel):
    post_id: int
    refresh: bool = False
    force: bool = False


class ReferenceRefreshIn(BaseModel):
    category_id: str = "0"
    keyword: str = ""
    date_window: int = 168
    duration_type: int = 0
    tags: list[dict] = Field(default_factory=list)
    limit: int = 20


class CredentialIn(BaseModel):
    account_id: int
    cookie: str = Field(min_length=1, max_length=30000)


class PlanIn(BaseModel):
    kept_text: str = ""
    changes: list[str] = Field(default_factory=list)
    target_metrics: list[str] = Field(default_factory=list)


class PlanPatchIn(BaseModel):
    kept_text: str | None = None
    changes: list[str] | None = None
    target_metrics: list[str] | None = None


class PlanLinkIn(BaseModel):
    published_post_id: int
    replace: bool = False


class PlanCheckIn(BaseModel):
    refresh: bool = True


class HomepageIn(BaseModel):
    account_id: int
    bio: str = Field(default="", max_length=1000)
    pinned_post_ids: list[int] = Field(default_factory=list, max_length=3)
    direction_note: str = Field(default="", max_length=500)
