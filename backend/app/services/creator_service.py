"""博主（主/对标）业务：当前主博主解析、切换、账号聚合（M13，R-029）。"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.platform import Creator, CreatorAccount


def get_current_creator(db: Session) -> Creator | None:
    """当前主博主（kind=owner 且 is_current）；未创建时返回 None。"""
    return (
        db.query(Creator)
        .filter(Creator.kind == "owner", Creator.is_current.is_(True))
        .first()
    )


def current_creator_id(db: Session) -> int | None:
    c = get_current_creator(db)
    return c.id if c else None


def require_current_creator(db: Session) -> Creator:
    c = get_current_creator(db)
    if c is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到一个主博主")
    return c


def switch_current(db: Session, creator_id: int) -> Creator:
    target = db.get(Creator, creator_id)
    if target is None:
        raise HTTPException(status_code=404, detail="博主不存在")
    if target.kind != "owner":
        raise HTTPException(status_code=400, detail="只能切换主博主")
    for c in db.query(Creator).filter(Creator.kind == "owner").all():
        c.is_current = c.id == target.id
    db.commit()
    db.refresh(target)
    return target


def ensure_only_one_owner_current(db: Session) -> None:
    """创建/删除主博主后维护 is_current 唯一性。"""
    owners = db.query(Creator).filter(Creator.kind == "owner").order_by(Creator.id).all()
    current = [c for c in owners if c.is_current]
    if not current and owners:
        owners[0].is_current = True
        db.commit()


def list_creators_with_meta(db: Session) -> list[dict]:
    out: list[dict] = []
    for c in db.query(Creator).order_by(Creator.id).all():
        accounts = db.query(CreatorAccount).filter(CreatorAccount.creator_id == c.id).all()
        out.append(
            {
                "id": c.id,
                "kind": c.kind,
                "parent_id": c.parent_id,
                "name": c.name,
                "note": c.note,
                "is_current": c.is_current,
                "accounts": [
                    {
                        "id": a.id,
                        "platform": a.platform,
                        "nickname": a.nickname,
                        "enabled": a.enabled,
                        "sync_frequency": a.sync_frequency,
                        "last_sync_at": a.last_sync_at,
                        "sync_status": a.sync_status,
                    }
                    for a in accounts
                ],
                "account_count": len(accounts),
                "created_at": c.created_at,
            }
        )
    return out


def delete_creator(db: Session, creator_id: int) -> None:
    c = db.get(Creator, creator_id)
    if c is None:
        raise HTTPException(status_code=404, detail="博主不存在")
    # 有账号/云端作品/本地素材/草稿时禁止物理删除（保护数据）
    from ..models.draft import Draft
    from ..models.platform import CreatorAccount, PlatformPost
    from ..models.video import Video

    if (
        db.query(CreatorAccount).filter(CreatorAccount.creator_id == creator_id).count()
        or db.query(PlatformPost).filter(PlatformPost.account_id.in_(
            [a.id for a in db.query(CreatorAccount).filter(CreatorAccount.creator_id == creator_id).all()]
        )).count()
        or db.query(Video).filter(Video.creator_id == creator_id).count()
        or db.query(Draft).filter(Draft.creator_id == creator_id).count()
        or db.query(Creator).filter(Creator.parent_id == creator_id).count()
    ):
        raise HTTPException(status_code=400, detail="该博主下存在账号/作品/素材/草稿，不能删除")
    db.delete(c)
    db.commit()
    ensure_only_one_owner_current(db)
