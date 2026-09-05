"""跨平台同作品合并服务（M13+）。

规则：同一创作者（主博主或某个对标各自独立）下的云端作品，
规范化标题相同 → 自动归为同一作品（work）；标题不同但内容同源 → 作者手动合并。
"""

from __future__ import annotations

import json
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.platform import CreatorAccount, PlatformPost, PlatformPostStat
from ..models.work import Work

_SPACE_RE = re.compile(r"\\s+")
_TAG_RE = re.compile(r"[#＃][^\\s#＃，,。！？!?]*")
_PUNCT_RE = re.compile(r"[，。！？!?,.;:：、|\\[\\]()（）《》\"'“”…\\-—\\s]+")


def normalize_work_title(title: str) -> str:
    """规范化标题用于跨平台匹配：去话题/标点/空白、小写。"""
    t = _TAG_RE.sub(" ", title or "")
    t = _PUNCT_RE.sub("", t)
    t = _SPACE_RE.sub("", t)
    return t.strip().lower()


def _latest_stat(db: Session, post_id: int):
    return (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id == post_id)
        .order_by(PlatformPostStat.stat_date.desc())
        .first()
    )


def post_item(db: Session, p: PlatformPost) -> dict:
    stat = _latest_stat(db, p.id)
    acc = db.get(CreatorAccount, p.account_id)
    tags = []
    try:
        tags = json.loads(p.tags or "[]") if isinstance(p.tags, str) else (p.tags or [])
    except json.JSONDecodeError:
        tags = []
    return {
        "id": p.id,
        "platform": p.platform,
        "tags": tags,
        "platform_post_id": p.platform_post_id,
        "title": p.title,
        "cover": p.cover_url_local,
        "publish_time": p.publish_time.isoformat() if p.publish_time else None,
        "local_video_id": p.local_video_id,
        "account_nickname": acc.nickname if acc else "",
        "latest_stat": {
            "date": stat.stat_date,
            "plays": stat.plays,
            "likes": stat.likes,
            "favorites": stat.favorites,
            "shares": stat.shares,
            "comments": stat.comments,
        }
        if stat
        else None,
    }


def auto_merge_creator(db: Session, creator_id: int) -> int:
    """自动合并：同创作者 + 规范化标题相同 → 同一 work。返回新建 work 数。"""
    accounts = (
        db.query(CreatorAccount).filter(CreatorAccount.creator_id == creator_id).all()
    )
    if not accounts:
        return 0
    acc_ids = [a.id for a in accounts]
    posts = (
        db.query(PlatformPost)
        .filter(PlatformPost.account_id.in_(acc_ids), PlatformPost.title != "")
        .order_by(PlatformPost.id)
        .all()
    )
    groups: dict[str, list[PlatformPost]] = {}
    for p in posts:
        key = normalize_work_title(p.title)
        if not key:
            continue
        groups.setdefault(key, []).append(p)

    created = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # 已有 work：取任一成员的 work；否则新建
        existing = next((m.work_id for m in members if m.work_id), None)
        work = db.get(Work, existing) if existing else None
        if work is None:
            title = max(members, key=lambda m: len(m.title)).title or members[0].title
            work = Work(creator_id=creator_id, title=title)
            db.add(work)
            db.flush()
            created += 1
        for m in members:
            if m.work_id != work.id:
                m.work_id = work.id
    db.commit()
    return created


def merge_manual(db: Session, platform_post_ids: list[int], creator_id: int | None = None) -> dict:
    """手动把多条素材标识为同一作品（可跨不同标题）。"""
    ids = [int(x) for x in (platform_post_ids or []) if x]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="至少选择 2 条才能合并为同一作品")
    posts = db.query(PlatformPost).filter(PlatformPost.id.in_(ids)).all()
    if len(posts) != len(ids):
        raise HTTPException(status_code=400, detail="部分素材不存在")
    cids = set()
    for p in posts:
        acc = db.get(CreatorAccount, p.account_id)
        if acc:
            cids.add(acc.creator_id)
    if len(cids) > 1:
        raise HTTPException(status_code=400, detail="只能合并同一博主下的素材")
    creator_id = creator_id or next(iter(cids), None)
    existing = next((p.work_id for p in posts if p.work_id), None)
    work = db.get(Work, existing) if existing else None
    if work is None:
        first = posts[0]
        work = Work(creator_id=creator_id, title=first.title or "", cover_path=first.cover_path)
        db.add(work)
        db.flush()
    for p in posts:
        p.work_id = work.id
    if not work.title and posts:
        work.title = posts[0].title or ""
    db.commit()
    return {"ok": True, "work_id": work.id, "members": len(posts)}


def split_work(db: Session, work_id: int, keep_ids: list[int] | None = None) -> dict:
    """拆分作品：未指定的成员移出该 work；全部移出后删除空 work。"""
    work = db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    keep = set(int(x) for x in (keep_ids or []))
    members = db.query(PlatformPost).filter(PlatformPost.work_id == work_id).all()
    for p in members:
        if p.id not in keep:
            p.work_id = None
    if not keep:
        db.delete(work)
    db.commit()
    return {"ok": True}


def list_works(db: Session, creator_id: int | None = None) -> list[dict]:
    """素材库云端作品列表：已合并作品在前（含各平台数据），未合并单条在后。"""
    q = db.query(PlatformPost)
    if creator_id:
        acc_ids = [a.id for a in db.query(CreatorAccount).filter(CreatorAccount.creator_id == creator_id).all()]
        q = q.filter(PlatformPost.account_id.in_(acc_ids)) if acc_ids else q.filter(PlatformPost.id < 0)
    posts = q.order_by(PlatformPost.publish_time.desc().nullslast(), PlatformPost.id.desc()).all()

    work_map: dict[int, list[PlatformPost]] = {}
    singles: list[PlatformPost] = []
    for p in posts:
        if p.work_id:
            work_map.setdefault(p.work_id, []).append(p)
        else:
            singles.append(p)

    out: list[dict] = []
    for wid, members in work_map.items():
        work = db.get(Work, wid)
        if work is None:
            continue
        members.sort(key=lambda m: m.platform)
        out.append(
            {
                "type": "work",
                "id": wid,
                "title": work.title or members[0].title,
                "creator_id": work.creator_id,
                "cover": next((m.cover_url_local for m in members if m.cover_url_local), None),
                "platforms": [m.platform for m in members],
                "posts": [post_item(db, m) for m in members],
            }
        )
    for p in singles:
        acc = db.get(CreatorAccount, p.account_id)
        out.append(
            {
                "type": "post",
                "id": p.id,
                "title": p.title,
                "creator_id": acc.creator_id if acc else None,
                "cover": p.cover_url_local,
                "platforms": [p.platform],
                "posts": [post_item(db, p)],
            }
        )
    return out
