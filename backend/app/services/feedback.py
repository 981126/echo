"""反馈服务：草稿评分/喜欢存储 + 近期好评选题（进入生成上下文）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.draft import Draft
from ..models.feedback import Feedback


def _clamp(v) -> int | None:
    if v is None:
        return None
    return max(1, min(5, int(v)))


def add_feedback(
    db: Session,
    draft_id: int,
    liked: bool | None = None,
    rating: int | None = None,
    comment: str = "",
    hook_score: int | None = None,
    pace_score: int | None = None,
    ending_score: int | None = None,
    style_score: int | None = None,
) -> Feedback:
    if rating is not None:
        rating = max(1, min(5, int(rating)))
    row = Feedback(
        draft_id=draft_id,
        liked=liked,
        rating=rating,
        comment=comment,
        hook_score=_clamp(hook_score),
        pace_score=_clamp(pace_score),
        ending_score=_clamp(ending_score),
        style_score=_clamp(style_score),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if liked:
        draft = db.get(Draft, draft_id)
        if draft:
            draft.status = "used"  # 隐式反馈：采用即标记已用
            db.commit()
    return row


