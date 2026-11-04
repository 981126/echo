from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostComment, PlatformPostStat
from ..models.video import Video
from ..models.video_review import (
    VideoReview,
    VideoReviewFinding,
    VideoTopicRecommendation,
)
from .creator_service import get_current_creator
from .douyin_creator_sync import CredentialError, sync_post_creator_data
from .douyin_references import refresh_references
from .video_review_comparison import build_comparison, dumps, loads, low_fan_references, peer_references
from .video_review_attribution import build_attribution
from .video_review_advices import build_metric_advices
from .video_review_rules import build_findings, comment_questions, homepage_analysis, summary_for
from .video_review_topics import recommend_topics

RULE_VERSION = "1"


def current_owner(db: Session) -> Creator:
    owner = get_current_creator(db)
    if owner is None:
        raise ValueError("请先创建并切换到主博主")
    return owner


def own_account(db: Session, owner: Creator, account_id: int | None = None) -> CreatorAccount:
    query = db.query(CreatorAccount).filter_by(creator_id=owner.id, platform="douyin", enabled=True)
    account = db.get(CreatorAccount, account_id) if account_id else query.first()
    if account is None or account.creator_id != owner.id or account.platform != "douyin" or not account.enabled:
        raise ValueError("请先绑定当前主博主的抖音账号")
    return account


def own_post(db: Session, owner: Creator, post_id: int) -> tuple[CreatorAccount, PlatformPost]:
    post = db.get(PlatformPost, post_id)
    if post is None or post.platform != "douyin":
        raise LookupError("视频不存在")
    account = own_account(db, owner, post.account_id)
    if post.account_id != account.id:
        raise LookupError("视频不属于当前主博主")
    return account, post


def _transcript(db: Session, post: PlatformPost) -> str:
    if not post.local_video_id:
        return ""
    video = db.get(Video, post.local_video_id)
    if not video or not video.transcript:
        return ""
    return (video.transcript.corrected_text or video.transcript.transcript_text or "").strip()


def fingerprint_for(db: Session, post: PlatformPost) -> str:
    from ..models.persona import PersonaTag
    from ..models.video_review import DouyinPostMetric

    metric = db.query(DouyinPostMetric).filter_by(post_id=post.id).order_by(DouyinPostMetric.captured_at.desc()).first()
    comments = db.query(PlatformPostComment).filter_by(post_id=post.id).count()
    account = db.get(CreatorAccount, post.account_id)
    persona_version = max([p.version for p in db.query(PersonaTag).filter_by(creator_id=account.creator_id if account else 0).all()] or [0])
    raw = f"{post.updated_at}|{metric.captured_at if metric else ''}|{comments}|{persona_version}|{RULE_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()


def create_review(db: Session, owner: Creator, post: PlatformPost, task_id: int | None = None) -> VideoReview:
    account = own_account(db, owner, post.account_id)
    review = VideoReview(
        account_id=account.id,
        post_id=post.id,
        task_id=task_id,
        input_fingerprint=fingerprint_for(db, post),
        rule_version=RULE_VERSION,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def _post_out(post: PlatformPost) -> dict:
    duration = None
    try:
        raw = json.loads(post.raw or "{}")
    except (TypeError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        # 抖音 app/v3 raw.duration 单位为毫秒（如 147469 = 147 秒）
        value = raw.get("duration")
        if isinstance(value, (int, float)) and value:
            duration = round(value / 1000) if value > 1000 else int(value)
    return {
        "post_id": post.id,
        "title": post.title,
        "cover_url": post.cover_url_local,
        "publish_time": post.publish_time,
        "video_url": post.video_url or f"https://www.douyin.com/video/{post.platform_post_id}",
        "duration_seconds": duration,
    }


def list_videos(db: Session, owner: Creator, account_id: int | None, query: str, cursor: int, limit: int) -> dict:
    account = own_account(db, owner, account_id)
    q = db.query(PlatformPost).filter_by(account_id=account.id, platform="douyin")
    if query:
        q = q.filter(PlatformPost.title.contains(query))
    if cursor:
        q = q.filter(PlatformPost.id < cursor)
    # v30：按发布时间倒序（与数据看板一致，默认选中最新一条，避免默认落到同名的私密旧视频）
    rows = q.order_by(PlatformPost.publish_time.desc().nulls_last(), PlatformPost.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    latest_map: dict[int, VideoReview] = {}
    status_map: dict[int, tuple[str, str]] = {}
    stat_map: dict[int, PlatformPostStat] = {}
    if page:
        from sqlalchemy import and_, func

        from ..models.video_review import DouyinPostMetric
        from .douyin_dashboard import post_status

        sub = (
            db.query(DouyinPostMetric.post_id, func.max(DouyinPostMetric.snapshot_date).label("d"))
            .filter(DouyinPostMetric.post_id.in_([post.id for post in page]))
            .group_by(DouyinPostMetric.post_id)
            .subquery()
        )
        for metric in (
            db.query(DouyinPostMetric)
            .join(sub, and_(DouyinPostMetric.post_id == sub.c.post_id, DouyinPostMetric.snapshot_date == sub.c.d))
            .all()
        ):
            status_map[metric.post_id] = post_status(metric)

        stat_sub = (
            db.query(PlatformPostStat.post_id, func.max(PlatformPostStat.stat_date).label("d"))
            .filter(PlatformPostStat.post_id.in_([post.id for post in page]))
            .group_by(PlatformPostStat.post_id)
            .subquery()
        )
        for stat_row in (
            db.query(PlatformPostStat)
            .join(stat_sub, and_(PlatformPostStat.post_id == stat_sub.c.post_id, PlatformPostStat.stat_date == stat_sub.c.d))
            .all()
        ):
            stat_map[stat_row.post_id] = stat_row
    if page:
        # R-240 S6：一次批量取每帖最新 review（按 id 升序覆盖 → 最大 id 即最新）
        for review in (
            db.query(VideoReview)
            .filter(VideoReview.post_id.in_([post.id for post in page]))
            .order_by(VideoReview.id)
            .all()
        ):
            latest_map[review.post_id] = review
    items = []
    for post in page:
        latest = latest_map.get(post.id)
        status, status_label = status_map.get(post.id, ("unknown", "—"))
        latest_stat = stat_map.get(post.id)
        items.append({
            **_post_out(post),
            "status": status,
            "status_label": status_label,
            "plays": latest_stat.plays if latest_stat else None,
            "likes": latest_stat.likes if latest_stat else None,
            "favorites": latest_stat.favorites if latest_stat else None,
            "shares": latest_stat.shares if latest_stat else None,
            "latest_review_id": latest.id if latest else None,
            "review_status": latest.status if latest else None,
            "latest_sync_at": latest.created_at if latest else post.updated_at,
            "running_task_id": latest.task_id if latest and latest.status == "running" else None,
        })
    from .douyin_account_policy import credential_summary, resolve_data_policy

    policy = resolve_data_policy(db, account)
    return {
        "account": {"id": account.id, "nickname": account.nickname, "avatar": account.avatar},
        "items": items,
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        "credential_status": policy.status,
        "credential": credential_summary(db, account),
        "data_source": policy.source,
    }



def refresh_post_by_policy(db: Session, account: CreatorAccount, post: PlatformPost) -> str:
    """按账号策略刷新一条作品指标（R-239）。

    返回 "creator" / "public"；账号 Cookie 失效抛 CredentialError，不发起任何请求。
    """
    from .douyin_account_policy import resolve_data_policy

    policy = resolve_data_policy(db, account)
    if policy.is_blocked:
        raise CredentialError(policy.reason)
    if policy.is_creator:
        sync_post_creator_data(db, account, post)
        return "creator"
    from .platform.budget import _charge
    from .platform.tikhub import make_client
    from .platform_sync import _write_stat

    client = make_client()
    stats = client.fetch_post_stats("douyin", post.platform_post_id, account)
    _charge(db)
    _write_stat(db, post, stats, source=str(stats.get("source") or "tikhub"))
    return "public"


def run_analysis(db: Session, payload: dict, update) -> dict:
    review_id = int(payload["review_id"])
    review = db.get(VideoReview, review_id)
    if review is None:
        raise LookupError("复盘任务不存在")
    account = db.get(CreatorAccount, review.account_id)
    post = db.get(PlatformPost, review.post_id)
    if account is None or post is None:
        raise LookupError("复盘账号或视频不存在")
    owner = db.get(Creator, account.creator_id)
    if owner is None:
        raise LookupError("主博主不存在")
    try:
        update(10, "检查账号和视频")
        refresh_source = "creator"
        media_info: dict | None = None
        if payload.get("refresh"):
            update(20, "更新抖音数据")
            refresh_source = refresh_post_by_policy(db, account, post)
            # v35：与数据看板手动更新/素材库同步一致——刷新时补视频下载 + ASR 转写
            # （有本地素材按 video_id 提交，素材库本地卡可认领动画；否则按 post_id 下载为新素材）
            update(30, "提交视频下载与转写")
            try:
                from .media_ensure import submit_media_task

                if post.local_video_id:
                    media_info = submit_media_task(db, video_id=post.local_video_id)
                else:
                    media_info = submit_media_task(db, post_id=post.id)
            except Exception as exc:  # noqa: BLE001 媒体补齐失败不影响复盘
                media_info = {"status": "failed", "reason": str(exc)[:200]}
        update(40, "比较相近视频")
        comparison = build_comparison(db, post)
        comments = db.query(PlatformPostComment).filter_by(post_id=post.id).order_by(PlatformPostComment.likes.desc()).all()
        transcript = _transcript(db, post)
        findings = build_findings(comparison, transcript, comments, comparison["charts"]["retention"]["points"])
        update(60, "整理同行和低粉爆款")
        peer_items, peer_charts = peer_references(db, owner)
        low_items = low_fan_references(db, owner)
        comparison["charts"]["peer_comparisons"] = peer_charts
        questions = comment_questions(comments)
        comparison["charts"]["comment_questions"] = questions
        update(65, "生成按指标优化建议")
        advices, advice_model, advice_warning = build_metric_advices(
            db, comparison, transcript, questions, post.title or ""
        )
        comparison["advices"] = advices
        update(75, "生成原因和主题建议")
        findings, model_name, llm_warning = build_attribution(
            db, comparison, transcript, comments, questions, findings, post_title=post.title or ""
        )
        recommendations = recommend_topics(db, owner, post, comparison, comments, peer_items, low_items)
        for index, finding in enumerate(findings):
            finding["comparison_post_ids"] = comparison["comparison"]["post_ids"]
            # metric_evidence/content_evidence/comparison_post_ids 是 JSON 结构，模型列是 Text，必须显式序列化
            db.add(VideoReviewFinding(
                review_id=review.id,
                sort_order=index,
                dimension=finding["dimension"],
                rule_key=finding["rule_key"],
                title=finding["title"],
                judgement_type=finding["judgement_type"],
                verdict=finding.get("verdict", ""),
                conclusion=finding["conclusion"],
                suggestion=finding.get("suggestion", ""),
                target_metric=finding.get("target_metric", "plays"),
                metric_evidence=dumps(finding.get("metric_evidence", [])),
                content_evidence=dumps(finding.get("content_evidence", [])),
                comparison_post_ids=dumps(finding.get("comparison_post_ids", [])),
            ))
        primary = recommendations["primary"]
        primary_row: VideoTopicRecommendation | None = None
        if primary:
            primary_row = VideoTopicRecommendation(review_id=review.id, role="primary", rank=1, **_topic_fields(primary))
            db.add(primary_row)
            db.flush()
        for index, item in enumerate(recommendations["backups"], 1):
            db.add(VideoTopicRecommendation(review_id=review.id, role="backup", rank=index, **_topic_fields(item)))
        for item in recommendations["follow_ups"]:
            db.add(VideoTopicRecommendation(
                review_id=review.id,
                parent_id=primary_row.id if primary_row else None,
                role="follow_up",
                rank=int(item["rank"]),
                **_topic_fields(item),
            ))
        recent = db.query(PlatformPost).filter_by(account_id=account.id).order_by(PlatformPost.publish_time.desc()).limit(10).all()
        comparison["charts"]["follower_topics"] = _follower_topics(db, account)
        review.comparison_count = comparison["comparison"]["count"]
        review.comparison_post_ids = dumps(comparison["comparison"]["post_ids"])
        review.summary = summary_for(comparison, findings)
        review.overall_result = comparison["overall"]
        review.metrics_snapshot = dumps(comparison)
        review.homepage_analysis = dumps(homepage_analysis(account, recent))
        review.new_topics = dumps(recommendations["new_topics"])
        warnings = comparison["warnings"] + ([llm_warning] if llm_warning else [])
        if advice_warning:
            warnings.append(advice_warning)
        if refresh_source == "public":
            warnings.append("当前账号未启用创作者数据，播放量/完播等私有指标暂缺，已使用公开数据")
        if not transcript:
            warnings.append("这条视频暂无转写，暂时不能精细分析具体台词")
        if not primary:
            warnings.append("目前没有足够依据给出可靠首选，可补充评论、转写或同行数据")
        elif recommendations.get("primary_note"):
            warnings.append(str(recommendations["primary_note"]))
        review.warnings = dumps(warnings)
        review.model_name = model_name
        review.status = "partial" if warnings else "done"
        review.completed_at = _app_now()
        db.commit()
        update(100, "复盘完成")
        return {
            "review_id": review.id,
            "post_id": post.id,
            "title": post.title,
            "status": review.status,
            "media": media_info,
            "media_task_id": (media_info or {}).get("task_id"),
        }
    except Exception as exc:
        db.rollback()
        failed = db.get(VideoReview, review_id)
        if failed:
            failed.status = "failed"
            failed.error = str(exc)[:1000]
            failed.completed_at = _app_now()
            db.commit()
        raise


def _topic_fields(item: dict) -> dict:
    return {
        "topic": item["topic"], "reason": item.get("reason", ""), "fit_reason": item.get("fit_reason", ""),
        "evidence": dumps(item.get("evidence", [])), "outline": dumps(item.get("outline", [])),
        "opening_line": item.get("opening_line", ""), "target_metric": item.get("target_metric", "plays"),
        "follow_up_role": item.get("follow_up_role", ""), "source_types": dumps(item.get("source_types", [])),
        "score": item.get("score", 0), "score_detail": dumps(item.get("score_detail", {})),
    }


def _follower_sort(item: dict) -> float:
    value = item.get("follower_per_1k")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _follower_topics(db: Session, account: CreatorAccount) -> list[dict]:
    """R-240 S6：一次批量取 30 条作品的私有指标与最新统计（内存内取最新），不再逐条查库。"""
    from ..models.video_review import DouyinPostMetric

    posts = db.query(PlatformPost).filter_by(account_id=account.id).order_by(PlatformPost.publish_time.desc()).limit(30).all()
    post_ids = [post.id for post in posts]
    if not post_ids:
        return []
    metrics: dict[int, DouyinPostMetric] = {}
    for row_metric in (
        db.query(DouyinPostMetric)
        .filter(DouyinPostMetric.post_id.in_(post_ids))
        .order_by(DouyinPostMetric.snapshot_date)
        .all()
    ):
        metrics[row_metric.post_id] = row_metric
    stats: dict[int, PlatformPostStat] = {}
    for row_stat in (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id.in_(post_ids))
        .order_by(PlatformPostStat.stat_date)
        .all()
    ):
        stats[row_stat.post_id] = row_stat
    rows = []
    for post in posts:
        metric = metrics.get(post.id)
        stat = stats.get(post.id)
        if not metric or metric.follower_gain is None:
            continue
        rows.append({
            "topic": post.title,
            "follower_gain": metric.follower_gain,
            "follower_per_1k": metric.follower_gain / stat.plays * 1000 if stat and stat.plays else None,
            "sample_count": 1,
        })
    return sorted(rows, key=_follower_sort, reverse=True)[:8]


def _finding_out(row: VideoReviewFinding) -> dict:
    return {
        "id": row.id, "dimension": row.dimension, "rule_key": row.rule_key, "title": row.title,
        "judgement_type": row.judgement_type, "verdict": row.verdict, "conclusion": row.conclusion,
        "suggestion": row.suggestion, "target_metric": row.target_metric,
        "metric_evidence": loads(row.metric_evidence, []), "content_evidence": loads(row.content_evidence, []),
        "comparison_post_ids": loads(row.comparison_post_ids, []),
    }


def _topic_out(row: VideoTopicRecommendation) -> dict:
    return {
        "id": row.id, "role": row.role, "rank": row.rank, "topic": row.topic, "reason": row.reason,
        "fit_reason": row.fit_reason, "evidence": loads(row.evidence, []), "outline": loads(row.outline, []),
        "opening_line": row.opening_line, "target_metric": row.target_metric, "follow_up_role": row.follow_up_role,
        "source_types": loads(row.source_types, []), "score": row.score, "score_detail": loads(row.score_detail, {}),
    }


_EMPTY_CHARTS: dict = {
    "comparison": [],
    "retention": {"points": [], "reliable": False, "plays": None, "has_timed_transcript": False},
    "traffic": [],
    "search_terms": [],
    "comment_questions": [],
    "follower_topics": [],
    "peer_comparisons": [],
}


def review_out(db: Session, review: VideoReview) -> dict:
    post = db.get(PlatformPost, review.post_id)
    snapshot = loads(review.metrics_snapshot, {})
    topics = db.query(VideoTopicRecommendation).filter_by(review_id=review.id).order_by(VideoTopicRecommendation.id).all()
    # 失败/历史复盘可能没有图表快照，也必须返回完整 charts 结构，避免前端 undefined.filter 崩溃
    charts = {**_EMPTY_CHARTS, **(snapshot.get("charts") or {})}
    # R-247：改进计划已删除，历史快照里可能残留 plan 键，读取侧统一去掉（不清理历史 JSON）
    charts.pop("plan", None)
    return {
        "id": review.id,
        "status": review.status,
        "error": review.error,
        "post": _post_out(post) if post else None,
        "data_time": review.created_at,
        "summary": review.summary,
        "overall_result": review.overall_result,
        "comparison": {
            "count": review.comparison_count,
            "post_ids": loads(review.comparison_post_ids, []),
            "sample_note": snapshot.get("comparison", {}).get("sample_note", ""),
        },
        "metrics": snapshot.get("metrics", []),
        "advices": snapshot.get("advices", []),
        "findings": [_finding_out(x) for x in db.query(VideoReviewFinding).filter_by(review_id=review.id).order_by(VideoReviewFinding.sort_order).all()],
        "follower_analysis": {"strong_topics": charts.get("follower_topics", []), "homepage": loads(review.homepage_analysis, {})},
        "recommendations": {
            "primary": next((_topic_out(x) for x in topics if x.role == "primary"), None),
            "backups": [_topic_out(x) for x in topics if x.role == "backup"],
            "follow_ups": [_topic_out(x) for x in topics if x.role == "follow_up"],
        },
        "new_topics": loads(review.new_topics, []),
        "charts": charts,
        "warnings": loads(review.warnings, []),
        "model_name": review.model_name,
        "created_at": review.created_at,
        "completed_at": review.completed_at,
    }


def refresh_reference_worker(db: Session, payload: dict, update) -> dict:
    owner = db.get(Creator, int(payload["owner_id"]))
    if owner is None:
        raise LookupError("主博主不存在")
    update(20, "获取低粉爆款")
    result = refresh_references(db, owner, payload.get("filters") or {})
    update(70, "补齐同行作品播放量")
    from .douyin_creator_sync import backfill_peer_plays

    peer = backfill_peer_plays(db, owner)
    warnings = list(result.get("warnings") or []) + list(peer.get("warnings") or [])
    update(100, "参考视频已更新")
    return {**result, "peer_plays": peer, "warnings": warnings}


def reference_items(db: Session, owner: Creator, kind: str, keyword: str, limit: int) -> list[dict]:
    if kind == "peer":
        return peer_references(db, owner, limit)[0]
    return low_fan_references(db, owner, keyword, limit)
