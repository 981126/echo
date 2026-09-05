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


def latest_account_snapshot(db: Session, account_id: int):
    from ..models.platform import CreatorAccountSnapshot

    return (
        db.query(CreatorAccountSnapshot)
        .filter(CreatorAccountSnapshot.account_id == account_id)
        .order_by(CreatorAccountSnapshot.snapshot_date.desc())
        .first()
    )


def account_meta(db: Session, a: CreatorAccount) -> dict:
    """单个账号的展示信息：头像 + 最新粉丝/作品数（主页快照）。"""
    snap = latest_account_snapshot(db, a.id)
    return {
        "id": a.id,
        "creator_id": a.creator_id,
        "platform": a.platform,
        "nickname": snap.nickname if (snap and snap.nickname) else a.nickname,
        "home_link": a.home_link,
        "platform_user_id": a.platform_user_id,
        "avatar": a.avatar,
        "avatar_path": a.avatar_path,
        "avatar_url": a.avatar_url,
        "extra_config": a.extra(),
        "enabled": a.enabled,
        "sync_frequency": a.sync_frequency,
        "followers": snap.followers if snap else 0,
        "likes_total": snap.likes_total if snap else 0,
        "posts_total": snap.posts_total if snap else 0,
        "last_sync_at": a.last_sync_at.isoformat() if a.last_sync_at else None,
        "sync_status": a.sync_status,
        "sync_message": a.sync_message,
    }


def list_accounts_meta(db: Session, creator_id: int) -> list[dict]:
    accounts = (
        db.query(CreatorAccount)
        .filter(CreatorAccount.creator_id == creator_id)
        .order_by(CreatorAccount.id)
        .all()
    )
    return [account_meta(db, a) for a in accounts]


def creator_public_meta(db: Session, c: Creator) -> dict:
    """博主卡片数据：账号列表 + 全网粉丝数（各平台粉丝独立累计，仅粉丝可汇总）+ 代表头像（粉丝最多平台）。"""
    accounts = list_accounts_meta(db, c.id)
    followers_total = sum(int(a["followers"] or 0) for a in accounts)
    rep = None
    for a in accounts:
        if a.get("avatar"):
            if rep is None or int(a["followers"] or 0) > int(rep["followers"] or 0):
                rep = a
    return {
        "id": c.id,
        "kind": c.kind,
        "parent_id": c.parent_id,
        "name": c.name,
        "note": c.note,
        "is_current": c.is_current,
        "avatar": (rep or {}).get("avatar"),
        "followers_total": followers_total,
        "accounts": accounts,
        "account_count": len(accounts),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def list_creators_with_meta(db: Session) -> list[dict]:
    out = []
    for c in db.query(Creator).order_by(Creator.id).all():
        out.append(creator_public_meta(db, c))
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
