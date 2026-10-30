"""抖音创作者数据（TikHub creator_v2）同步与 Cookie 凭证管理（R-237）。

真实接口联调结论（2026-10-30）：
- creator_v2 系列 HTTP 200 只代表 TikHub 代理成功；抖音业务错误在 body 的
  `status_code/status_msg` 或 `BaseResp.StatusCode`（8 = 用户未登录），必须判错，
  否则会把「Cookie 失效」当成功、写入全空指标并覆盖真实数据。
- 作品指标真实字段：view_count / bounce_rate_2s / completion_rate_5s /
  completion_rate / avg_view_second / homepage_visit_count / subscribe_count /
  unsubscribe_count / favorite_count / like_count / comment_count / share_count。
- 流量来源、搜索词不在 overview 接口，需分别调 fetch_item_play_source /
  fetch_item_search_keyword。
- 列表接口不返回其他账号播放量，同行播放量需用 fetch_video_statistics 补采。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.log import get_logger
from ..core.pipeline import today_key
from ..core.timeutil import now as _app_now
from ..models.kv import Kv
from ..models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from ..models.video_review import DouyinCreatorCredential, DouyinPostMetric
from .douyin_account_policy import (
    get_credential,
    mark_invalid,
    mark_valid,
    normalize_status,
    resolve_data_policy,
)
from .platform.budget import _charge
from .platform.tikhub import TikHubBusinessError, TikHubClient, TikHubError, make_client
from .text_tags import extract_hashtags

log = get_logger("douyin_creator_sync")

PEER_PLAYS_KV = "douyin_peer_plays_refreshed_at"
PEER_PLAYS_REUSE_HOURS = 6

# 抖音流量来源 key → 页面直白中文
PLAY_SOURCE_LABELS = {
    "homepage_hot": "推荐",
    "familiar": "朋友",
    "homepage": "主页",
    "search": "搜索",
    "follow": "关注",
    "message": "私信",
    "live": "直播",
    "other": "其他",
}


def _charge_requests(db: Session, client: TikHubClient, before: int) -> None:
    """按真实请求数补记预算；预算异常不覆盖主流程错误。"""
    if client.mode != "real":
        return
    for _ in range(max(0, client.requests_used - before)):
        try:
            _charge(db)
        except Exception as exc:  # noqa: BLE001  预算超限不应覆盖真实业务错误
            log.warning("TikHub 预算计费失败：%s", exc)
            break


class CredentialError(ValueError):
    pass


def _fernet() -> Fernet:
    key = get_settings().douyin_cookie_key.strip()
    if not key:
        raise CredentialError("请先在 .env 配置 ECHO_DOUYIN_COOKIE_KEY")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise CredentialError("ECHO_DOUYIN_COOKIE_KEY 格式不正确") from exc


def encrypt_cookie(value: str) -> str:
    if not value.strip():
        raise CredentialError("Cookie 不能为空")
    return _fernet().encrypt(value.strip().encode()).decode()


def decrypt_cookie(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise CredentialError("Cookie 解密失败，请重新保存") from exc


def credential_out(db: Session, account_id: int) -> dict:
    row = get_credential(db, account_id)
    status = normalize_status(row)
    return {
        "account_id": account_id,
        "enabled": bool(row.enabled) if row is not None else True,
        "status": status,
        "has_cookie": bool(row is not None and (row.cookie_value or "").strip()),
        "last_validated_at": row.last_validated_at if row is not None else None,
        "last_success_at": row.last_success_at if row is not None else None,
        "last_error": (row.last_error or "") if row is not None else "",
    }


def _auth_error(exc: Exception) -> bool:
    return isinstance(exc, TikHubBusinessError) and exc.code in (5, 8)


def is_auth_failure(exc: Exception) -> bool:
    """创作者接口的 Cookie 失效判定：业务码 5/8，或 TikHub 代理把失效 Cookie 包成 HTTP 400。"""
    if _auth_error(exc):
        return True
    return isinstance(exc, TikHubError) and "HTTP 400" in str(exc)


CREDENTIAL_HINT = "Cookie 未登录或已过期，请在「博主管理 → 编辑账号」重新保存抖音创作者 Cookie"


def _credential_message(exc: Exception) -> str:
    if _auth_error(exc):
        return CREDENTIAL_HINT
    text = str(exc)
    if "未配置 ECHO_TIKHUB_API_KEY" in text:
        return "未配置 TikHub API Key，无法验证创作者 Cookie"
    if "预算" in text or "Budget" in text:
        return f"TikHub 请求预算不足，暂时无法验证 Cookie：{text[:120]}"
    # creator_v2 在 Cookie 未登录时真实响应为 HTTP 400（通用提示），对保存/刷新场景按 Cookie 问题提示
    return f"{CREDENTIAL_HINT}；TikHub 返回：{text[:160]}"


def _mark_credential(db: Session, account_id: int, *, ok: bool, error: str = "", auth: bool = False) -> None:
    """兼容旧调用：成功标 valid；失败标 invalid 并按状态迁移发一次通知。"""
    account = db.get(CreatorAccount, account_id)
    if account is None:
        return
    if ok:
        mark_valid(db, account)
    else:
        mark_invalid(db, account, error or "创作者接口调用失败", notify=auth)


def save_credential(db: Session, account: CreatorAccount, cookie: str, *, enabled: bool | None = None) -> dict:
    """保存并做一次最小真实请求验证（会消耗一次 TikHub 额度）；不回显 Cookie。"""
    if account.platform != "douyin":
        raise CredentialError("只有抖音账号支持创作者数据配置")
    encrypted = encrypt_cookie(cookie)
    row = get_credential(db, account.id)
    if row is None:
        row = DouyinCreatorCredential(account_id=account.id)
        db.add(row)
    row.cookie_value = encrypted
    row.last_validated_at = _app_now()
    if enabled is not None:
        row.enabled = bool(enabled)
    elif row.enabled is None:
        row.enabled = True
    client = make_client()
    before = client.requests_used
    try:
        now = _app_now()
        client.fetch_douyin_creator_item_list(
            cookie=cookie.strip(),
            start_time=int((now - timedelta(days=2)).timestamp() * 1000),
            end_time=int(now.timestamp() * 1000),
            count=1,
        )
        row.status = "valid"
        row.last_success_at = _app_now()
        row.last_error = ""
        db.commit()
    except Exception as exc:
        message = _credential_message(exc)
        row.status = "invalid"
        row.last_validated_at = _app_now()
        row.last_error = message[:500]
        db.commit()
        raise CredentialError(message) from exc
    finally:
        _charge_requests(db, client, before)
    return credential_out(db, account.id)


def set_credential_enabled(db: Session, account: CreatorAccount, enabled: bool) -> dict:
    """只切换开关：不需要重新校验 Cookie。"""
    if account.platform != "douyin":
        raise CredentialError("只有抖音账号支持创作者数据配置")
    row = get_credential(db, account.id)
    if row is None:
        raise CredentialError("请先粘贴并保存抖音创作者 Cookie 后再开启")
    if enabled and not (row.cookie_value or "").strip():
        raise CredentialError("请先粘贴并保存抖音创作者 Cookie 后再开启")
    row.enabled = bool(enabled)
    if not enabled:
        row.last_error = ""
        row.status = "valid" if (row.cookie_value or "").strip() else "missing"
    db.commit()
    return credential_out(db, account.id)


def _cookie(db: Session, account_id: int, client: TikHubClient) -> str:
    if client.mode != "real":
        return "mock"
    row = db.query(DouyinCreatorCredential).filter_by(account_id=account_id).first()
    if row is None or not row.cookie_value:
        raise CredentialError("请先设置抖音创作者平台 Cookie")
    return decrypt_cookie(row.cookie_value)


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _data(raw: Any) -> Any:
    if isinstance(raw, dict) and isinstance(raw.get("data"), (dict, list)):
        return raw["data"]
    return raw


def _items(raw: Any) -> list[dict]:
    data = _data(raw)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "list", "objs", "aweme_list"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
    return []


def _item(raw: Any, item_id: str) -> dict:
    for item in _items(raw):
        if str(item.get("id") or item.get("item_id") or item.get("aweme_id") or "") == str(item_id):
            return item
    items = _items(raw)
    return items[0] if items and str(item_id) == "" else {}


def _deep_find(value: Any, names: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in names and isinstance(item, (int, float, str)):
                return item
        for item in value.values():
            found = _deep_find(item, names)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_find(item, names)
            if found is not None:
                return found
    return None


def _number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("%", "").strip())
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def _metric(item: dict, names: set[str], *, rate: bool = False) -> float | int | None:
    value = _number(_deep_find(item, names))
    if value is None:
        return None
    if rate:
        number = float(value)
        if 1 < number <= 100:
            number /= 100
        return number if 0 <= number <= 1 else None
    return value


def _int_metric(item: dict, names: set[str]) -> int | None:
    value = _metric(item, names)
    return int(value) if value is not None else None


def _trend(raw: Any) -> tuple[list, list]:
    data = _data(raw)
    trend = data.get("analysis_trend", data) if isinstance(data, dict) else {}
    current = trend.get("current_item") or trend.get("current") or []
    similar = trend.get("similar_author") or trend.get("similar") or []
    return current if isinstance(current, list) else [], similar if isinstance(similar, list) else []


def _traffic_sources(raw: Any) -> list[dict]:
    """fetch_item_play_source → 页面图表用 [{name,value,ratio}]；英文 key 转直白中文，未知渠道归「其他渠道」。"""
    data = _data(raw)
    items = data.get("play_source") if isinstance(data, dict) else None
    merged: dict[str, dict] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = _number(item.get("value"))
        if not key or value is None:
            continue
        ratio = float(value)
        name = PLAY_SOURCE_LABELS.get(key) or "其他渠道"
        entry = merged.setdefault(name, {"name": name, "value": 0.0, "ratio": 0.0, "keys": []})
        entry["value"] = round(float(entry["value"]) + ratio, 6)
        entry["ratio"] = round(float(entry["ratio"]) + ratio, 6)
        entry["keys"].append(key)
    return sorted(merged.values(), key=lambda x: float(x["value"]), reverse=True)


def _search_terms(raw: Any) -> list[dict]:
    """fetch_item_search_keyword → [{term,value}]；真实结构 inspire_search/show_from 内为 {keyword,percent}。"""
    data = _data(raw)
    merged: dict[str, float] = {}
    if isinstance(data, dict):
        for key in ("inspire_search", "show_from", "keywords"):
            items = data.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                term = str(item.get("keyword") or item.get("term") or item.get("word") or "").strip()
                if not term:
                    continue
                percent = _number(item.get("percent") or item.get("percentage"))
                value = _number(item.get("count") if percent is None else None)
                if percent is not None:
                    value = round(float(percent) * 100, 1)
                if value is None:
                    continue
                merged[term] = max(float(value), merged.get(term, 0.0))
    return [{"term": term, "value": value} for term, value in sorted(merged.items(), key=lambda x: x[1], reverse=True)[:20]]


def _duration_seconds(item: dict) -> int | None:
    info = item.get("video_info")
    raw = _number(info.get("duration")) if isinstance(info, dict) else None
    if raw is None:
        return None
    value = int(float(raw))
    # 创作者接口 video_info.duration 单位为毫秒（如 85774 = 85.7 秒）
    return round(value / 1000) if value > 1000 else value


def stats_from_item(item: dict) -> dict:
    """把创作者接口单条作品映射成标准统计 dict（平台同步/素材库/复盘共用）。"""
    raw_metrics = item.get("metrics")
    metrics: dict = raw_metrics if isinstance(raw_metrics, dict) else {}
    bounce = _metric(metrics, {"bounce_rate_2s", "bounce_2s_rate", "2s_bounce_rate"})
    finish5 = _metric(metrics, {"completion_rate_5s", "finish_5s_rate", "5s_finish_rate"})
    finish = _metric(metrics, {"completion_rate", "finish_rate", "play_finish_ratio"})
    avg_play = _metric(metrics, {"avg_view_second", "avg_play_seconds", "avg_play_duration"})
    cover = _metric(metrics, {"cover_click_rate", "cover_ctr"})
    profile = _int_metric(metrics, {"homepage_visit_count", "profile_visits", "profile_visit_count"})
    follower = _int_metric(metrics, {"subscribe_count", "follower_gain", "fans_increment"})
    return {
        "plays": int(_metric(metrics, {"view_count", "play_count", "plays"}) or 0),
        "likes": int(_metric(metrics, {"like_count", "digg_count", "likes"}) or 0),
        "comments": int(_metric(metrics, {"comment_count", "comments"}) or 0),
        "favorites": int(_metric(metrics, {"favorite_count", "collect_count", "favorites"}) or 0),
        "shares": int(_metric(metrics, {"share_count", "shares"}) or 0),
        "source": "tikhub_creator",
        "extra": {
            "source": "douyin_creator_v2",
            "bounce_2s_rate": bounce,
            "finish_5s_rate": finish5,
            "finish_rate": finish,
            "avg_play_seconds": avg_play,
            "cover_click_rate": cover,
            "profile_visits": profile,
            "follower_gain": follower,
            "duration_seconds": _duration_seconds(item),
        },
    }


def _apply_item_metrics(db: Session, post: PlatformPost, item: dict) -> tuple[DouyinPostMetric, PlatformPostStat]:
    """把创作者接口返回的单条作品指标落库（按天快照 + 公开统计）。真实字段名优先。"""
    stats = stats_from_item(item)
    today = today_key()
    row = db.query(DouyinPostMetric).filter_by(post_id=post.id, snapshot_date=today).first()
    if row is None:
        row = DouyinPostMetric(post_id=post.id, snapshot_date=today)
        db.add(row)
    row.captured_at = _app_now()
    row.bounce_2s_rate = stats["extra"]["bounce_2s_rate"]
    row.finish_5s_rate = stats["extra"]["finish_5s_rate"]
    row.finish_rate = stats["extra"]["finish_rate"]
    row.avg_play_seconds = stats["extra"]["avg_play_seconds"]
    row.cover_click_rate = stats["extra"]["cover_click_rate"]
    row.profile_visits = stats["extra"]["profile_visits"]
    row.follower_gain = stats["extra"]["follower_gain"]
    row.raw = _json({"item": item, "source": "douyin_creator_v2"})

    public = db.query(PlatformPostStat).filter_by(post_id=post.id, stat_date=today).first()
    if public is None:
        public = PlatformPostStat(post_id=post.id, stat_date=today, source="tikhub_creator")
        db.add(public)
    public.plays = int(stats["plays"])
    public.likes = int(stats["likes"])
    public.comments = int(stats["comments"])
    public.shares = int(stats["shares"])
    public.favorites = int(stats["favorites"])
    public.source = "tikhub_creator"
    try:
        extra = json.loads(public.extra or "{}")
    except (TypeError, ValueError):
        extra = {}
    if not isinstance(extra, dict):
        extra = {}
    if stats["extra"].get("duration_seconds") is not None:
        extra["duration_seconds"] = stats["extra"]["duration_seconds"]
    extra["creator_metrics"] = {
        key: stats["extra"][key]
        for key in ("bounce_2s_rate", "finish_5s_rate", "finish_rate", "avg_play_seconds", "profile_visits", "follower_gain")
    }
    public.extra = _json(extra)
    db.flush()
    return row, public


def sync_post_creator_data(
    db: Session, account: CreatorAccount, post: PlatformPost, client: TikHubClient | None = None
) -> dict:
    """单条作品刷新（视频复盘/发布后检查用）：指标 + 流量来源 + 搜索词 + 观看/跳出趋势。"""
    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        raise CredentialError("当前账号未启用创作者数据，无法刷新创作者私有指标")
    client = client or make_client()
    before = client.requests_used
    cookie = _cookie(db, account.id, client)
    try:
        overview = client.fetch_douyin_creator_overview(cookie=cookie, item_id=post.platform_post_id)
        item = _item(overview, post.platform_post_id)
        if not item:
            raise CredentialError("创作者接口没有返回这条作品的数据，请确认视频属于该账号并稍后重试")
        row, public = _apply_item_metrics(db, post, item)
        row.traffic_sources = _json(_traffic_sources(client.fetch_douyin_creator_play_source(cookie=cookie, item_id=post.platform_post_id)))
        row.search_terms = _json(_search_terms(client.fetch_douyin_creator_search_keyword(cookie=cookie, item_id=post.platform_post_id)))
        trends: dict[str, list] = {}
        similar: dict[str, list] = {}
        for analysis_type, key in ((1, "retention"), (7, "bounce")):
            current, similar_items = _trend(
                client.fetch_douyin_watch_trend(cookie=cookie, item_id=post.platform_post_id, analysis_type=analysis_type)
            )
            trends[key] = current
            similar[key] = similar_items
        row.retention_trend = _json(trends["retention"])
        row.bounce_trend = _json(trends["bounce"])
        row.like_trend = _json([])
        row.similar_author_trend = _json(similar)
        row.trend_reliable = bool((public.plays or 0) >= 200 and trends["retention"])
        mark_valid(db, account)
        return {"post_id": post.id, "metric_id": row.id, "trend_reliable": row.trend_reliable}
    except Exception as exc:
        db.rollback()
        auth = is_auth_failure(exc)
        message = _credential_message(exc) if isinstance(exc, (TikHubBusinessError, CredentialError)) else str(exc)
        if auth:
            mark_invalid(db, account, message, notify=True)
        if isinstance(exc, (TikHubBusinessError, CredentialError)):
            raise CredentialError(message) from exc
        raise
    finally:
        _charge_requests(db, client, before)


def creator_stats_for_post(
    db: Session, account: CreatorAccount, post: PlatformPost, client: TikHubClient | None = None
) -> dict:
    """素材库/单帖同步用的轻量创作者取数：只调 overview（1 次请求），不取流量/趋势。"""
    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        raise CredentialError("当前账号未启用创作者数据")
    client = client or make_client()
    before = client.requests_used
    try:
        cookie = _cookie(db, account.id, client)
        overview = client.fetch_douyin_creator_overview(cookie=cookie, item_id=post.platform_post_id)
        item = _item(overview, post.platform_post_id)
        if not item:
            raise CredentialError("创作者接口没有返回这条作品的数据")
        _apply_item_metrics(db, post, item)
        db.commit()
        mark_valid(db, account)
        return stats_from_item(item)
    except Exception as exc:
        db.rollback()
        auth = is_auth_failure(exc)
        message = _credential_message(exc) if isinstance(exc, (TikHubBusinessError, CredentialError)) else str(exc)
        if auth:
            mark_invalid(db, account, message, notify=True)
        if isinstance(exc, (TikHubBusinessError, CredentialError)):
            raise CredentialError(message) from exc
        raise
    finally:
        _charge_requests(db, client, before)


def _creator_item_id(item: dict) -> str:
    return str(item.get("id") or item.get("item_id") or item.get("aweme_id") or "")


def _creator_item_cover(item: dict) -> str:
    cover = item.get("cover")
    if isinstance(cover, dict):
        urls = cover.get("url_list")
        if isinstance(urls, list):
            for url in urls:
                if isinstance(url, str) and url:
                    return url
    return ""


def _creator_item_publish(item: dict) -> datetime | None:
    value = _number(item.get("create_time"))
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(float(value)))
    except (OverflowError, OSError, ValueError):
        return None


def _iter_creator_items(
    client: TikHubClient,
    cookie: str,
    *,
    full: bool,
    recent_days: int,
    max_requests: int,
) -> tuple[list[dict], bool]:
    """时间窗向前分页拉作品；返回 (items, 是否已确认没有更多)。

    creator_v2 的 `cursor` 参数实测无效（返回同一页），因此按 `start_time/end_time` 时间窗分页：
    每次取 [end-90d, end]，再用响应里的 max_cursor（最早作品时间）作为下一页 end，
    直到请求数达到上限、作品为空或时间窗走到 0。full=False 时只看最近 recent_days。
    """
    now = _app_now()
    end = int(now.timestamp() * 1000)
    floor = 0 if full else int((now - timedelta(days=recent_days)).timestamp() * 1000)
    window_ms = 90 * 86400 * 1000
    seen: dict[str, dict] = {}
    requests = 0
    exhausted = False
    while requests < max_requests:
        start = max(floor, end - window_ms)
        raw = client.fetch_douyin_creator_item_list(
            cookie=cookie,
            start_time=start,
            end_time=end,
            count=100,
        )
        requests += 1
        page_items = _items(raw)
        data = _data(raw)
        for item in page_items:
            key = _creator_item_id(item)
            if key:
                seen[key] = item
        has_more = bool(data.get("has_more")) if isinstance(data, dict) else False
        if not page_items:
            exhausted = True
            break
        if not full and not has_more:
            exhausted = True
            break
        nxt = _number(data.get("max_cursor")) if isinstance(data, dict) else None
        next_end = int(nxt) if nxt is not None and int(nxt) > 0 else start
        if next_end >= end:
            # 游标没有前进 → 退到窗口起点，仍不前进则终止，避免死循环
            next_end = start
            if next_end >= end:
                exhausted = True
                break
        end = next_end
        if end <= floor:
            exhausted = True
            break
    return list(seen.values()), exhausted


def fetch_creator_items(
    db: Session,
    account: CreatorAccount,
    *,
    full: bool = False,
    recent_days: int = 120,
    max_requests: int = 60,
    client: TikHubClient | None = None,
    return_meta: bool = False,
):
    """拉取账号作品（时间窗分页）；请求数计入 TikHub 预算。"""
    client = client or make_client()
    before = client.requests_used
    try:
        cookie = _cookie(db, account.id, client)
        items, exhausted = _iter_creator_items(client, cookie, full=full, recent_days=recent_days, max_requests=max_requests)
        if return_meta:
            return items, exhausted, client.requests_used - before
        return items
    finally:
        _charge_requests(db, client, before)


def fetch_creator_post_data(
    db: Session,
    account: CreatorAccount,
    *,
    limit: int | None = None,
    full: bool = False,
    recent_days: int = 120,
    max_requests: int = 60,
    client: TikHubClient | None = None,
) -> list[dict]:
    """创作者作品 → 平台同步用的 PostData 字典（评论/媒体仍由调用方走公开接口）。"""
    items = fetch_creator_items(
        db, account, full=full, recent_days=recent_days, max_requests=max_requests, client=client
    )
    out: list[dict] = []
    for item in items:
        pid = _creator_item_id(item)
        if not pid:
            continue
        desc = str(item.get("description") or "")
        out.append({
            "platform_post_id": pid,
            "title": desc,
            "desc": desc,
            "tags": extract_hashtags(desc),
            "cover_url": _creator_item_cover(item),
            "video_url": "",
            "publish_time": _creator_item_publish(item),
            "stats": stats_from_item(item),
            "raw": item,
        })
        if limit is not None and not full and len(out) >= limit:
            break
    return out


def sync_account_creator_data(db: Session, account: CreatorAccount, limit: int = 30) -> dict:
    """账号级创作者指标同步（每日保鲜）：只同步最近 limit 条已有作品，不新建平台作品。"""
    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        return {"synced": 0, "errors": [], "total": 0, "skipped": "public", "source": policy.source}
    client = make_client()
    posts = (
        db.query(PlatformPost)
        .filter_by(account_id=account.id, platform="douyin")
        .order_by(PlatformPost.publish_time.desc())
        .limit(limit)
        .all()
    )
    synced = 0
    errors: list[str] = []
    try:
        if client.mode != "real":
            for post in posts:
                try:
                    sync_post_creator_data(db, account, post, client)
                    synced += 1
                except Exception as exc:
                    errors.append(f"{post.title[:30]}：{str(exc)[:100]}")
            return {"synced": synced, "errors": errors, "total": len(posts)}
        items = fetch_creator_items(db, account, full=False, recent_days=120, max_requests=2, client=client)
        index = {_creator_item_id(item): item for item in items if _creator_item_id(item)}
        for post in posts:
            item = index.get(str(post.platform_post_id))
            if item is None:
                continue
            try:
                _apply_item_metrics(db, post, item)
                synced += 1
            except Exception as exc:
                errors.append(f"{post.title[:30]}：{str(exc)[:100]}")
        db.commit()
        mark_valid(db, account)
        return {"synced": synced, "errors": errors, "total": len(posts)}
    except Exception as exc:
        db.rollback()
        auth = is_auth_failure(exc)
        message = _credential_message(exc) if isinstance(exc, (TikHubBusinessError, CredentialError)) else str(exc)
        if auth:
            mark_invalid(db, account, message, notify=True)
        if isinstance(exc, (TikHubBusinessError, CredentialError)):
            raise CredentialError(message) from exc
        raise


def _backfill_marker_key(account_id: int) -> str:
    return f"douyin_creator_backfill_done:{account_id}"


def backfill_done(db: Session, account_id: int) -> bool:
    return db.get(Kv, _backfill_marker_key(account_id)) is not None


def _mark_backfill_done(db: Session, account_id: int) -> None:
    key = _backfill_marker_key(account_id)
    row = db.get(Kv, key)
    if row is None:
        db.add(Kv(key=key, value=_app_now().isoformat()))
    else:
        row.value = _app_now().isoformat()
    db.commit()


def backfill_account_creator_data(db: Session, account: CreatorAccount, max_requests: int = 60) -> dict:
    """首次历史回填：把账号全部抖音作品的当天统计补齐；跑完写幂等标记。"""
    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        return {"synced": 0, "complete": False, "skipped": "public", "account_id": account.id}
    client = make_client()
    items, exhausted, _requests = fetch_creator_items(
        db, account, full=True, max_requests=max_requests, client=client, return_meta=True
    )
    posts = db.query(PlatformPost).filter_by(account_id=account.id, platform="douyin").all()
    index = {str(post.platform_post_id): post for post in posts}
    synced = 0
    errors: list[str] = []
    for item in items:
        post = index.get(_creator_item_id(item))
        if post is None:
            continue
        try:
            _apply_item_metrics(db, post, item)
            synced += 1
        except Exception as exc:  # noqa: BLE001 单条失败不阻断
            errors.append(f"{post.platform_post_id}: {str(exc)[:120]}")
            log.warning("历史回填单条失败 %s：%s", post.platform_post_id, exc)
            db.rollback()
    db.commit()
    mark_valid(db, account)
    if exhausted:
        _mark_backfill_done(db, account.id)
    return {"synced": synced, "complete": exhausted, "items": len(items), "errors": errors, "account_id": account.id}


def backfill_creator_worker(db: Session, payload: dict, update=None) -> dict:
    account = db.get(CreatorAccount, int(payload.get("account_id") or 0))
    if account is None:
        raise LookupError("账号不存在")
    if update:
        update(10, "检查账号创作者数据")
    result = backfill_account_creator_data(db, account, max_requests=int(payload.get("max_requests") or 60))
    if update:
        update(100, "历史作品数据补齐完成")
    return result


def _peer_plays_fresh(db: Session) -> bool:
    row = db.get(Kv, PEER_PLAYS_KV)
    if row is None or not row.value:
        return False
    try:
        last = datetime.fromisoformat(row.value)
    except ValueError:
        return False
    return _app_now() - last < timedelta(hours=PEER_PLAYS_REUSE_HOURS)


def _mark_peer_plays_fresh(db: Session) -> None:
    row = db.get(Kv, PEER_PLAYS_KV)
    if row is None:
        db.add(Kv(key=PEER_PLAYS_KV, value=_app_now().isoformat()))
    else:
        row.value = _app_now().isoformat()
    db.commit()


def backfill_peer_plays(db: Session, owner: Creator, *, days: int = 30, max_requests: int = 120, force: bool = False) -> dict:
    """补采对标账号最近作品播放量：列表接口不返回播放量，只有 fetch_video_statistics 有。

    每请求最多 2 个作品 id；结果写入当天 PlatformPostStat，供「同行爆款」规则使用。
    默认 6 小时内复用，避免反复扣额度。
    """
    if not force and _peer_plays_fresh(db):
        return {"updated": 0, "requests": 0, "remaining": 0, "reused": True, "warnings": []}
    client = make_client()
    if client.mode != "real":
        return {"updated": 0, "requests": 0, "remaining": 0, "reused": False, "warnings": []}
    cutoff = _app_now() - timedelta(days=days)
    accounts = (
        db.query(CreatorAccount)
        .join(Creator, CreatorAccount.creator_id == Creator.id)
        .filter(Creator.parent_id == owner.id, Creator.kind == "benchmark", CreatorAccount.platform == "douyin", CreatorAccount.enabled.is_(True))
        .all()
    )
    today = today_key()
    pending: list[PlatformPost] = []
    for account in accounts:
        posts = (
            db.query(PlatformPost)
            .filter_by(account_id=account.id, platform="douyin", is_ad=False)
            .filter(PlatformPost.publish_time >= cutoff)
            .all()
        )
        for post in posts:
            stat = (
                db.query(PlatformPostStat)
                .filter_by(post_id=post.id)
                .order_by(PlatformPostStat.stat_date.desc())
                .first()
            )
            if stat is not None and (stat.plays or 0) > 0:
                continue
            pending.append(post)
    updated = 0
    requests = 0
    warnings: list[str] = []
    limit = max(0, min(max_requests, 120))
    try:
        for index in range(0, len(pending), 2):
            if requests >= limit:
                warnings.append(f"同行播放量补齐达到本次上限（{limit} 次请求），剩余 {len(pending) - index} 条下次继续")
                break
            batch = pending[index:index + 2]
            ids = ",".join(str(post.platform_post_id) for post in batch)
            raw = None
            for attempt in (1, 2):
                try:
                    raw = client.fetch_douyin_video_statistics(ids)
                    requests += 1
                    break
                except TikHubBusinessError as exc:
                    requests += 1
                    warnings.append(f"同行播放量补齐失败：{str(exc)[:120]}")
                    break
                except Exception as exc:
                    requests += 1
                    if attempt == 2:
                        warnings.append(f"同行播放量补齐失败：{str(exc)[:120]}")
                    else:
                        time.sleep(1.5)  # 该接口偶发 400/抖动，稍等重试一次
            if raw is None:
                continue
            time.sleep(0.25)  # 批量补采主动降速，避免上游限流（真实联调 87 次连发出现 400）
            stats = _stats_by_aweme(raw)
            for post in batch:
                stats_item = stats.get(str(post.platform_post_id))
                if not stats_item:
                    continue
                stat_row = db.query(PlatformPostStat).filter_by(post_id=post.id, stat_date=today).first()
                if stat_row is None:
                    stat_row = PlatformPostStat(post_id=post.id, stat_date=today, source="tikhub_statistics")
                    db.add(stat_row)
                stat_row.plays = int(_number(stats_item.get("play_count")) or stat_row.plays or 0)
                if stat_row.likes is None or stat_row.likes == 0:
                    stat_row.likes = int(_number(stats_item.get("digg_count")) or stat_row.likes or 0)
                if stat_row.comments is None or stat_row.comments == 0:
                    stat_row.comments = int(_number(stats_item.get("comment_count")) or stat_row.comments or 0)
                if stat_row.shares is None or stat_row.shares == 0:
                    stat_row.shares = int(_number(stats_item.get("share_count")) or stat_row.shares or 0)
                updated += 1
            db.commit()
        _mark_peer_plays_fresh(db)
    finally:
        _charge_requests(db, client, 0)
    remaining = max(0, len(pending) - updated)
    return {"updated": updated, "requests": requests, "remaining": remaining, "reused": False, "warnings": warnings}


def _stats_by_aweme(raw: Any) -> dict[str, dict]:
    data = _data(raw)
    items: list = []
    if isinstance(data, dict):
        for key in ("statistics_list", "list", "items"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    elif isinstance(data, list):
        items = data
    out: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("aweme_id") or item.get("item_id") or item.get("id") or "")
        if key:
            out[key] = item
    return out
