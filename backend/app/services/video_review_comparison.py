from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from ..models.video import Video
from ..models.video_review import DouyinPostMetric, DouyinReferenceVideo
from .douyin_references import reference_out


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    lower_better: bool = False
    rate: bool = False


SPECS = [
    MetricSpec("plays", "播放量", "次"),
    MetricSpec("likes", "点赞量", "次"),
    MetricSpec("comments", "评论量", "条"),
    MetricSpec("favorites", "收藏量", "次"),
    MetricSpec("shares", "转发量", "次"),
    MetricSpec("like_rate", "点赞率", "ratio", rate=True),
    MetricSpec("bounce_2s_rate", "2秒跳出率", "ratio", lower_better=True, rate=True),
    MetricSpec("finish_5s_rate", "5秒完播率", "ratio", rate=True),
    MetricSpec("finish_rate", "完整完播率", "ratio", rate=True),
    MetricSpec("avg_play_seconds", "平均播放时长", "秒"),
    MetricSpec("cover_click_rate", "封面点击率", "ratio", rate=True),
    MetricSpec("profile_visits", "主页访问量", "次"),
    MetricSpec("follower_gain", "粉丝增量", "人"),
    MetricSpec("follower_per_1k", "每1000次播放带来的关注", "人"),
]
SPEC_MAP = {x.key: x for x in SPECS}


def loads(value: str | None, fallback: Any) -> Any:
    try:
        data = json.loads(value or "null")
        return fallback if data is None else data
    except (json.JSONDecodeError, TypeError):
        return fallback


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    def bigrams(s: str) -> set[str]:
        return {s[i:i + 2] for i in range(max(1, len(s) - 1))}

    aa, bb = bigrams(a), bigrams(b)
    return max(len(aa & bb) / max(1, len(aa | bb)), SequenceMatcher(None, a, b).ratio())


def _latest_stat(db: Session, post_id: int) -> PlatformPostStat | None:
    return db.query(PlatformPostStat).filter_by(post_id=post_id).order_by(PlatformPostStat.stat_date.desc()).first()


def _latest_private(db: Session, post_id: int) -> DouyinPostMetric | None:
    return db.query(DouyinPostMetric).filter_by(post_id=post_id).order_by(DouyinPostMetric.snapshot_date.desc()).first()


def _stat_at(db: Session, post: PlatformPost, age: int) -> PlatformPostStat | None:
    if not post.publish_time:
        return None
    cutoff = (post.publish_time + timedelta(days=age)).date().isoformat()
    return (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id == post.id, PlatformPostStat.stat_date <= cutoff)
        .order_by(PlatformPostStat.stat_date.desc())
        .first()
    )


def _private_at(db: Session, post: PlatformPost, age: int) -> DouyinPostMetric | None:
    if not post.publish_time:
        return None
    cutoff = (post.publish_time + timedelta(days=age)).date().isoformat()
    return (
        db.query(DouyinPostMetric)
        .filter(DouyinPostMetric.post_id == post.id, DouyinPostMetric.snapshot_date <= cutoff)
        .order_by(DouyinPostMetric.snapshot_date.desc())
        .first()
    )


def _values(stat: PlatformPostStat | None, private: DouyinPostMetric | None) -> dict[str, float | int | None]:
    out: dict[str, float | int | None] = {key: None for key in SPEC_MAP}
    if stat:
        for key in ("plays", "likes", "comments", "favorites", "shares"):
            out[key] = getattr(stat, key)
    if private:
        for key in ("bounce_2s_rate", "finish_5s_rate", "finish_rate", "avg_play_seconds", "cover_click_rate", "profile_visits", "follower_gain"):
            out[key] = getattr(private, key)
    plays = out["plays"]
    if plays:
        out["like_rate"] = float(out["likes"] or 0) / float(plays)
        out["follower_per_1k"] = float(out["follower_gain"] or 0) / float(plays) * 1000 if out["follower_gain"] is not None else None
    return out


def _percentile(values: list[float], target: float) -> float:
    less = sum(1 for x in values if x < target)
    equal = sum(1 for x in values if x == target)
    return round((less + equal * 0.5) / len(values) * 100, 1)


def _state(spec: MetricSpec, value: float, baseline: float, percentile: float, sample: int) -> str:
    if sample < 5:
        return "limited"
    if spec.rate:
        if abs(value - baseline) < 0.03:
            return "normal"
    elif baseline and abs(value - baseline) / abs(baseline) < 0.2:
        return "normal"
    elif spec.key == "follower_gain" and abs(value - baseline) < 1:
        return "normal"
    high = percentile >= 75
    low = percentile <= 25
    if spec.lower_better:
        high, low = low, high
    return "high" if high else "low" if low else "normal"


def _topic_score(db: Session, target: PlatformPost, candidate: PlatformPost) -> float:
    score = _sim(target.title, candidate.title) * 0.4
    if target.local_video_id and candidate.local_video_id:
        a = db.get(Video, target.local_video_id)
        b = db.get(Video, candidate.local_video_id)
        if a and b:
            at, bt = set(loads(a.main_topics, [])), set(loads(b.main_topics, []))
            ag, bg = set(loads(a.tags, [])), set(loads(b.tags, []))
            if at & bt:
                score += 1.0
            if ag and bg and len(ag & bg) / len(ag | bg) >= 0.5:
                score += 0.6
            if a.main_topics == b.main_topics:
                score += 0.1
    return score


def build_comparison(db: Session, post: PlatformPost) -> dict:
    current_stat = _latest_stat(db, post.id)
    current_private = _latest_private(db, post.id)
    age = max(0, (_app_now().date() - post.publish_time.date()).days) if post.publish_time else 0
    candidates = (
        db.query(PlatformPost)
        .filter(PlatformPost.account_id == post.account_id, PlatformPost.id != post.id, PlatformPost.is_ad.is_(False))
        .order_by(PlatformPost.publish_time.desc())
        .limit(30)
        .all()
    )
    ranked = sorted(candidates, key=lambda p: (_topic_score(db, post, p), p.publish_time or datetime.min), reverse=True)
    comparison = ranked[:10]
    ids = [p.id for p in comparison]
    current = _values(current_stat, current_private)
    metrics: list[dict] = []
    facts: dict[str, dict] = {}
    for spec in SPECS:
        history: list[float] = []
        for candidate in comparison:
            value = _values(_stat_at(db, candidate, age), _private_at(db, candidate, age))[spec.key]
            if value is not None:
                history.append(float(value))
        value = current[spec.key]
        baseline = float(median(history)) if history else None
        percentile = _percentile(history, float(value)) if history and value is not None else None
        state = "missing" if value is None else "limited"
        if value is not None and baseline is not None and percentile is not None:
            state = _state(spec, float(value), baseline, percentile, len(history))
        item = {
            "key": spec.key,
            "label": spec.label,
            "unit": spec.unit,
            "value": value,
            "baseline": baseline,
            "percentile": percentile,
            "state": state,
            "sample_count": len(history),
            "missing": value is None,
        }
        metrics.append(item)
        facts[spec.key] = item
    dims = {
        "plays": facts["plays"]["state"],
        "engagement": facts["like_rate"]["state"],
        "completion": "low" if "low" in (facts["finish_rate"]["state"], facts["finish_5s_rate"]["state"]) else "high" if "high" in (facts["finish_rate"]["state"], facts["finish_5s_rate"]["state"]) else "normal",
        "followers": facts["follower_per_1k"]["state"],
    }
    low = sum(x == "low" for x in dims.values())
    high = sum(x == "high" for x in dims.values())
    valid_sample = int(facts["plays"]["sample_count"])
    if valid_sample < 5:
        overall = "unknown"
    elif low >= 2:
        overall = "needs_improvement"
    elif high >= 2 and low == 0:
        overall = "good"
    else:
        overall = "mixed"
    warnings = [] if valid_sample >= 5 else ["可比较的历史视频较少，暂时不做整体好坏判断"]
    return {
        "metrics": metrics,
        "facts": facts,
        "comparison": {
            "count": len(comparison),
            "post_ids": ids,
            "sample_note": "按相近主题、时长和发布天数比较" if comparison else "暂无可比较视频",
            "age_days": age,
        },
        "overall": overall,
        "warnings": warnings,
        "charts": _charts(current_stat, current_private, metrics),
    }


def _charts(stat: PlatformPostStat | None, private: DouyinPostMetric | None, metrics: list[dict]) -> dict:
    traffic = loads(private.traffic_sources, {}) if private else {}
    if isinstance(traffic, dict):
        traffic_items = []
        total = sum(float(v) for v in traffic.values() if isinstance(v, (int, float)))
        for name, value in traffic.items():
            if isinstance(value, (int, float)):
                ratio = float(value) / total if total > 1 else float(value)
                traffic_items.append({"name": name, "value": value, "ratio": ratio})
    else:
        traffic_items = traffic if isinstance(traffic, list) else []
    points = []
    similar = loads(private.similar_author_trend, {}) if private else {}
    for point in loads(private.retention_trend, []) if private else []:
        if not isinstance(point, dict):
            continue
        label = str(point.get("key") or point.get("time") or "00:00")
        parts = label.split(":")
        try:
            seconds = int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            seconds = 0
        points.append({
            "time_seconds": seconds,
            "time_label": label,
            "current": point.get("value"),
            "similar_author": None,
        })
    for index, point in enumerate(similar.get("retention") or []):
        if index < len(points) and isinstance(point, dict):
            points[index]["similar_author"] = point.get("value")
    return {
        "comparison": metrics,
        "retention": {
            "points": points,
            "reliable": bool(private.trend_reliable) if private else False,
            "plays": stat.plays if stat else None,
            "has_timed_transcript": False,
        },
        "traffic": traffic_items,
        "search_terms": loads(private.search_terms, []) if private else [],
        "comment_questions": [],
        "follower_topics": [],
        "peer_comparisons": [],
        "plan": [],
    }


def _post_stats(db: Session, post_ids: list[int]) -> dict[int, PlatformPostStat]:
    rows = db.query(PlatformPostStat).filter(PlatformPostStat.post_id.in_(post_ids)).order_by(PlatformPostStat.stat_date).all() if post_ids else []
    return {row.post_id: row for row in rows}


def peer_references(db: Session, owner: Creator, limit: int = 20) -> tuple[list[dict], list[dict]]:
    accounts = (
        db.query(CreatorAccount)
        .join(Creator, CreatorAccount.creator_id == Creator.id)
        .filter(Creator.parent_id == owner.id, Creator.kind == "benchmark", CreatorAccount.platform == "douyin", CreatorAccount.enabled.is_(True))
        .all()
    )
    items: list[dict] = []
    charts: list[dict] = []
    cutoff = _app_now() - timedelta(days=30)
    for account in accounts:
        posts = db.query(PlatformPost).filter_by(account_id=account.id, is_ad=False).order_by(PlatformPost.publish_time.desc()).limit(30).all()
        stats = _post_stats(db, [p.id for p in posts])
        plays = [float(stats[p.id].plays) for p in posts if p.id in stats and stats[p.id].plays > 0]
        if not plays:
            continue
        base = float(median(plays))
        for post in posts:
            stat = stats.get(post.id)
            if not stat or not post.publish_time or post.publish_time < cutoff or stat.plays <= 0 or base <= 0:
                continue
            percentile = _percentile(plays, float(stat.plays))
            multiple = stat.plays / base
            formal = len(plays) >= 5 and percentile >= 75 and multiple >= 2
            recent_high = 2 <= len(plays) < 5 and multiple >= 2
            if not (formal or recent_high):
                continue
            verdict = "同行爆款" if formal else "高于该同行平时"
            evidence = {"baseline_plays": base, "play_multiple": round(multiple, 2), "sample_count": len(plays)}
            items.append({
                "id": f"peer:{post.id}", "kind": "peer", "title": post.title,
                "cover_url": post.cover_url_local, "author_nickname": account.nickname,
                "author_followers": None, "publish_time": post.publish_time,
                "plays": stat.plays, "likes": stat.likes, "comments": stat.comments,
                "video_url": post.video_url, "verdict": verdict,
                "verdict_evidence": evidence, "relevance": 100, "analysis": None,
            })
            charts.append({"post_id": post.id, "title": post.title, "plays": stat.plays, "baseline": base, "play_multiple": round(multiple, 2), "sample_count": len(plays)})
    items.sort(key=lambda x: x["verdict_evidence"]["play_multiple"], reverse=True)
    charts.sort(key=lambda x: x["play_multiple"], reverse=True)
    return items[:limit], charts[:limit]


def low_fan_references(db: Session, owner: Creator, keyword: str = "", limit: int = 20) -> list[dict]:
    query = db.query(DouyinReferenceVideo).order_by(DouyinReferenceVideo.last_seen_at.desc())
    if keyword:
        query = query.filter(DouyinReferenceVideo.title.contains(keyword))
    return [reference_out(db, owner, row) for row in query.limit(200).all()][:limit]
