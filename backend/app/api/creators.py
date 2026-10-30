"""博主管理接口（M13，R-029）：主博主/对标 CRUD、切换（确认在页面）、账号配置。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models.platform import Creator, CreatorAccount
from ..schemas.platform import AccountIn, AccountOut, CreatorIn, CreatorOut
from ..services.creator_service import (
    creator_public_meta,
    current_creator_id,
    delete_creator,
    ensure_only_one_owner_current,
    list_accounts_meta,
    list_creators_with_meta,
    switch_current,
)
from ..services.douyin_account_policy import credential_summary
from ..services.douyin_creator_sync import CredentialError, save_credential, set_credential_enabled
from ..services.platform.tikhub import parse_link

router = APIRouter()


class DouyinCredentialIn(BaseModel):
    cookie: str | None = None
    enabled: bool | None = None


def _douyin_account(account_id: int, db: Session) -> CreatorAccount:
    account = db.get(CreatorAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.platform != "douyin":
        raise HTTPException(status_code=400, detail="只有抖音账号支持创作者数据配置")
    return account


@router.get("/accounts/{account_id}/douyin-credential", response_model=dict)
def get_douyin_credential(account_id: int, db: Session = Depends(get_db)):
    account = _douyin_account(account_id, db)
    return credential_summary(db, account)


@router.put("/accounts/{account_id}/douyin-credential", response_model=dict)
def put_douyin_credential(account_id: int, payload: DouyinCredentialIn, db: Session = Depends(get_db)):
    account = _douyin_account(account_id, db)
    cookie = (payload.cookie or "").strip()
    try:
        if cookie:
            if len(cookie) > 30000:
                raise HTTPException(status_code=400, detail="Cookie 过长（上限 30000 字符）")
            return save_credential(db, account, cookie, enabled=payload.enabled)
        if payload.enabled is None:
            raise HTTPException(status_code=400, detail="请提供 cookie 或 enabled")
        return set_credential_enabled(db, account, bool(payload.enabled))
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[dict])
def list_creators(db: Session = Depends(get_db)):
    return list_creators_with_meta(db)


@router.get("/current", response_model=dict)
def get_current(db: Session = Depends(get_db)):
    cid = current_creator_id(db)
    if cid is None:
        return {"id": None, "name": "", "avatar": None, "followers_total": 0}
    c = db.get(Creator, cid)
    if c is None:
        return {"id": None, "name": "", "avatar": None, "followers_total": 0}
    meta = creator_public_meta(db, c)
    return {
        "id": c.id,
        "name": c.name,
        "kind": c.kind,
        "avatar": meta["avatar"],
        "followers_total": meta["followers_total"],
    }


@router.post("", response_model=CreatorOut)
def create_creator(payload: CreatorIn, db: Session = Depends(get_db)):
    if payload.kind == "owner":
        # 一个主博主只能有一个父级为空的 owner 自身（同平台多号 = 多个 owner）
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="主博主名称不能为空")
    elif payload.kind == "benchmark":
        if not payload.parent_id:
            raise HTTPException(status_code=400, detail="对标博主必须挂在一个主博主下")
        parent = db.get(Creator, payload.parent_id)
        if parent is None or parent.kind != "owner":
            raise HTTPException(status_code=400, detail="对标博主的主博主不存在")
    else:
        raise HTTPException(status_code=400, detail="kind 仅支持 owner/benchmark")
    c = Creator(
        kind=payload.kind,
        parent_id=payload.parent_id if payload.kind == "benchmark" else None,
        name=payload.name.strip() or "未命名",
        note=payload.note.strip(),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    ensure_only_one_owner_current(db)
    return c


@router.patch("/{creator_id}", response_model=CreatorOut)
def update_creator(creator_id: int, payload: CreatorIn, db: Session = Depends(get_db)):
    c = db.get(Creator, creator_id)
    if c is None:
        raise HTTPException(status_code=404, detail="博主不存在")
    if payload.name is not None:
        c.name = payload.name.strip() or c.name
    if payload.note is not None:
        c.note = payload.note.strip()
    db.commit()
    db.refresh(c)
    return c


@router.post("/{creator_id}/activate", response_model=CreatorOut)
def activate_creator(creator_id: int, db: Session = Depends(get_db)):
    """切换当前主博主（前端弹框确认后调用）。"""
    return switch_current(db, creator_id)


@router.delete("/{creator_id}", response_model=dict)
def remove_creator(creator_id: int, db: Session = Depends(get_db)):
    delete_creator(db, creator_id)
    return {"ok": True}


# ---------- 账号配置 ----------
@router.get("/{creator_id}/accounts", response_model=list[dict])
def list_accounts(creator_id: int, db: Session = Depends(get_db)):
    if db.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="博主不存在")
    return list_accounts_meta(db, creator_id)


@router.post("/{creator_id}/accounts", response_model=AccountOut)
def create_account(creator_id: int, payload: AccountIn, db: Session = Depends(get_db)):
    if db.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="博主不存在")
    dup = (
        db.query(CreatorAccount)
        .filter(CreatorAccount.creator_id == creator_id, CreatorAccount.platform == payload.platform)
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail=f"该博主已配置 {payload.platform} 账号")
    user_id = payload.platform_user_id
    if payload.home_link and not user_id:
        user_id = parse_link(payload.platform, payload.home_link)
        if not user_id:
            raise HTTPException(status_code=400, detail="未能从主页链接解析出平台用户 ID（试试完整主页链接，或直接填写平台用户 ID）")
    a = CreatorAccount(
        creator_id=creator_id,
        platform=payload.platform,
        nickname=payload.nickname.strip(),
        home_link=payload.home_link.strip(),
        platform_user_id=user_id,
        extra_config=json.dumps(payload.extra_config or {}, ensure_ascii=False),
        enabled=payload.enabled,
        sync_frequency=payload.sync_frequency,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: int, payload: AccountIn, db: Session = Depends(get_db)):
    a = db.get(CreatorAccount, account_id)
    if a is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    user_id = payload.platform_user_id
    if payload.home_link and payload.home_link != a.home_link and not user_id:
        user_id = parse_link(payload.platform or a.platform, payload.home_link)
        if not user_id:
            raise HTTPException(status_code=400, detail="未能从主页链接解析出平台用户 ID（试试完整主页链接，或直接填写平台用户 ID）")
    a.nickname = payload.nickname.strip()
    a.home_link = payload.home_link.strip()
    if user_id:
        a.platform_user_id = user_id
    merged_extra = a.extra()
    merged_extra.update(payload.extra_config or {})
    a.extra_config = json.dumps(merged_extra, ensure_ascii=False)
    a.enabled = payload.enabled
    a.sync_frequency = payload.sync_frequency
    db.commit()
    db.refresh(a)
    return a


@router.delete("/accounts/{account_id}", response_model=dict)
def remove_account(account_id: int, db: Session = Depends(get_db)):
    a = db.get(CreatorAccount, account_id)
    if a is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    db.delete(a)
    db.commit()
    return {"ok": True}


class AccountEnabledIn(BaseModel):
    enabled: bool


@router.post("/accounts/{account_id}/enabled", response_model=AccountOut)
def set_account_enabled(account_id: int, payload: AccountEnabledIn, db: Session = Depends(get_db)):
    """R-101：启用/禁用账号——禁用后不再自动同步，素材库/对标隐藏该账号数据。"""
    a = db.get(CreatorAccount, account_id)
    if a is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    a.enabled = payload.enabled
    db.commit()
    db.refresh(a)
    return a


@router.post("/accounts/{account_id}/avatar", response_model=dict)
def upload_account_avatar(account_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """手动上传账号头像（jpg/png，存 covers/，之后自动同步不再覆盖）。"""
    a = db.get(CreatorAccount, account_id)
    if a is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(status_code=400, detail="头像仅支持 jpg/png")
    settings = get_settings()
    settings.covers_dir.mkdir(parents=True, exist_ok=True)
    new_name = f"avatar_{uuid.uuid4().hex[:10]}{suffix}"
    dest = settings.covers_dir / new_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if a.avatar_path:
        try:
            (settings.covers_dir / a.avatar_path).unlink(missing_ok=True)
        except OSError:
            pass
    a.avatar_path = new_name
    db.commit()
    from ..services.creator_service import account_meta

    return account_meta(db, a)



def parse_account_link(payload: dict, db: Session = Depends(get_db)):
    platform = (payload.get("platform") or "").strip()
    link = (payload.get("home_link") or "").strip()
    if platform not in ("douyin", "xiaohongshu", "bilibili"):
        raise HTTPException(status_code=400, detail="platform 仅支持 douyin/xiaohongshu/bilibili")
    if not link:
        raise HTTPException(status_code=400, detail="请填写主页分享链接")
    uid = parse_link(platform, link)
    if not uid:
        raise HTTPException(status_code=400, detail="未能从链接解析出账号 ID（请直接粘贴主页分享链接，或手动填写平台用户 ID）")
    return {"platform": platform, "platform_user_id": uid}


class BenchmarkToggleIn(BaseModel):
    on: bool


@router.post("/{creator_id}/benchmark", response_model=dict)
def toggle_benchmark(creator_id: int, payload: BenchmarkToggleIn, db: Session = Depends(get_db)):
    """R-098：把某个博主标为当前主博主的对标（on），或恢复为独立主博主（off）。"""
    target = db.get(Creator, creator_id)
    if target is None:
        raise HTTPException(status_code=404, detail="博主不存在")
    owner_id = current_creator_id(db)
    owner = db.get(Creator, owner_id) if owner_id else None
    if owner is None:
        raise HTTPException(status_code=400, detail="请先创建并切换到主博主")
    if target.id == owner.id:
        raise HTTPException(status_code=400, detail="当前主博主不能标为对标")
    if payload.on:
        target.kind = "benchmark"
        target.parent_id = owner.id
        target.is_current = False
    else:
        target.kind = "owner"
        target.parent_id = None
        target.is_current = False
    db.commit()
    db.refresh(target)
    return {"ok": True, "id": target.id, "kind": target.kind, "parent_id": target.parent_id}
