"""R-244 抖音数据看板服务：账号总览 + 近期作品 + 作品分析 + 刷新任务。

数据来源：TikHub creator_v2（设计见 `development-design/R-244-douyin-data-dashboard.md`）。
本模块只做「读本地缓存/快照 + 归一化第三方响应 + 编排刷新任务」，不猜测缺失数据：
- 账号诊断（5 指标 + 同类对比）来自 `fetch_author_diagnosis`，缓存 24h；
- 近 7 日主页访问量/点赞/分享/评论、逐日播放趋势由本地每日快照差值计算（口径差异在页面说明）；
- 作品详情 5 个 tab 的私有指标来自 `fetch_item_overview_data` 等接口，落库后读缓存（6h）；
- 评论热词为本地评论词频统计，评论管理只读；拿不到的项返回空并带说明。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from math import ceil
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.kv import Kv
from ..models.platform import CreatorAccount, CreatorAccountSnapshot, PlatformPost, PlatformPostComment, PlatformPostStat
from ..models.video_review import DouyinPostMetric
from .creator_service import get_current_creator
from .douyin_account_policy import credential_summary, mark_invalid, mark_valid, resolve_data_policy
from .douyin_creator_sync import (
    CredentialError,
    _charge_requests,
    _credential_message,
    _cookie,
    is_auth_failure,
    make_client,
    sync_account_creator_data,
    sync_post_creator_data,
)
from .platform.budget import get_budget
from .platform.tikhub import TikHubBusinessError

OVERVIEW_KV = "douyin_dashboard:overview:{account_id}"
OVERVIEW_TTL_HOURS = 24
DETAIL_TTL_HOURS = 6
OVERVIEW_REQUESTS = 3  # 诊断 1 + 作品快照 2（投稿概览已不展示，2026-11-01 起不再请求）
POST_REQUESTS = 8  # 作品私有指标 5 + 观众画像 1 + 受众兴趣 1 + 评论 1

# 状态映射（证据见设计 5.6：真实响应 review.status=2/visibility.status=1 为通过，
# review.status=4 + visibility.status=3 为私密/不适宜公开）
STATUS_LABELS = {
    "approved": "通过",
    "private": "私密",
    "rejected": "不适宜公开",
    "published": "已发布",
    "unknown": "状态未知",
}

# 活跃分布映射（证据见设计 5.9：截图图例颜色面积占比与接口 active 值逐项比对得出；
# TikHub 文档写成「上午/下午/晚上」与实际抖音页面不符，以页面口径为准）
ACTIVE_LABELS = {"-1": "未知", "1": "低活", "2": "轻度", "3": "中度", "4": "重度"}
ACTIVE_ORDER = ["-1", "1", "2", "3", "4"]
GENDER_LABELS = {"male": "男性", "female": "女性"}
AGE_ORDER = ["-18", "18-23", "24-30", "31-40", "41-50", "50-"]
PLAY_SOURCE_LABELS = {
    "推荐": "推荐页",
    "关注": "关注页",
    "主页": "个人主页",
    "朋友": "朋友页",
    "私信": "消息页",
    "搜索": "搜索",
    "直播": "直播",
    "其他": "其他",
    "其他渠道": "其他",
}

DIAGNOSIS_FIELDS = {
    "plays": "PlayCnt",
    "finish_rate": "PlayFinishRatio",
    "interact": "Interact",
    "new_fans": "NewFans",
    "publish_count": "PublishActivation",
}



_CJK = re.compile(r"[\u4e00-\u9fff]+")
_URL_RE = re.compile(r"https?://\S+")
_STOP_CHARS = set("的了是吗呢吧啊呀哦嗯哈么着过嘛哟啦咯呗")
_STOPWORDS = frozenset(
    """
    我 你 他 她 它 我们 你们 他们 自己 这个 那个 这些 那些 什么 怎么 为什么 可以 感觉 觉得
    真的 确实 就是 不是 没有 不会 不能 不要 不用 不过 不然 不行 不错 还有 还是 或者 但是
    然后 因为 所以 如果 时候 现在 今天 明天 昨天 之前 之后 一个 一下 一点 一直 一样 一次
    一天 一年 东西 事情 问题 希望 应该 需要 可能 准备 开始 继续 知道 认为 出来 起来 上去
    下来 这里 那里 这么 那么 多少 几个 有的 有人 有些 有点 大家 朋友 视频 内容 评论 点赞
    关注 收藏 分享 谢谢 支持 加油 哈哈 呵呵 捂脸 大笑 笑哭 流泪 牛 厉害 真的假的 无语 笑死
    哥们 兄弟 小姐姐 老师 老板 这种 那种 一定 一般 一起 一会 没有 不是 不要 不用 不错 确实
    你这 我那 你这 真的假的 有没有 是不是 行不行 好不好 对不对 咋样 咋办 怎么办
    """.split()
)


# ---------- 通用小工具 ----------


def _loads(value: Any, fallback: Any) -> Any:
    try:
        data = json.loads(value or "null")
    except (TypeError, ValueError):
        return fallback
    return fallback if data is None else data


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _rate(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    if 1 < number <= 100:
        number /= 100
    return number if 0 <= number <= 1 else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _hours_since(value: datetime | None) -> float:
    if value is None:
        return float("inf")
    return max(0.0, (_app_now() - value).total_seconds() / 3600)


def _safe_error(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return text[:160]


def _owner(db: Session):
    return get_current_creator(db)


def _resolve(db: Session) -> dict:
    """当前主博主 + 抖音账号 + 数据策略（不发起网络请求）。"""
    owner = _owner(db)
    if owner is None:
        return {
            "owner": None,
            "account": None,
            "policy": None,
            "credential": None,
            "blocked_reason": "请先创建并切换主博主",
        }
    account = (
        db.query(CreatorAccount)
        .filter_by(creator_id=owner.id, platform="douyin", enabled=True)
        .order_by(CreatorAccount.id)
        .first()
    )
    if account is None:
        return {
            "owner": owner,
            "account": None,
            "policy": None,
            "credential": None,
            "blocked_reason": "请先绑定当前主博主的抖音账号",
        }
    return {
        "owner": owner,
        "account": account,
        "policy": resolve_data_policy(db, account),
        "credential": credential_summary(db, account),
        "blocked_reason": "",
    }


def _own_post(db: Session, owner, post_id: int) -> tuple[CreatorAccount, PlatformPost]:
    """当前主博主的抖音作品：不存在/不属于 → LookupError，无账号 → ValueError。"""
    account = (
        db.query(CreatorAccount)
        .filter_by(creator_id=owner.id, platform="douyin", enabled=True)
        .order_by(CreatorAccount.id)
        .first()
    )
    if account is None:
        raise ValueError("请先绑定当前主博主的抖音账号")
    post = db.get(PlatformPost, post_id)
    if post is None or post.platform != "douyin" or post.account_id != account.id:
        raise LookupError("作品不存在或不属于当前主博主")
    return account, post


def _running_task(kind: str, payload: dict) -> int | None:
    from ..tasks import find_running_task

    return find_running_task(kind, payload)


def _ensure_budget(db: Session, needed: int) -> None:
    budget = get_budget(db)
    remaining = int(budget["remaining"])
    if remaining < needed:
        raise ValueError(f"今日 TikHub 请求额度不足（剩余 {remaining} 次，本次需要 {needed} 次）")


def _latest_metric(db: Session, post_id: int) -> DouyinPostMetric | None:
    return (
        db.query(DouyinPostMetric)
        .filter_by(post_id=post_id)
        .order_by(DouyinPostMetric.snapshot_date.desc(), DouyinPostMetric.id.desc())
        .first()
    )


def _latest_stat(db: Session, post_id: int) -> PlatformPostStat | None:
    return (
        db.query(PlatformPostStat)
        .filter_by(post_id=post_id)
        .order_by(PlatformPostStat.stat_date.desc(), PlatformPostStat.id.desc())
        .first()
    )


def _latest_maps(db: Session, post_ids: list[int]) -> tuple[dict[int, PlatformPostStat], dict[int, DouyinPostMetric]]:
    """批量取每条作品最新一天的统计/创作者指标（避免 N+1）。"""
    if not post_ids:
        return {}, {}
    sub = (
        db.query(PlatformPostStat.post_id, func.max(PlatformPostStat.stat_date).label("d"))
        .filter(PlatformPostStat.post_id.in_(post_ids))
        .group_by(PlatformPostStat.post_id)
        .subquery()
    )
    stats = {
        row.post_id: row
        for row in db.query(PlatformPostStat)
        .join(sub, and_(PlatformPostStat.post_id == sub.c.post_id, PlatformPostStat.stat_date == sub.c.d))
        .all()
    }
    sub2 = (
        db.query(DouyinPostMetric.post_id, func.max(DouyinPostMetric.snapshot_date).label("d"))
        .filter(DouyinPostMetric.post_id.in_(post_ids))
        .group_by(DouyinPostMetric.post_id)
        .subquery()
    )
    metrics = {
        row.post_id: row
        for row in db.query(DouyinPostMetric)
        .join(sub2, and_(DouyinPostMetric.post_id == sub2.c.post_id, DouyinPostMetric.snapshot_date == sub2.c.d))
        .all()
    }
    return stats, metrics


# ---------- 状态解析 ----------


def _raw_item(row: DouyinPostMetric | None) -> dict:
    if row is None:
        return {}
    payload = _loads(row.raw, {})
    if not isinstance(payload, dict):
        return {}
    item = payload.get("item")
    return item if isinstance(item, dict) else {}


def post_status(row: DouyinPostMetric | None) -> tuple[str, str]:
    """作品状态：私密 > 不适宜公开 > 通过 > 已发布 > 未知。"""
    item = _raw_item(row)
    if not item:
        raw_text = (row.raw or "").strip() if row is not None else ""
        return ("unknown", "—" if raw_text in ("", "{}") else STATUS_LABELS["unknown"])
    review_raw = item.get("review")
    review = review_raw if isinstance(review_raw, dict) else {}
    visibility_raw = item.get("visibility")
    visibility = visibility_raw if isinstance(visibility_raw, dict) else {}
    if _int(visibility.get("status")) == 3:
        return ("private", STATUS_LABELS["private"])
    if _int(review.get("status")) == 4:
        return ("rejected", STATUS_LABELS["rejected"])
    if _int(review.get("status")) == 2:
        return ("approved", STATUS_LABELS["approved"])
    if _int(visibility.get("status")) == 1:
        return ("published", STATUS_LABELS["published"])
    return ("unknown", STATUS_LABELS["unknown"])


# ---------- 账号诊断 / 投稿概览归一化 ----------


def normalize_diagnosis(body: dict) -> dict | None:
    """fetch_author_diagnosis → {metrics: {plays/finish_rate/interact/new_fans/publish_count}, similar_count}。"""
    if not isinstance(body, dict):
        return None
    payload = body.get("data")
    payload = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(payload, dict):
        return None
    metrics: dict[str, dict] = {}
    similar_count = None
    for key, raw_key in DIAGNOSIS_FIELDS.items():
        row = payload.get(raw_key)
        if not isinstance(row, dict):
            continue
        own = _num(row.get("OwnValue"))
        similar = _num(row.get("SimilarValue"))
        rank = _rate(row.get("AuthorRank"))
        if similar_count is None:
            similar_count = _int(row.get("SimilarCount"))
        metrics[key] = {
            "own": int(own) if own is not None and float(own).is_integer() else own,
            "similar": int(similar) if similar is not None and float(similar).is_integer() else similar,
            "rank": rank,
        }
    if not metrics:
        return None
    return {"metrics": metrics, "similar_count": similar_count}


_COUNTER_FIELDS = ("plays", "likes", "comments", "shares", "profile_visits")


def _clean_counter_series(series: dict[int, dict[str, dict]]) -> None:
    """累计计数器不可能从 >0 掉回 0：同作品同字段出现过正数时，把 0 当缺失日期剔除。

    历史数据里公开同步的 `plays` 长期被写成 0（app/v3 不返回播放数），而创作者接口是真实值；
    不清理就会把「0 → 170573」算成一天新增 17 万播放。点赞/评论/分享/主页访问量同理。
    """
    for days in series.values():
        for field in _COUNTER_FIELDS:
            observed = [day[field] for day in days.values() if field in day and day[field] is not None]
            if not any(int(value) > 0 for value in observed):
                continue
            for day in days.values():
                if field in day and day[field] is not None and int(day[field]) == 0:
                    del day[field]


PERIOD_DAYS = (7, 14, 30, 90)
PERIOD_LABELS = {7: "近 7 日", 14: "近 14 日", 30: "近 30 日", 90: "近 90 日"}

# 指标卡与曲线共用：作品维度指标（本地快照差值） + 账号维度粉丝指标
METRIC_SPECS: list[tuple[str, str, str, str]] = [
    # (key, label, 快照字段, 单位)
    ("plays", "播放量", "plays", "次"),
    ("homepage_visits", "主页访问量", "profile_visits", "次"),
    ("likes", "作品点赞", "likes", "次"),
    ("shares", "作品分享", "shares", "次"),
    ("comments", "作品评论", "comments", "条"),
    ("net_fans", "净增粉丝", "net_fans", "人"),
]
METRIC_MAP = {key: (label, field, unit) for key, label, field, unit in METRIC_SPECS}
POST_METRIC_KEYS = ("plays", "homepage_visits", "likes", "shares", "comments")


def _account_series(db: Session, account_id: int, start: date) -> dict[int, dict[str, dict]]:
    """{post_id: {date: {field: value}}}，取 start 起（含之前周期）的作品快照。"""
    start_s = start.isoformat()
    series: dict[int, dict[str, dict]] = {}
    stat_rows = (
        db.query(
            PlatformPostStat.post_id,
            PlatformPostStat.stat_date,
            PlatformPostStat.plays,
            PlatformPostStat.likes,
            PlatformPostStat.comments,
            PlatformPostStat.shares,
        )
        .join(PlatformPost, PlatformPost.id == PlatformPostStat.post_id)
        .filter(
            PlatformPost.account_id == account_id,
            PlatformPost.platform == "douyin",
            PlatformPostStat.stat_date >= start_s,
        )
        .all()
    )
    # 快照有效性：某天公开统计全为 0 视为无效快照（历史同步失败写 0），不参与差值。
    invalid: set[tuple[int, str]] = set()
    for post_id, stat_date, plays, likes, comments, shares in stat_rows:
        values = {
            "plays": int(plays or 0),
            "likes": int(likes or 0),
            "comments": int(comments or 0),
            "shares": int(shares or 0),
        }
        if not any(values.values()):
            invalid.add((post_id, stat_date))
            series.setdefault(post_id, {})[stat_date] = {}
            continue
        series.setdefault(post_id, {})[stat_date] = values
    metric_rows = (
        db.query(DouyinPostMetric.post_id, DouyinPostMetric.snapshot_date, DouyinPostMetric.profile_visits)
        .join(PlatformPost, PlatformPost.id == DouyinPostMetric.post_id)
        .filter(PlatformPost.account_id == account_id, PlatformPost.platform == "douyin", DouyinPostMetric.snapshot_date >= start_s)
        .all()
    )
    for post_id, snapshot_date, profile_visits in metric_rows:
        if (post_id, snapshot_date) in invalid:
            continue
        series.setdefault(post_id, {}).setdefault(snapshot_date, {})["profile_visits"] = (
            int(profile_visits) if profile_visits is not None else None
        )
    _clean_counter_series(series)
    return series


def _fan_series(db: Session, account_id: int, start: date) -> list[tuple[str, int]]:
    """账号粉丝数每日快照（总粉丝量曲线 / 净增粉丝曲线的数据源）。"""
    rows = (
        db.query(CreatorAccountSnapshot.snapshot_date, CreatorAccountSnapshot.followers)
        .filter(CreatorAccountSnapshot.account_id == account_id, CreatorAccountSnapshot.snapshot_date >= start.isoformat())
        .order_by(CreatorAccountSnapshot.snapshot_date)
        .all()
    )
    return [(str(snapshot_date), int(followers or 0)) for snapshot_date, followers in rows]


def _window_delta(series: dict[int, dict[str, dict]], field: str, start: date, end: date) -> tuple[int, int, list[str]]:
    """区间首末快照差值合计；返回 (合计, 覆盖作品数, 覆盖日期)。"""
    start_s, end_s = start.isoformat(), end.isoformat()
    total = 0
    covered = 0
    dates: set[str] = set()
    for post_series in series.values():
        values = [
            (stat_date, value[field])
            for stat_date, value in sorted(post_series.items())
            if start_s <= stat_date <= end_s and value.get(field) is not None
        ]
        if len(values) < 2 or values[0][0] == values[-1][0]:
            continue
        total += max(0, int(values[-1][1]) - int(values[0][1]))
        covered += 1
        dates.update(day for day, _ in values)
    return total, covered, sorted(dates)


def _fan_window_delta(fan_series: list[tuple[str, int]], start: date, end: date) -> tuple[int, int, list[str]]:
    """区间粉丝净增（可为负）；返回 (净增, 是否有可比数据(0/1), 覆盖日期)。"""
    start_s, end_s = start.isoformat(), end.isoformat()
    values = [(day, followers) for day, followers in fan_series if start_s <= day <= end_s]
    if len(values) < 2:
        return 0, 0, [day for day, _ in values]
    return values[-1][1] - values[0][1], 1, [day for day, _ in values]


def _post_trend_buckets(series: dict[int, dict[str, dict]], field: str, start: date, end: date) -> dict[str, int]:
    """某指标的「新增」曲线：本次抓取值 - 上一次可用快照值（作者 2026-11-01 确认口径）。

    - 上一次快照就是昨天 → 等于当日新增；
    - 昨天没抓 → 用「非今天的最近一日」快照做基线（可能是几天前），该点包含这几天的累计增量；
    - 起点必须落在统计周期内（先按周期整体算，不引入窗口外基线），这样曲线各点之和 = 周期首末快照差值。
    """
    start_s, end_s = start.isoformat(), end.isoformat()
    buckets: dict[str, int] = {}
    for post_series in series.values():
        values = [
            (stat_date, value[field])
            for stat_date, value in sorted(post_series.items())
            if value.get(field) is not None
        ]
        for (before_day, before), (day, after) in zip(values, values[1:]):
            if before_day < start_s or day > end_s:
                continue
            buckets[day] = buckets.get(day, 0) + max(0, int(after) - int(before))
    return buckets


def _fan_net_buckets(fan_series: list[tuple[str, int]], start: date, end: date) -> dict[str, int]:
    """粉丝净增曲线（可为负）：本次快照 - 上一次可用快照；断档时该点包含这几天累计净增。"""
    start_s, end_s = start.isoformat(), end.isoformat()
    buckets: dict[str, int] = {}
    for (before_day, before), (day, after) in zip(fan_series, fan_series[1:]):
        if before_day < start_s or day > end_s:
            continue
        buckets[day] = after - before
    return buckets


def _period_days(days: int, today: date) -> list[date]:
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _series_points(days: list[date], values: Mapping[str, int | None]) -> list[dict]:
    return [{"date": day.isoformat(), "value": values.get(day.isoformat())} for day in days]


def account_kpis(db: Session, account_id: int, days: int = 7, today: date | None = None) -> dict:
    """账号总览：任意统计周期（7/14/30/90 天）的 KPI 合计、较前周期对比与逐日曲线序列。"""
    today = today or _app_now().date()
    days = days if days in PERIOD_DAYS else 7
    start = today - timedelta(days=days - 1)
    fetch_start = today - timedelta(days=2 * days - 1)
    prev_start, prev_end = fetch_start, today - timedelta(days=days)
    series = _account_series(db, account_id, fetch_start)
    fan_series = _fan_series(db, account_id, fetch_start)

    fields: dict[str, dict] = {}
    for key in POST_METRIC_KEYS:
        field = METRIC_MAP[key][1]
        total, covered, dates = _window_delta(series, field, start, today)
        prev_total, prev_covered, prev_dates = _window_delta(series, field, prev_start, prev_end)
        delta = None
        if covered and prev_covered and prev_covered >= ceil(covered * 0.5):
            delta = total - prev_total
        fields[key] = {
            "value": total if covered else None,
            "prev": prev_total if prev_covered else None,
            "delta": delta,
            "covered": covered,
            "prev_covered": prev_covered,
            "dates": dates,
            "prev_dates": prev_dates,
        }

    net, net_covered, net_dates = _fan_window_delta(fan_series, start, today)
    prev_net, prev_net_covered, prev_net_dates = _fan_window_delta(fan_series, prev_start, prev_end)
    fields["net_fans"] = {
        "value": net if net_covered else None,
        "prev": prev_net if prev_net_covered else None,
        "delta": (net - prev_net) if (net_covered and prev_net_covered) else None,
        "covered": net_covered,
        "prev_covered": prev_net_covered,
        "dates": net_dates,
        "prev_dates": prev_net_dates,
    }

    days_list = _period_days(days, today)
    series_out: dict[str, dict] = {}
    for key in POST_METRIC_KEYS:
        label, field, unit = METRIC_MAP[key]
        buckets = _post_trend_buckets(series, field, start, today)
        series_out[key] = {
            "key": key,
            "label": label,
            "unit": unit,
            "mode": "daily",
            "points": _series_points(days_list, buckets),
        }
    net_buckets = _fan_net_buckets(fan_series, start, today)
    series_out["net_fans"] = {
        "key": "net_fans",
        "label": "净增粉丝",
        "unit": "人",
        "mode": "daily",
        "points": _series_points(days_list, net_buckets),
    }
    return {
        "period": {"start": start.isoformat(), "end": today.isoformat(), "days": days, "label": PERIOD_LABELS[days]},
        "fields": fields,
        "series": series_out,
    }


def _kpi_cards(snapshot: dict, diagnosis: dict | None, days: int) -> list[dict]:
    """7 个指标卡：播放量/主页访问量/作品点赞/作品分享/作品评论/净增粉丝/总粉丝量（一行 4 个显示）。"""
    metrics = (diagnosis or {}).get("metrics") or {}

    def diag(key: str) -> dict:
        value = metrics.get(key)
        return value if isinstance(value, dict) else {}

    def snapshot_card(key: str, label: str, unit: str) -> dict:
        item = snapshot["fields"].get(key) or {}
        covered = int(item.get("covered") or 0)
        dates = item.get("dates") or []
        return {
            "key": key,
            "label": label,
            "unit": unit,
            "trend_key": key,
            "value": item.get("value"),
            "prev": item.get("prev"),
            "delta": item.get("delta"),
            "source": "snapshot",
            "similar": None,
            "rank": None,
            "available": covered > 0,
            "coverage": {"posts": covered, "dates": dates},
            "note": ""
            if covered
            else f"数据积累中（已有 {len(dates)} 天快照，至少需要 2 天）",
        }

    cards: list[dict] = []
    # 播放量/净增粉丝：仅 7 日周期有官方诊断口径；其它周期用本地快照
    for key, label, unit, diag_key in (
        ("plays", "播放量", "次", "plays"),
        ("homepage_visits", "主页访问量", "次", None),
        ("likes", "作品点赞", "次", None),
        ("shares", "作品分享", "次", None),
        ("comments", "作品评论", "条", None),
        ("net_fans", "净增粉丝", "人", "new_fans"),
    ):
        official = diag(diag_key) if (diag_key and days == 7) else {}
        if official.get("own") is not None:
            cards.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "trend_key": key,
                    "value": official.get("own"),
                    "prev": None,
                    "delta": None,
                    "source": "diagnosis",
                    "similar": official.get("similar"),
                    "rank": official.get("rank"),
                    "available": True,
                    "coverage": None,
                    "note": f"较前 {days} 日：诊断接口无上期数据",
                }
            )
        else:
            cards.append(snapshot_card(key, label, unit))

    return cards


# ---------- 账号总览缓存 ----------


def _read_overview_cache(db: Session, account_id: int) -> dict:
    row = db.get(Kv, OVERVIEW_KV.format(account_id=account_id))
    data = _loads(row.value if row else "", {})
    return data if isinstance(data, dict) else {}


def _write_overview_cache(db: Session, account_id: int, payload: dict) -> None:
    key = OVERVIEW_KV.format(account_id=account_id)
    row = db.get(Kv, key)
    if row is None:
        row = Kv(key=key, value="")
        db.add(row)
    row.value = _json(payload)
    db.commit()


# ---------- 账号总览 ----------


def overview(db: Session, period_days: int = 7) -> dict:
    """账号总览（period_days ∈ 7/14/30/90）：诊断缓存 + 本地快照 KPI/各指标逐日曲线。"""
    if period_days not in PERIOD_DAYS:
        raise ValueError(f"统计周期只支持 {'/'.join(str(x) for x in PERIOD_DAYS)} 天")
    ctx = _resolve(db)
    account: CreatorAccount | None = ctx["account"]
    policy = ctx["policy"]
    result: dict = {
        "account": {"id": account.id, "nickname": account.nickname, "avatar": account.avatar} if account else None,
        "credential": ctx["credential"],
        "data_policy": policy.as_dict() if policy is not None else None,
        "private_available": bool(account is not None and policy is not None and policy.is_creator),
        "blocked_reason": ctx["blocked_reason"],
        "period": None,
        "diagnosis": None,
        "kpis": [],
        "series": {},
        "needs_refresh": True,
        "stale": True,
        "updating_task_id": None,
        "warnings": [],
    }
    if account is None:
        return result

    now = _app_now()
    today = now.date()
    cache = _read_overview_cache(db, account.id)
    diagnosis = cache.get("diagnosis") if isinstance(cache.get("diagnosis"), dict) else None
    diagnosis_at = _parse_dt(cache.get("diagnosis_at"))
    stale = diagnosis_at is None or (now - diagnosis_at) > timedelta(hours=OVERVIEW_TTL_HOURS)

    snapshot = account_kpis(db, account.id, days=period_days, today=today)
    warnings = [str(x) for x in (cache.get("warnings") or []) if isinstance(x, str)]
    result.update(
        {
            "period": snapshot["period"],
            "diagnosis": {
                "available": bool(diagnosis and diagnosis.get("metrics")),
                "captured_at": _iso(diagnosis_at),
                "similar_count": (diagnosis or {}).get("similar_count"),
                **(diagnosis or {}).get("metrics", {}),
            },
            "kpis": _kpi_cards(snapshot, diagnosis, period_days),
            "series": snapshot["series"],
            "needs_refresh": stale,
            "stale": stale,
            "updating_task_id": _running_task("douyin_dashboard_overview", {"account_id": account.id}),
            "warnings": warnings,
        }
    )
    if policy is not None and policy.is_blocked:
        result["warnings"].append(policy.reason)
    return result


# ---------- 近期作品列表 ----------


def list_works(db: Session, limit: int = 20, offset: int = 0) -> dict:
    ctx = _resolve(db)
    account: CreatorAccount | None = ctx["account"]
    if account is None:
        raise ValueError(ctx["blocked_reason"] or "请先绑定当前主博主的抖音账号")
    base = db.query(PlatformPost).filter_by(account_id=account.id, platform="douyin")
    total = base.count()
    posts = (
        base.order_by(PlatformPost.publish_time.desc().nulls_last(), PlatformPost.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    ids = [post.id for post in posts]
    stats, metrics = _latest_maps(db, ids)
    items: list[dict] = []
    for post in posts:
        stat = stats.get(post.id)
        metric = metrics.get(post.id)
        status, status_label = post_status(metric)
        items.append(
            {
                "post_id": post.id,
                "title": post.title or "",
                "cover_url": post.cover_url_local,
                "publish_time": _iso(post.publish_time),
                "status": status,
                "status_label": status_label,
                "plays": stat.plays if stat else None,
                "likes": stat.likes if stat else None,
                "comments": stat.comments if stat else None,
                "shares": stat.shares if stat else None,
                "has_detail": metric is not None,
                "data_time": _iso(metric.captured_at) if metric else (_iso(stat.updated_at) if stat else None),
            }
        )
    return {"items": items, "total": total, "has_more": offset + len(items) < total}


# ---------- 作品详情 ----------


def _item_metrics(row: DouyinPostMetric | None) -> dict:
    item = _raw_item(row)
    metrics = item.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _duration_seconds(item: dict) -> int | None:
    info = item.get("video_info")
    if not isinstance(info, dict):
        return None
    raw = _num(info.get("duration"))
    if raw is None:
        return None
    value = int(raw)
    return round(value / 1000) if value > 1000 else value


def _overview_values(row: DouyinPostMetric | None, stat: PlatformPostStat | None) -> dict:
    """作品指标归一：raw item metrics 优先，缺失回退同表列/公开统计。"""
    metrics = _item_metrics(row)

    def pick_int(key: str, fallback: int | None = None) -> int | None:
        value = _int(metrics.get(key))
        return value if value is not None else fallback

    def pick_rate(key: str, fallback: float | None = None) -> float | None:
        value = _rate(metrics.get(key))
        return value if value is not None else fallback

    def pick_num(key: str, fallback: float | None = None) -> float | None:
        value = _num(metrics.get(key))
        return value if value is not None else fallback

    return {
        "plays": pick_int("view_count", stat.plays if stat else None),
        "likes": pick_int("like_count", stat.likes if stat else None),
        "comments": pick_int("comment_count", stat.comments if stat else None),
        "shares": pick_int("share_count", stat.shares if stat else None),
        "favorites": pick_int("favorite_count", stat.favorites if stat else None),
        "danmaku": pick_int("danmaku_count"),
        "finish_rate": pick_rate("completion_rate", row.finish_rate if row else None),
        "bounce_2s_rate": pick_rate("bounce_rate_2s", row.bounce_2s_rate if row else None),
        "finish_5s_rate": pick_rate("completion_rate_5s", row.finish_5s_rate if row else None),
        "avg_play_seconds": pick_num("avg_view_second", row.avg_play_seconds if row else None),
        "avg_view_proportion": pick_rate("avg_view_proportion"),
        "favorite_rate": pick_rate("favorite_rate"),
        "cover_click_rate": pick_rate("cover_click_rate", row.cover_click_rate if row else None),
        "follower_gain": pick_int("subscribe_count", row.follower_gain if row else None),
        "follower_rate": pick_rate("subscribe_rate"),
        "unfollowers": pick_int("unsubscribe_count"),
        "unfollower_rate": pick_rate("unsubscribe_rate"),
        "dislike_count": pick_int("dislike_count"),
        "dislike_rate": pick_rate("dislike_rate"),
        "fan_view_proportion": pick_rate("fan_view_proportion"),
        "profile_visits": pick_int("homepage_visit_count", row.profile_visits if row else None),
    }


def _play_trend(db: Session, post_id: int) -> dict:
    rows = (
        db.query(PlatformPostStat)
        .filter_by(post_id=post_id)
        .order_by(PlatformPostStat.stat_date.desc())
        .limit(7)
        .all()
    )
    rows = list(reversed(rows))
    if any(int(row.plays or 0) > 0 for row in rows):
        rows = [row for row in rows if int(row.plays or 0) > 0]
    points: list[dict] = []
    previous = None
    for row in rows:
        played = int(row.plays or 0)
        added = None if previous is None else max(0, played - previous)
        points.append({"date": row.stat_date, "total": played, "added": added})
        previous = played
    available = len(points) >= 2
    return {
        "available": available,
        "mode": ["daily"],
        "points": points,
        "note": "" if available else "逐小时趋势 TikHub 未提供；逐日数据积累中（需要至少 2 天快照）",
    }


def _fan_trend(db: Session, post_id: int) -> dict:
    rows = (
        db.query(DouyinPostMetric)
        .filter_by(post_id=post_id)
        .order_by(DouyinPostMetric.snapshot_date.desc())
        .limit(7)
        .all()
    )
    rows = list(reversed(rows))
    invalid_dates: set[str] = set()
    for stat in db.query(PlatformPostStat).filter_by(post_id=post_id).all():
        if not any(int(value or 0) for value in (stat.plays, stat.likes, stat.comments, stat.shares)):
            invalid_dates.add(stat.stat_date)
    rows = [row for row in rows if row.snapshot_date not in invalid_dates and row.follower_gain is not None]
    if any(int(row.follower_gain or 0) > 0 for row in rows):
        rows = [row for row in rows if int(row.follower_gain or 0) > 0]
    points: list[dict] = []
    previous = None
    for row in rows:
        gain = row.follower_gain
        if gain is None:
            continue
        added = None if previous is None else max(0, int(gain) - previous)
        points.append({"date": row.snapshot_date, "total": int(gain), "added": added})
        previous = int(gain)
    available = len(points) >= 2
    return {
        "available": available,
        "mode": ["daily"],
        "points": points,
        "note": "" if available else "涨粉量趋势需要至少 2 天快照；逐小时趋势 TikHub 未提供",
    }


def _flow_sections(row: DouyinPostMetric | None) -> dict:
    loads = lambda value, fallback: _loads(value, fallback)  # noqa: E731

    def points_of(current_raw: Any, similar_raw: Any) -> list[dict]:
        current = current_raw if isinstance(current_raw, list) else []
        similar_items = similar_raw if isinstance(similar_raw, list) else []
        similar_map = {
            str(item.get("key")): item.get("value")
            for item in similar_items
            if isinstance(item, dict)
        }
        points: list[dict] = []
        for item in current:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if not key:
                continue
            points.append(
                {
                    "key": key,
                    "current": _rate(item.get("value")),
                    "similar": _rate(similar_map.get(key)),
                }
            )
        return points

    similar_map = loads(row.similar_author_trend, {}) if row else {}
    if not isinstance(similar_map, dict):
        similar_map = {}
    retention = points_of(loads(row.retention_trend, []) if row else [], similar_map.get("retention"))
    bounce = points_of(loads(row.bounce_trend, []) if row else [], similar_map.get("bounce"))

    sources: list[dict] = []
    raw_sources = loads(row.traffic_sources, []) if row else []
    for item in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        ratio = _rate(item.get("ratio"))
        if not name or ratio is None:
            continue
        sources.append({"name": PLAY_SOURCE_LABELS.get(name, name), "ratio": ratio})
    sources.sort(key=lambda x: -(x["ratio"] or 0))

    return {
        "retention": {"points": retention, "reliable": bool(row.trend_reliable) if row else False},
        "bounce": {"points": bounce, "reliable": bool(row.trend_reliable) if row else False},
        "sources": sources,
        "unavailable": ["平台扶持流量（TikHub 未提供）"],
    }


def _ratio_items(raw: Any) -> list[dict]:
    if isinstance(raw, dict):
        # 观众画像用 ratio_list；受众兴趣的 total_data 用 ratio_data（R-244 真实响应）
        items = raw.get("ratio_list") if raw.get("ratio_list") is not None else raw.get("ratio_data")
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    out: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        ratio = _rate(item.get("value"))
        if not key or ratio is None:
            continue
        out.append({"key": key, "ratio": ratio})
    return out


def _gender_items(portrait: dict) -> list[dict]:
    ratios = {item["key"]: item["ratio"] for item in _ratio_items(portrait.get("gender"))}
    return [
        {"key": key, "label": GENDER_LABELS[key], "ratio": ratios[key]}
        for key in ("male", "female")
        if key in ratios
    ]


def _active_items(portrait: dict) -> list[dict]:
    raw = portrait.get("active")
    ratios = {item["key"]: item["ratio"] for item in _ratio_items(raw if isinstance(raw, list) else [])}
    return [
        {"key": key, "label": ACTIVE_LABELS[key], "ratio": ratios[key]}
        for key in ACTIVE_ORDER
        if key in ratios
    ]


def _age_items(portrait: dict) -> list[dict]:
    ratios = {item["key"]: item["ratio"] for item in _ratio_items(portrait.get("age"))}
    order = [key for key in AGE_ORDER if key in ratios]
    order += [key for key in ratios if key not in AGE_ORDER]
    return [{"key": key, "label": key, "ratio": ratios[key]} for key in order]


def _region_items(raw: Any, top: int = 6) -> dict:
    items = sorted(_ratio_items(raw), key=lambda x: -x["ratio"])
    head = [{"name": item["key"], "ratio": item["ratio"]} for item in items[:top]]
    rest = round(sum(item["ratio"] for item in items[top:]), 4)
    return {"items": head, "rest": rest, "total": len(items)}


def _interest_items(others: dict) -> list[dict]:
    preference = others.get("audience_preference")
    if not isinstance(preference, dict):
        return []
    total = preference.get("total_data")
    ratios = _ratio_items(total) if isinstance(total, dict) else []
    items = [item for item in ratios if not item["key"].startswith("未分类")]
    items.sort(key=lambda x: -x["ratio"])
    return [{"name": item["key"], "ratio": item["ratio"]} for item in items[:6]]


def _keyword_items(others: dict) -> list[dict]:
    raw = others.get("audience_search_most_keywords")
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        word = str(item.get("keywords") or "").strip()
        heat = _int(item.get("query_cnt_7d"))
        if not word or heat is None:
            continue
        out.append({"word": word, "heat": heat})
    out.sort(key=lambda x: -x["heat"])
    return out[:8]


def _audience_sections(row: DouyinPostMetric | None, db: Session, post_id: int, values: dict) -> dict:
    portrait = _loads(row.audience_portrait, {}) if row else {}
    others = _loads(row.audience_others, {}) if row else {}
    if not isinstance(portrait, dict):
        portrait = {}
    if not isinstance(others, dict):
        others = {}
    region = _region_items(portrait.get("province"))
    city = _region_items(portrait.get("city_level"), top=3)
    return {
        "cards": [
            {"key": "follower_gain", "label": "涨粉量", "value": values["follower_gain"], "unit": "人"},
            {"key": "follower_rate", "label": "涨粉率", "value": values["follower_rate"], "unit": "ratio"},
            {"key": "unfollowers", "label": "脱粉量", "value": values["unfollowers"], "unit": "人"},
            {"key": "unfollower_rate", "label": "脱粉率", "value": values["unfollower_rate"], "unit": "ratio"},
            {"key": "dislike_count", "label": "不感兴趣量", "value": values["dislike_count"], "unit": "人"},
            {"key": "dislike_rate", "label": "不感兴趣率", "value": values["dislike_rate"], "unit": "ratio"},
        ],
        "fan_trend": _fan_trend(db, post_id),
        "gender": _gender_items(portrait),
        "active": _active_items(portrait),
        "age": _age_items(portrait),
        "provinces": region["items"],
        "province_rest": region["rest"],
        "city_levels": city["items"],
        "interests": _interest_items(others),
        "keywords": _keyword_items(others),
    }


def _diagnosis_card(db: Session, post: PlatformPost, values: dict) -> dict:
    """作品诊断：只做「与本人近 30 条同时点中位数对比」的流量结论，不编造原因。"""
    state = "missing"
    sample = 0
    baseline = None
    try:
        from .video_review_comparison import build_comparison

        comparison = build_comparison(db, post)
        facts = comparison.get("facts") or {}
        plays = facts.get("plays") or {}
        state = str(plays.get("state") or "missing")
        sample = int(plays.get("sample_count") or 0)
        baseline = plays.get("baseline")
    except Exception:  # noqa: BLE001 诊断只是附加信息，失败不影响详情
        state, sample, baseline = "missing", 0, None

    played = values.get("plays")
    if state == "missing" or sample < 5 or played is None:
        conclusion = "样本较少，暂不做判断"
        detail = "可比较的历史视频不足，先看上面的指标本身。"
    elif state == "low":
        conclusion = "流量低于平时"
        detail = f"这条视频播放 {played}，你近 30 条相近视频在相同发布天数的中位数是 {baseline:.0f}（样本 {sample} 条）。"
    elif state == "high":
        conclusion = "流量高于平时"
        detail = f"这条视频播放 {played}，高于你近 30 条相近视频在相同发布天数的中位数 {baseline:.0f}（样本 {sample} 条）。"
    else:
        conclusion = "流量接近平时"
        detail = f"这条视频播放 {played}，与你近 30 条相近视频在相同发布天数的中位数 {baseline:.0f} 接近（样本 {sample} 条）。"

    return {
        "conclusion": conclusion,
        "detail": detail,
        "avg_view_proportion": values.get("avg_view_proportion"),
        "favorite_rate": values.get("favorite_rate"),
        "baseline_plays": int(baseline) if baseline is not None else None,
        "sample_count": sample,
        "note": "「较往期」官方对比数据 TikHub 未提供，这里只用本账号历史作品作参考。",
    }


def _comment_out(rows: list[PlatformPostComment]) -> list[dict]:
    return [
        {
            "id": row.id,
            "user": row.user_nick or "",
            "text": row.text or "",
            "likes": int(row.likes or 0),
            "synced_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _clean_comment_text(text: str) -> str:
    text = _URL_RE.sub(" ", text or "")
    text = re.sub(r"#[^#]{0,30}#", " ", text)
    return text


def _candidate_ok(word: str) -> bool:
    if word in _STOPWORDS or len(word) < 2:
        return False
    if len(set(word)) == 1:
        return False
    return not any(ch in _STOP_CHARS for ch in word)


def comment_hot_words(comments: list[str], limit: int = 40) -> dict:
    """本地评论热词：按「评论覆盖条数」统计 2~4 字片段，过滤停用词并去子串重复。

    口径与抖音官方不同，输出带 note 说明；确定性纯函数，便于单测。
    """
    cleaned = [_clean_comment_text(text) for text in comments]
    total = sum(1 for text in cleaned if _CJK.search(text))
    if total < 3:
        return {
            "items": [],
            "total_comments": len(comments),
            "note": "评论太少（少于 3 条），暂无法统计热词",
        }
    counts: dict[str, int] = {}
    for text in cleaned:
        seen: set[str] = set()
        for chunk in _CJK.findall(text):
            for size in (2, 3, 4):
                for index in range(len(chunk) - size + 1):
                    candidate = chunk[index : index + size]
                    if candidate in seen or not _candidate_ok(candidate):
                        continue
                    seen.add(candidate)
                    counts[candidate] = counts.get(candidate, 0) + 1
    threshold = max(2, ceil(total * 0.02))
    ordered = sorted(
        ((word, count) for word, count in counts.items() if count >= threshold),
        key=lambda item: (-item[1], len(item[0]), item[0]),
    )
    kept: list[tuple[str, int]] = []
    for word, count in ordered:
        if any(word in kept_word or kept_word in word for kept_word, _ in kept):
            continue
        kept.append((word, count))
        if len(kept) >= limit:
            break
    return {
        "items": [
            {"word": word, "count": count, "ratio": round(count / total, 4)}
            for word, count in kept
        ],
        "total_comments": total,
        "note": f"基于已同步 {total} 条评论做本地词频统计，与抖音官方口径可能不同",
    }


def post_detail(db: Session, post_id: int) -> dict:
    ctx = _resolve(db)
    owner = ctx["owner"]
    if owner is None:
        raise ValueError(ctx["blocked_reason"] or "请先创建并切换主博主")
    account, post = _own_post(db, owner, post_id)
    policy = resolve_data_policy(db, account)
    row = _latest_metric(db, post.id)
    stat = _latest_stat(db, post.id)
    values = _overview_values(row, stat)
    item = _raw_item(row)
    status, status_label = post_status(row)

    comment_rows = (
        db.query(PlatformPostComment)
        .filter_by(post_id=post.id)
        .order_by(PlatformPostComment.likes.desc(), PlatformPostComment.id.desc())
        .limit(50)
        .all()
    )
    texts = [row_.text or "" for row_ in comment_rows]
    warnings: list[str] = []
    if row is None:
        warnings.append("暂无该作品的创作者私有指标，请点「更新数据」获取；当前只展示公开统计。")
    if policy.is_blocked:
        warnings.append(policy.reason)
    if not policy.is_creator:
        warnings.append("当前账号未开启创作者数据，私有指标不可用（观众画像/流量来源/观看趋势等）")

    return {
        "post": {
            "post_id": post.id,
            "title": post.title or "",
            "cover_url": post.cover_url_local,
            "publish_time": _iso(post.publish_time),
            # 数据看板「查看原视频」固定跳抖音作品页；平台同步里的 video_url 可能是 CDN 直链
            "video_url": f"https://www.douyin.com/video/{post.platform_post_id}",
            "duration_seconds": _duration_seconds(item),
            "status": status,
            "status_label": status_label,
        },
        "data_time": _iso(row.captured_at) if row else (_iso(stat.updated_at) if stat else None),
        "cached": row is not None,
        "stale": row is None or _hours_since(row.captured_at) > DETAIL_TTL_HOURS,
        "private_available": bool(policy.is_creator),
        "overview": {
            "plays": values["plays"],
            "likes": values["likes"],
            "comments": values["comments"],
            "shares": values["shares"],
            "favorites": values["favorites"],
            "danmaku": values["danmaku"],
            "finish_rate": values["finish_rate"],
            "finish_5s_rate": values["finish_5s_rate"],
            "bounce_2s_rate": values["bounce_2s_rate"],
            "avg_play_seconds": values["avg_play_seconds"],
            "avg_view_proportion": values["avg_view_proportion"],
        },
        "play_trend": _play_trend(db, post.id),
        "fans": {
            "follower_gain": values["follower_gain"],
            "unfollowers": values["unfollowers"],
            "fan_view_proportion": values["fan_view_proportion"],
        },
        "diagnosis": _diagnosis_card(db, post, values),
        "flow": _flow_sections(row),
        "audience": _audience_sections(row, db, post.id, values),
        "comment_words": comment_hot_words(texts),
        "comments": {"total": len(comment_rows), "items": _comment_out(comment_rows)},
        "updating_task_id": _running_task("douyin_dashboard_post", {"post_id": post.id}),
        "warnings": warnings,
    }


# ---------- 刷新任务 ----------


def prepare_overview_refresh(db: Session) -> dict:
    ctx = _resolve(db)
    account: CreatorAccount | None = ctx["account"]
    policy = ctx["policy"]
    if account is None:
        raise ValueError(ctx["blocked_reason"] or "请先绑定当前主博主的抖音账号")
    assert policy is not None
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        raise CredentialError("当前账号未开启创作者数据，暂时无法获取私有指标")
    _ensure_budget(db, OVERVIEW_REQUESTS)
    return {"account_id": account.id}


def prepare_post_refresh(db: Session, post_id: int, force: bool) -> dict:
    ctx = _resolve(db)
    owner = ctx["owner"]
    if owner is None:
        raise ValueError(ctx["blocked_reason"] or "请先创建并切换主博主")
    account, post = _own_post(db, owner, post_id)
    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        raise CredentialError("当前账号未开启创作者数据，暂时无法获取私有指标")
    latest = _latest_metric(db, post.id)
    if not force and latest is not None and _hours_since(latest.captured_at) < DETAIL_TTL_HOURS:
        return {
            "skipped": True,
            "reason": f"数据已是最新（{DETAIL_TTL_HOURS} 小时内）",
            "data_time": _iso(latest.captured_at),
            "post_id": post.id,
        }
    _ensure_budget(db, POST_REQUESTS)
    return {"skipped": False, "account_id": account.id, "post_id": post.id}


def overview_worker(db: Session, payload: dict, update) -> dict:
    """账号「更新数据」后台任务：诊断 + 投稿概览 + 作品快照，共 5 次 TikHub 请求。"""
    account = db.get(CreatorAccount, int(payload.get("account_id") or 0))
    if account is None:
        raise ValueError("抖音账号不存在")
    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        raise CredentialError("当前账号未开启创作者数据，暂时无法获取私有指标")

    client = make_client()
    before = client.requests_used
    warnings: list[str] = []
    diagnosis = None
    try:
        cookie = _cookie(db, account.id, client)
        update(10, "正在获取账号诊断")
        diagnosis = normalize_diagnosis(client.fetch_douyin_author_diagnosis(cookie=cookie))
        if diagnosis is None:
            warnings.append("账号诊断返回为空，保留上次数据")
    except Exception as exc:
        auth = is_auth_failure(exc)
        message = _credential_message(exc) if isinstance(exc, (TikHubBusinessError, CredentialError)) else str(exc)
        if auth:
            mark_invalid(db, account, message, notify=True)
        if isinstance(exc, (TikHubBusinessError, CredentialError)):
            raise CredentialError(message) from exc
        raise
    finally:
        _charge_requests(db, client, before)

    update(60, "正在同步作品快照")
    try:
        sync_account_creator_data(db, account, limit=60)
    except Exception as exc:  # noqa: BLE001 快照失败不影响诊断结果
        warnings.append(f"作品快照同步失败：{_safe_error(exc)}")

    update(90, "正在写入缓存")
    cache = _read_overview_cache(db, account.id)
    now_iso = _iso(_app_now())
    _write_overview_cache(
        db,
        account.id,
        {
            "diagnosis": diagnosis if diagnosis is not None else cache.get("diagnosis"),
            "diagnosis_at": now_iso if diagnosis is not None else cache.get("diagnosis_at"),
            "warnings": warnings,
        },
    )
    mark_valid(db, account)
    update(100, "完成")
    return {
        "ok": True,
        "account_id": account.id,
        "diagnosis_at": _iso(_app_now()) if diagnosis else None,
        "warnings": warnings,
    }


def post_worker(db: Session, payload: dict, update) -> dict:
    """作品「更新数据」后台任务：私有指标 5 + 观众画像 1 + 受众兴趣 1 + 评论 1 = 8 次请求。"""
    account = db.get(CreatorAccount, int(payload.get("account_id") or 0))
    post = db.get(PlatformPost, int(payload.get("post_id") or 0))
    if account is None or post is None:
        raise ValueError("作品不存在")
    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if not policy.is_creator:
        raise CredentialError("当前账号未开启创作者数据，暂时无法获取私有指标")

    if not payload.get("force"):
        latest = _latest_metric(db, post.id)
        if latest is not None and _hours_since(latest.captured_at) < DETAIL_TTL_HOURS:
            update(100, "数据已是最新")
            return {"ok": True, "skipped": True, "post_id": post.id, "data_time": _iso(latest.captured_at)}

    warnings: list[str] = []
    update(5, "正在获取作品指标")
    try:
        sync_post_creator_data(db, account, post, with_audience=True)
    except CredentialError:
        raise
    except (TikHubBusinessError, CredentialError) as exc:
        raise CredentialError(_credential_message(exc)) from exc
    update(75, "正在同步评论")
    try:
        from .platform_sync import sync_post_comments

        sync_post_comments(db, post, limit=50, account=account, pool=False)
    except Exception as exc:  # noqa: BLE001 评论失败不影响私有指标
        warnings.append(f"评论同步失败：{_safe_error(exc)}")
    update(100, "完成")
    latest = _latest_metric(db, post.id)
    return {
        "ok": True,
        "post_id": post.id,
        "data_time": _iso(latest.captured_at) if latest else None,
        "warnings": warnings,
    }
