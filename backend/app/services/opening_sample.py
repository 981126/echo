"""R-266：开头样本库构建（首句 × 真实指标）。

- own：主博主作品，按「同话题 + 同时长桶」的 5 秒完播百分位排序；样本 <20 时不打极性。
- peer：benchmark 同行作品，按「播放 ÷ 该账号播放中位数」排序（公开数据，不推断留人）。
- negative_reason：该作品最新复盘里「前 10 秒」的第一个掉点。
"""

from __future__ import annotations

import json
import re
from statistics import median
from typing import Any

from sqlalchemy.orm import Session, selectinload

from ..models.opening_sample import OpeningSample
from ..models.platform import Creator, PlatformPost, PlatformPostStat
from ..models.video import Video
from ..models.video_review import DouyinPostMetric, VideoReview
from .post_meta import duration_bucket

MAX_TEXT_CHARS = 120
MIN_OWN_SAMPLES = 20
OWN_HIGH_PERCENTILE = 75.0
OWN_LOW_PERCENTILE = 25.0
PEER_HIGH_MULTIPLE = 2.0
EARLY_DROP_SECONDS = 10

_SENTENCE_SPLIT = re.compile(r"[。！？!?…\n]")
_PUNCT = re.compile(r"[\s。！？!?；;，,、…—“”\"'（）()：:]+")
_BACKGROUND_OPENERS = ("大家好", "我是", "今天想", "最近", "先介绍", "这一期", "hello", "哈喽")
_QUESTION_WORDS = ("为什么", "怎么", "如何", "是不是", "能不能", "有没有")
_NUMBER_WORDS = ("万", "块", "元", "岁", "天", "份", "次", "个月", "年", "小时", "分钟")
_RESULT_WORDS = ("结果", "最后", "拿到", "赚了", "过了", "成了", "面过", "涨了", "降了", "亏了", "被拒", "拒了")


def clean_text(text: str) -> str:
    return _PUNCT.sub("", text or "")


def first_sentence(text: str) -> str:
    """取第一个句子（到 。！？!?… 或换行为止），去空白并截断到 120 字。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(raw) if part.strip()]
    sentence = parts[0] if parts else ""
    if len(sentence) > MAX_TEXT_CHARS:
        sentence = sentence[: MAX_TEXT_CHARS - 1] + "…"
    return sentence


def classify_opening(sentence: str) -> str:
    """开头类型：background 优先，避免「大家好，今天聊 3 个方法」被归成数字型。"""
    text = (sentence or "").strip()
    if not text:
        return "statement"
    lowered = text.lower().replace(" ", "")
    if any(lowered.startswith(word) for word in _BACKGROUND_OPENERS):
        return "background"
    if text.endswith(("？", "?")) or any(word in text for word in _QUESTION_WORDS):
        return "question"
    if re.search(r"\d", text) or any(word in text for word in _NUMBER_WORDS):
        return "number"
    if any(word in text for word in _RESULT_WORDS):
        return "result"
    return "statement"


def _percentile(values: list[float], target: float) -> float:
    if not values:
        return 0.0
    less = sum(1 for value in values if value < target)
    equal = sum(1 for value in values if value == target)
    return round((less + equal * 0.5) / len(values) * 100, 1)


def _topic(video: Video) -> str:
    try:
        items = json.loads(video.main_topics or "[]")
    except (TypeError, ValueError):
        return "未分类"
    if isinstance(items, list) and items:
        return str(items[0] or "未分类")
    return "未分类"


def _early_drop(db: Session, review: VideoReview | None) -> str:
    if review is None:
        return ""
    try:
        snapshot = json.loads(review.metrics_snapshot or "{}")
    except (TypeError, ValueError):
        return ""
    retention = ((snapshot.get("charts") or {}).get("retention") or {})
    for drop in retention.get("drops") or []:
        if not isinstance(drop, dict):
            continue
        if float(drop.get("end_seconds") or 0) > EARLY_DROP_SECONDS:
            continue
        return f"{drop.get('time_label') or ''} 掉 {float(drop.get('drop') or 0) * 100:.1f} 个百分点"
    return ""


def _candidate_rows(db: Session, creators: list[Creator]) -> list[dict[str, Any]]:
    creator_ids = [creator.id for creator in creators]
    if not creator_ids:
        return []
    videos = (
        db.query(Video)
        .options(selectinload(Video.transcript))
        .filter(Video.creator_id.in_(creator_ids), Video.is_ad.is_(False))
        .all()
    )
    video_ids = [video.id for video in videos]
    if not video_ids:
        return []
    posts = (
        db.query(PlatformPost)
        .filter(PlatformPost.local_video_id.in_(video_ids))
        .order_by(PlatformPost.publish_time.desc().nulls_last(), PlatformPost.id.desc())
        .all()
    )
    posts_by_video: dict[int, list[PlatformPost]] = {}
    for post in posts:
        posts_by_video.setdefault(int(post.local_video_id or 0), []).append(post)
    post_ids = [post.id for post in posts]
    metrics: dict[int, DouyinPostMetric] = {}
    stats: dict[int, PlatformPostStat] = {}
    reviews: dict[int, VideoReview] = {}
    if post_ids:
        for metric_row in (
            db.query(DouyinPostMetric)
            .filter(DouyinPostMetric.post_id.in_(post_ids))
            .order_by(DouyinPostMetric.snapshot_date)
            .all()
        ):
            metrics[int(metric_row.post_id)] = metric_row
        for stat_row in (
            db.query(PlatformPostStat)
            .filter(PlatformPostStat.post_id.in_(post_ids))
            .order_by(PlatformPostStat.stat_date)
            .all()
        ):
            stats[int(stat_row.post_id)] = stat_row
        for review_row in (
            db.query(VideoReview)
            .filter(VideoReview.post_id.in_(post_ids))
            .order_by(VideoReview.id)
            .all()
        ):
            reviews[int(review_row.post_id)] = review_row
    return [
        {
            "video": video,
            "posts": posts_by_video.get(video.id, []),
            "metrics": metrics,
            "stats": stats,
            "reviews": reviews,
        }
        for video in videos
    ]


def _text_of(video: Video) -> str:
    transcript = video.transcript
    if transcript is None:
        return ""
    return (transcript.corrected_text or transcript.transcript_text or "").strip()


def build_opening_samples(db: Session, *, owner_id: int) -> dict:
    """重建主博主 + 全部 benchmark 同行的开头样本；返回各组数量。"""
    owner = db.get(Creator, owner_id)
    if owner is None:
        raise ValueError("主博主不存在")
    peers = db.query(Creator).filter(Creator.kind == "benchmark").all()
    created: dict[str, Any] = {"own": 0, "peer": 0, "skipped": 0}
    built_ids: dict[str, set[int]] = {"own": set(), "peer": set()}

    # ---------- 收集候选 ----------
    own_candidates: list[dict[str, Any]] = []
    peer_candidates: list[dict[str, Any]] = []
    for row in _candidate_rows(db, [owner, *peers]):
        video: Video = row["video"]
        text = first_sentence(_text_of(video))
        is_own = video.creator_id == owner.id
        # 同一视频可能有多条帖子：选「最新且带所需指标」的那条，而不是盲目取最新
        post: PlatformPost | None = None
        metric: DouyinPostMetric | None = None
        stat: PlatformPostStat | None = None
        for candidate in row["posts"]:
            candidate_metric = row["metrics"].get(candidate.id)
            candidate_stat = row["stats"].get(candidate.id)
            if is_own and candidate_metric is not None and candidate_metric.finish_5s_rate is not None:
                post, metric, stat = candidate, candidate_metric, candidate_stat
                break
            if not is_own and candidate_stat is not None and candidate_stat.plays:
                post, metric, stat = candidate, candidate_metric, candidate_stat
                break
        if not text or post is None:
            created["skipped"] += 1
            continue
        item: dict[str, Any] = {
            "video": video,
            "post": post,
            "text": text,
            "hook_type": classify_opening(text),
            "topic": _topic(video),
            "bucket": duration_bucket(post.duration_seconds) if post.duration_seconds else "",
            "finish_5s": float(metric.finish_5s_rate) if metric and metric.finish_5s_rate is not None else None,
            "bounce_2s": float(metric.bounce_2s_rate) if metric and metric.bounce_2s_rate is not None else None,
            "plays": int(stat.plays or 0) if stat else None,
            "likes": int(stat.likes or 0) if stat else None,
            "negative_reason": _early_drop(db, row["reviews"].get(post.id)),
        }
        (own_candidates if is_own else peer_candidates).append(item)

    # ---------- own：分层百分位 ----------
    strata: dict[tuple[str, str], list[float]] = {}
    for item in own_candidates:
        strata.setdefault((item["topic"], item["bucket"]), []).append(item["finish_5s"])
    own_total = len(own_candidates)
    for item in own_candidates:
        bucket_values = strata.get((item["topic"], item["bucket"]), [])
        if len(bucket_values) >= 5:
            values, note = bucket_values, f"同话题同况 {item['bucket'] or '未知'} 时长 {len(bucket_values)} 条"
        else:
            topic_values = [x["finish_5s"] for x in own_candidates if x["topic"] == item["topic"]]
            if len(topic_values) >= 5:
                values, note = topic_values, f"同话题 {len(topic_values)} 条（同时长样本不足）"
            else:
                values, note = [x["finish_5s"] for x in own_candidates], f"全账号 {own_total} 条（同话题样本不足）"
        item["rank_score"] = _percentile(values, item["finish_5s"])
        item["baseline_note"] = note
        if own_total >= MIN_OWN_SAMPLES:
            if item["rank_score"] >= OWN_HIGH_PERCENTILE:
                item["polarity"] = "high"
            elif item["rank_score"] <= OWN_LOW_PERCENTILE:
                item["polarity"] = "low"
            else:
                item["polarity"] = "neutral"
        else:
            item["polarity"] = ""

    # ---------- peer：账号内播放倍数 ----------
    by_creator: dict[int, list[float]] = {}
    for item in peer_candidates:
        by_creator.setdefault(int(item["video"].creator_id), []).append(float(item["plays"] or 0))
    peer_medians = {cid: median(values) for cid, values in by_creator.items()}
    for item in peer_candidates:
        base = peer_medians.get(int(item["video"].creator_id)) or 0.0
        if base <= 0:
            item["rank_score"], item["polarity"] = 0.0, ""
        else:
            multiple = round(float(item["plays"] or 0) / base, 2)
            item["rank_score"] = multiple
            item["polarity"] = "high" if multiple >= PEER_HIGH_MULTIPLE else "neutral"
        item["baseline_note"] = "同行公开播放，非留人数据"

    # ---------- 落库（upsert + 清理失效） ----------
    sources: list[tuple[str, list[dict[str, Any]]]] = [("own", own_candidates), ("peer", peer_candidates)]
    for source_kind, items in sources:
        for item in items:
            video_id = int(item["video"].id)
            sample = (
                db.query(OpeningSample)
                .filter_by(video_id=video_id, source_kind=source_kind)
                .first()
            )
            if sample is None:
                sample = OpeningSample(
                    video_id=video_id, source_kind=source_kind, creator_id=item["video"].creator_id
                )
                db.add(sample)
            sample.creator_id = item["video"].creator_id
            sample.post_id = item["post"].id
            sample.platform = item["post"].platform
            sample.text = item["text"]
            sample.chars = len(clean_text(item["text"]))
            sample.hook_type = item["hook_type"]
            sample.finish_5s_rate = item["finish_5s"]
            sample.bounce_2s_rate = item["bounce_2s"]
            sample.plays = item["plays"]
            sample.likes = item["likes"]
            sample.duration_seconds = item["post"].duration_seconds
            sample.published_at = item["post"].publish_time
            sample.rank_score = float(item["rank_score"] or 0)
            sample.polarity = item["polarity"]
            sample.baseline_note = item["baseline_note"][:200]
            sample.negative_reason = item["negative_reason"][:200]
            built_ids[source_kind].add(video_id)
            created[source_kind] += 1

    for source_kind in ("own", "peer"):
        stale = (
            db.query(OpeningSample)
            .filter(OpeningSample.source_kind == source_kind)
            .all()
        )
        for old_sample in stale:
            if old_sample.video_id not in built_ids[source_kind]:
                db.delete(old_sample)
    db.commit()
    return created


def coverage(db: Session, owner_id: int) -> dict:
    rows = db.query(OpeningSample).all()
    own = [row for row in rows if row.source_kind == "own" and row.creator_id == owner_id]
    peer = [row for row in rows if row.source_kind == "peer"]
    built_at = max((row.updated_at for row in rows), default=None)
    return {
        "own": len(own),
        "peer": len(peer),
        "own_high": sum(1 for row in own if row.polarity == "high"),
        "own_low": sum(1 for row in own if row.polarity == "low"),
        "peer_high": sum(1 for row in peer if row.polarity == "high"),
        "built_at": built_at.isoformat() if built_at else None,
        "samples_enough": len(own) >= MIN_OWN_SAMPLES,
    }


def opening_samples_task(db: Session, payload: dict, update=None) -> dict:
    """后台任务：重建开头样本（纯 DB + 文本计算，不调 LLM）。"""
    from .creator_service import get_current_creator

    owner = get_current_creator(db)
    if owner is None:
        raise ValueError("请先创建并切换到主博主")
    if update is not None:
        update(10, "正在读取作品与指标")
    result = build_opening_samples(db, owner_id=owner.id)
    if update is not None:
        update(100, f"完成：自己 {result['own']} 条、同行 {result['peer']} 条")
    return {"own": result["own"], "peer": result["peer"], "skipped": result["skipped"]}
