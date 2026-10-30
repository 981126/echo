"""账号级抖音数据源策略（R-239）。

规则（作者 2026-10-30 确认）：
- 只对抖音账号生效；B 站/小红书恒走公开接口。
- 账号编辑页有「启用创作者中心」开关（默认开）：
  - 开关关闭或未配置 Cookie → 公开接口；
  - 开关开启且 Cookie 有效 → 创作者中心接口（列表/指标）；
  - 开关开启但 Cookie 失效 → 停止该账号所有第三方调用，标记失效并发一次通知，直到更新 Cookie。
- 失效状态只由后台校验/收数发现触发；保存 Cookie 时校验失败由接口直接返回错误，不重复发通知。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.platform import CreatorAccount
from ..models.video_review import DouyinCreatorCredential

SOURCE_CREATOR = "creator"
SOURCE_PUBLIC = "public"
SOURCE_BLOCKED = "blocked"

STATUS_MISSING = "missing"
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_DISABLED = "disabled"

_STATUS_LABEL = {
    STATUS_MISSING: "未配置",
    STATUS_VALID: "可用",
    STATUS_INVALID: "已失效",
    STATUS_DISABLED: "已关闭",
}


def normalize_status(row: DouyinCreatorCredential | None) -> str:
    """把数据库状态归一成展示/策略状态。历史 expired 统一按 invalid 处理。"""
    if row is None or not (row.cookie_value or "").strip():
        return STATUS_MISSING
    if not bool(row.enabled):
        return STATUS_DISABLED
    status = (row.status or "").strip().lower()
    if status == "valid":
        return STATUS_VALID
    if status in ("invalid", "expired"):
        return STATUS_INVALID
    return STATUS_INVALID


@dataclass(frozen=True)
class AccountDataPolicy:
    source: str
    reason: str
    status: str
    enabled: bool
    has_cookie: bool

    @property
    def is_creator(self) -> bool:
        return self.source == SOURCE_CREATOR

    @property
    def is_blocked(self) -> bool:
        return self.source == SOURCE_BLOCKED

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "reason": self.reason,
            "status": self.status,
            "enabled": self.enabled,
            "has_cookie": self.has_cookie,
            "status_label": _STATUS_LABEL.get(self.status, self.status),
        }


def get_credential(db: Session, account_id: int) -> DouyinCreatorCredential | None:
    return db.query(DouyinCreatorCredential).filter_by(account_id=account_id).first()


def resolve_data_policy(db: Session, account: CreatorAccount | None) -> AccountDataPolicy:
    """唯一的数据源判定入口；不发起任何网络请求。"""
    if account is None:
        return AccountDataPolicy(SOURCE_BLOCKED, "账号不存在", STATUS_MISSING, False, False)
    if account.platform != "douyin":
        return AccountDataPolicy(SOURCE_PUBLIC, "非抖音账号，使用公开接口", STATUS_MISSING, False, False)
    row = get_credential(db, account.id)
    has_cookie = bool(row is not None and (row.cookie_value or "").strip())
    enabled = bool(row.enabled) if row is not None else False
    status = normalize_status(row)
    if not has_cookie:
        return AccountDataPolicy(SOURCE_PUBLIC, "未配置抖音创作者 Cookie，使用公开接口", status, enabled, False)
    if not enabled:
        return AccountDataPolicy(SOURCE_PUBLIC, "已关闭创作者中心数据，使用公开接口", status, False, True)
    if status == STATUS_VALID:
        return AccountDataPolicy(SOURCE_CREATOR, "使用抖音创作者中心数据", status, True, True)
    reason = "抖音创作者 Cookie 已失效，已停止该账号数据收集，请在博主管理更新 Cookie"
    return AccountDataPolicy(SOURCE_BLOCKED, reason, STATUS_INVALID, True, True)


def credential_summary(db: Session, account: CreatorAccount) -> dict[str, Any] | None:
    """给账号列表/视频复盘用的只读凭据摘要；B站/小红书返回 None。不返回 Cookie 明文。"""
    if account.platform != "douyin":
        return None
    row = get_credential(db, account.id)
    status = normalize_status(row)
    return {
        "account_id": account.id,
        "enabled": bool(row.enabled) if row is not None else True,
        "has_cookie": bool(row is not None and (row.cookie_value or "").strip()),
        "status": status,
        "status_label": _STATUS_LABEL.get(status, status),
        "last_validated_at": row.last_validated_at.isoformat() if row is not None and row.last_validated_at else None,
        "last_success_at": row.last_success_at.isoformat() if row is not None and row.last_success_at else None,
        "last_error": (row.last_error or "") if row is not None else "",
    }


def mark_valid(db: Session, account: CreatorAccount, *, commit: bool = True) -> None:
    row = get_credential(db, account.id)
    if row is None:
        row = DouyinCreatorCredential(account_id=account.id)
        db.add(row)
    row.status = STATUS_VALID
    row.last_validated_at = _app_now()
    row.last_success_at = _app_now()
    row.last_error = ""
    if commit:
        db.commit()


def mark_invalid(
    db: Session,
    account: CreatorAccount,
    error: str,
    *,
    notify: bool = True,
    commit: bool = True,
) -> bool:
    """标记账号 Cookie 失效；仅状态从非失效变为失效时发一次通知。返回是否发了通知。"""
    row = get_credential(db, account.id)
    if row is None:
        row = DouyinCreatorCredential(account_id=account.id, status=STATUS_INVALID)
        db.add(row)
    previous = normalize_status(row)
    row.status = STATUS_INVALID
    row.last_validated_at = _app_now()
    row.last_error = (error or "")[:500]
    notified = False
    if commit:
        db.commit()
    if notify and previous != STATUS_INVALID:
        from ..tasks import push_notification

        nickname = account.nickname or f"账号 {account.id}"
        push_notification(
            db,
            kind="douyin_credential_invalid",
            status="failed",
            title=f"账号「{nickname}」抖音创作者 Cookie 已失效",
            message=f"{nickname} 的抖音创作者数据已停止收集，所有第三方接口暂停，请在「博主管理 → 编辑账号」更新 Cookie。原因：{(error or '')[:120]}",
            target="/creators",
        )
        notified = True
    return notified


def mark_disabled(db: Session, account: CreatorAccount, *, enabled: bool, commit: bool = True) -> None:
    row = get_credential(db, account.id)
    if row is None:
        row = DouyinCreatorCredential(account_id=account.id)
        db.add(row)
    row.enabled = bool(enabled)
    if commit:
        db.commit()
