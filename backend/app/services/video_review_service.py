from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from ..core.timeutil import now as _app_now
from ..models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostComment, PlatformPostStat
from ..models.video import Video
from ..models.video_review import (
    VideoImprovementPlan,
    VideoReview,
    VideoReviewFinding,
    VideoTopicRecommendation,
)
from .creator_service import get_current_creator
from .douyin_creator_sync import CredentialError, sync_post_creator_data
from .douyin_references import refresh_references
from .video_review_comparison import build_comparison, dumps, loads, low_fan_references, peer_references
from .video_review_llm import enhance_findings
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
    rows = q.order_by(PlatformPost.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    latest_map: dict[int, VideoReview] = {}
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
        items.append({
            **_post_out(post),
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
        if payload.get("refresh"):
            update(20, "更新抖音数据")
            refresh_source = refresh_post_by_policy(db, account, post)
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
        update(75, "生成原因和主题建议")
        findings, model_name, llm_warning = enhance_findings(db, findings)
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
        return {"review_id": review.id, "post_id": post.id, "title": post.title, "status": review.status}
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
        "judgement_type": row.judgement_type, "conclusion": row.conclusion,
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
        "adopted_at": row.adopted_at,
    }


_EMPTY_CHARTS: dict = {
    "comparison": [],
    "retention": {"points": [], "reliable": False, "plays": None, "has_timed_transcript": False},
    "traffic": [],
    "search_terms": [],
    "comment_questions": [],
    "follower_topics": [],
    "peer_comparisons": [],
    "plan": [],
}


def review_out(db: Session, review: VideoReview) -> dict:
    post = db.get(PlatformPost, review.post_id)
    snapshot = loads(review.metrics_snapshot, {})
    topics = db.query(VideoTopicRecommendation).filter_by(review_id=review.id).order_by(VideoTopicRecommendation.id).all()
    plan = db.query(VideoImprovementPlan).filter_by(review_id=review.id).order_by(VideoImprovementPlan.id.desc()).first()
    # 失败/历史复盘可能没有图表快照，也必须返回完整 charts 结构，避免前端 undefined.filter 崩溃
    charts = {**_EMPTY_CHARTS, **(snapshot.get("charts") or {})}
    if plan:
        charts["plan"] = loads(plan.check_result, {}).get("items", [])
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
        "findings": [_finding_out(x) for x in db.query(VideoReviewFinding).filter_by(review_id=review.id).order_by(VideoReviewFinding.sort_order).all()],
        "follower_analysis": {"strong_topics": charts.get("follower_topics", []), "homepage": loads(review.homepage_analysis, {})},
        "recommendations": {
            "primary": next((_topic_out(x) for x in topics if x.role == "primary"), None),
            "backups": [_topic_out(x) for x in topics if x.role == "backup"],
            "follow_ups": [_topic_out(x) for x in topics if x.role == "follow_up"],
        },
        "new_topics": loads(review.new_topics, []),
        "improvement_plan": plan_out(plan) if plan else None,
        "charts": charts,
        "warnings": loads(review.warnings, []),
        "model_name": review.model_name,
        "created_at": review.created_at,
        "completed_at": review.completed_at,
    }


def plan_out(plan: VideoImprovementPlan) -> dict:
    return {
        "id": plan.id, "review_id": plan.review_id, "source_post_id": plan.source_post_id,
        "recommendation_id": plan.recommendation_id, "kept_text": plan.kept_text,
        "changes": loads(plan.changes, []), "target_metrics": loads(plan.target_metrics, []),
        "status": plan.status, "published_post_id": plan.published_post_id,
        "check_result": loads(plan.check_result, {}), "checked_at": plan.checked_at,
        "created_at": plan.created_at, "updated_at": plan.updated_at,
    }


def adopt_topic(db: Session, recommendation: VideoTopicRecommendation, payload: dict) -> VideoImprovementPlan:
    changes = [str(x).strip() for x in payload.get("changes", []) if str(x).strip()]
    targets = [str(x) for x in payload.get("target_metrics", []) if str(x)]
    if not 1 <= len(changes) <= 2:
        raise ValueError("请记录1～2项重点修改")
    if not targets:
        raise ValueError("请至少选择一个主要观察指标")
    plan = db.query(VideoImprovementPlan).filter_by(recommendation_id=recommendation.id).first()
    if plan is None:
        review = db.get(VideoReview, recommendation.review_id)
        if review is None:
            raise LookupError("推荐所属复盘不存在")
        plan = VideoImprovementPlan(review_id=recommendation.review_id, source_post_id=review.post_id, recommendation_id=recommendation.id)
        db.add(plan)
    plan.kept_text = str(payload.get("kept_text") or "")
    plan.changes = dumps(changes)
    plan.target_metrics = dumps(targets)
    plan.status = "linked" if plan.published_post_id else "recorded"
    plan.check_result = "{}"
    recommendation.adopted_at = _app_now()
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db: Session, plan: VideoImprovementPlan, payload: dict) -> VideoImprovementPlan:
    if not any(key in payload for key in ("kept_text", "changes", "target_metrics")):
        raise ValueError("至少修改一项内容")
    if "kept_text" in payload:
        plan.kept_text = str(payload["kept_text"] or "")
    if "changes" in payload:
        changes = [str(x).strip() for x in payload["changes"] if str(x).strip()]
        if not 1 <= len(changes) <= 2:
            raise ValueError("请记录1～2项重点修改")
        plan.changes = dumps(changes)
    if "target_metrics" in payload:
        if not payload["target_metrics"]:
            raise ValueError("请至少选择一个主要观察指标")
        plan.target_metrics = dumps(payload["target_metrics"])
    plan.status = "linked" if plan.published_post_id else "recorded"
    plan.check_result = "{}"
    db.commit()
    return plan


def link_plan(db: Session, plan: VideoImprovementPlan, published: PlatformPost, replace: bool) -> VideoImprovementPlan:
    source = db.get(PlatformPost, plan.source_post_id)
    if source is None or published.account_id != source.account_id:
        raise ValueError("只能关联同一抖音账号的视频")
    if published.publish_time and published.publish_time < plan.created_at:
        raise ValueError("新视频发布时间早于修改计划，请确认是否选错")
    if plan.published_post_id and plan.published_post_id != published.id and not replace:
        raise RuntimeError("已关联另一条视频，确认替换后才能继续")
    plan.published_post_id = published.id
    plan.status = "linked"
    plan.check_result = "{}"
    db.commit()
    return plan


def run_plan_check(db: Session, payload: dict, update) -> dict:
    plan = db.get(VideoImprovementPlan, int(payload["plan_id"]))
    if plan is None or not plan.published_post_id:
        raise ValueError("请先关联已发布视频")
    published = db.get(PlatformPost, plan.published_post_id)
    if published is None:
        raise LookupError("关联的新视频不存在")
    account = db.get(CreatorAccount, published.account_id)
    if account is None:
        raise LookupError("新视频账号不存在")
    update(25, "更新新视频数据")
    if payload.get("refresh"):
        refresh_post_by_policy(db, account, published)
    update(60, "比较修改前后数据")
    before_review = db.get(VideoReview, plan.review_id)
    if before_review is None:
        raise LookupError("原复盘不存在")
    before = loads(before_review.metrics_snapshot, {}).get("facts", {})
    after = build_comparison(db, published)["facts"]
    items = []
    for key in loads(plan.target_metrics, []):
        old = before.get(key, {})
        new = after.get(key, {})
        result = "uncertain"
        reason = "缺少可比较数据"
        if old.get("value") is not None and new.get("value") is not None:
            av, bv = float(old["value"]), float(new["value"])
            if old.get("unit") == "ratio":
                difference = bv - av
                if abs(difference) >= 0.03:
                    result = "improved" if difference > 0 else "not_improved"
                    reason = f"变化{difference * 100:+.1f}个百分点"
                else:
                    reason = "变化小于3个百分点"
            elif av == 0:
                result = "improved" if bv > 0 else "uncertain"
                reason = f"从0变为{bv:g}"
            else:
                difference = (bv - av) / abs(av)
                if abs(difference) >= 0.2:
                    result = "improved" if difference > 0 else "not_improved"
                    reason = f"变化{difference * 100:+.1f}%"
                else:
                    reason = "变化小于20%"
            if key == "bounce_2s_rate" and result != "uncertain":
                result = "improved" if result == "not_improved" else "not_improved"
        items.append({"metric": key, "label": new.get("label") or old.get("label") or key, "unit": new.get("unit") or old.get("unit"), "before": old.get("value"), "after": new.get("value"), "result": result, "reason": reason})
    plan.check_result = dumps({"status": "checked", "items": items, "comparison_days": after.get("plays", {}).get("sample_count")})
    plan.status = "checked"
    plan.checked_at = _app_now()
    db.commit()
    update(100, "检查完成")
    return {"plan_id": plan.id, "items": items}


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
