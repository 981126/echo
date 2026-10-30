from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.platform import CreatorAccount, PlatformPost
from ..models.video_review import VideoImprovementPlan, VideoReview, VideoTopicRecommendation
from ..schemas.douyin_review import (
    AnalyzeIn,
    CredentialIn,
    HomepageIn,
    PlanCheckIn,
    PlanIn,
    PlanLinkIn,
    PlanPatchIn,
    ReferenceRefreshIn,
)
from ..services import video_review_service as service
from ..services.douyin_creator_sync import CredentialError, credential_out, save_credential
from ..tasks import find_running_task, start_task

router = APIRouter()


def _call(fn):
    try:
        return fn()
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/videos", response_model=dict)
def videos(
    account_id: int | None = None,
    query: str = Query(default="", max_length=100),
    cursor: int = 0,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return _call(lambda: service.list_videos(db, service.current_owner(db), account_id, query, cursor, limit))


@router.post("/analyze", response_model=dict)
def analyze(payload: AnalyzeIn, db: Session = Depends(get_db)):
    def run():
        owner = service.current_owner(db)
        _, post = service.own_post(db, owner, payload.post_id)
        existing_task = find_running_task("douyin_review_analyze", {"post_id": post.id})
        if existing_task:
            existing = db.query(VideoReview).filter_by(post_id=post.id, status="running").order_by(VideoReview.id.desc()).first()
            return JSONResponse(status_code=202, content={"task_id": existing_task, "review_id": existing.id if existing else None, "reused": True})
        fingerprint = service.fingerprint_for(db, post)
        if not payload.force and not payload.refresh:
            # 已完成（含数据不足的 partial）且输入指纹一致 → 直接复用，避免重复扣 AI 额度
            existing = (
                db.query(VideoReview)
                .filter(VideoReview.post_id == post.id, VideoReview.input_fingerprint == fingerprint, VideoReview.status.in_(("done", "partial")))
                .order_by(VideoReview.id.desc())
                .first()
            )
            if existing:
                return {"task_id": existing.task_id, "review_id": existing.id, "reused": True, "review": service.review_out(db, existing)}
        review = service.create_review(db, owner, post)
        task_id = start_task(
            "douyin_review_analyze",
            {"review_id": review.id, "post_id": post.id, "account_id": post.account_id, "refresh": payload.refresh},
            service.run_analysis,
        )
        review.task_id = task_id
        db.commit()
        return JSONResponse(status_code=202, content={"task_id": task_id, "review_id": review.id, "reused": False})

    return _call(run)


@router.get("/reviews/{review_id}", response_model=dict)
def get_review(review_id: int, db: Session = Depends(get_db)):
    def run():
        review = db.get(VideoReview, review_id)
        if review is None:
            raise LookupError("复盘不存在")
        service.own_post(db, service.current_owner(db), review.post_id)
        return service.review_out(db, review)

    return _call(run)


@router.get("/posts/{post_id}/latest-review", response_model=dict)
def latest_review(post_id: int, db: Session = Depends(get_db)):
    def run():
        service.own_post(db, service.current_owner(db), post_id)
        latest = db.query(VideoReview).filter_by(post_id=post_id).order_by(VideoReview.id.desc()).first()
        running = find_running_task("douyin_review_analyze", {"post_id": post_id})
        failed = latest if latest is not None and latest.status == "failed" else None
        review = latest
        if failed is not None:
            # 失败不覆盖上一次成功分析：返回上一次成功结果 + 本次失败原因
            review = (
                db.query(VideoReview)
                .filter(VideoReview.post_id == post_id, VideoReview.status.in_(("done", "partial")))
                .order_by(VideoReview.id.desc())
                .first()
            )
        payload = {
            "review": service.review_out(db, review) if review else None,
            "running_task_id": running,
            "failed_review": {"id": failed.id, "error": failed.error, "created_at": failed.created_at, "task_id": failed.task_id} if failed else None,
        }
        return payload

    return _call(run)


@router.get("/references", response_model=dict)
def references(
    kind: str,
    keyword: str = "",
    category_id: str = "0",
    date_days: int = 7,
    duration_type: int = 0,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    if kind not in ("peer", "low_fan"):
        raise HTTPException(status_code=422, detail="kind 只支持 peer 或 low_fan")
    owner = service.current_owner(db)
    items = service.reference_items(db, owner, kind, keyword, limit)
    warnings: list[str] = []
    # 低粉榜是「近 N 天热门」榜，作品发布时间可能更早，不能按发布时间二次过滤（真实联调会误删大部分条目）
    if not items:
        if kind == "peer":
            warnings.append("暂无符合规则的同行爆款：请先在博主管理添加抖音同行并同步数据；同行作品播放量需要在「低粉爆款 → 更新」时一并补齐")
        else:
            warnings.append("当前条件下暂无低粉爆款，可点击更新获取")
    return {"items": items, "warnings": warnings}


@router.post("/references/refresh", response_model=dict)
def refresh_references(payload: ReferenceRefreshIn, db: Session = Depends(get_db)):
    if payload.date_window not in (1, 24, 72, 168):
        raise HTTPException(status_code=400, detail="时间窗口只支持1/24/72/168小时")
    if payload.duration_type not in (0, 1, 6, 7, 8, 9):
        raise HTTPException(status_code=400, detail="时长筛选只支持0/1/6/7/8/9")
    if payload.tags and any(not isinstance(tag, dict) or "value" not in tag for tag in payload.tags):
        raise HTTPException(status_code=400, detail="tags 必须是 [{value, children}] 结构")
    owner = service.current_owner(db)
    filters = payload.model_dump()
    task_id = find_running_task("douyin_review_references", {"owner_id": owner.id})
    reused = bool(task_id)
    if not task_id:
        task_id = start_task(
            "douyin_review_references",
            {"owner_id": owner.id, "filters": filters},
            service.refresh_reference_worker,
        )
    return JSONResponse(status_code=202, content={"task_id": task_id, "reused": reused})


@router.get("/credentials", response_model=dict)
def credentials(account_id: int, db: Session = Depends(get_db)):
    return _call(lambda: credential_out(db, service.own_account(db, service.current_owner(db), account_id).id))


@router.put("/credentials", response_model=dict)
def save_credentials(payload: CredentialIn, db: Session = Depends(get_db)):
    account = service.own_account(db, service.current_owner(db), payload.account_id)
    return _call(lambda: save_credential(db, account, payload.cookie))


@router.post("/recommendations/{recommendation_id}/adopt", response_model=dict)
def adopt(recommendation_id: int, payload: PlanIn, db: Session = Depends(get_db)):
    def run():
        recommendation = db.get(VideoTopicRecommendation, recommendation_id)
        if recommendation is None:
            raise LookupError("主题推荐不存在")
        review = db.get(VideoReview, recommendation.review_id)
        service.own_post(db, service.current_owner(db), review.post_id)
        plan = service.adopt_topic(db, recommendation, payload.model_dump())
        return {"plan_id": plan.id, "recommendation_id": recommendation.id, "status": plan.status, "adopted_at": recommendation.adopted_at}

    return _call(run)


@router.patch("/plans/{plan_id}", response_model=dict)
def patch_plan(plan_id: int, payload: PlanPatchIn, db: Session = Depends(get_db)):
    def run():
        plan = _plan(db, plan_id)
        clean = {key: value for key, value in payload.model_dump().items() if value is not None}
        return service.plan_out(service.update_plan(db, plan, clean))

    return _call(run)


@router.post("/plans/{plan_id}/link", response_model=dict)
def link_plan(plan_id: int, payload: PlanLinkIn, db: Session = Depends(get_db)):
    def run():
        plan = _plan(db, plan_id)
        published = db.get(PlatformPost, payload.published_post_id)
        if published is None:
            raise LookupError("新发布视频不存在")
        service.own_post(db, service.current_owner(db), published.id)
        plan = service.link_plan(db, plan, published, payload.replace)
        return {"plan_id": plan.id, "status": plan.status, "published_post_id": plan.published_post_id}

    return _call(run)


@router.post("/plans/{plan_id}/check", response_model=dict)
def check_plan(plan_id: int, payload: PlanCheckIn, db: Session = Depends(get_db)):
    plan = _plan(db, plan_id)
    if not plan.published_post_id:
        raise HTTPException(status_code=409, detail="请先关联已发布视频")
    task_id = find_running_task("douyin_review_plan_check", {"plan_id": plan.id})
    if not task_id:
        task_id = start_task(
            "douyin_review_plan_check",
            {"plan_id": plan.id, "refresh": payload.refresh},
            service.run_plan_check,
        )
    return JSONResponse(status_code=202, content={"task_id": task_id})


@router.get("/plans", response_model=dict)
def plans(post_id: int | None = None, limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    owner = service.current_owner(db)
    query = db.query(VideoImprovementPlan).join(VideoReview, VideoImprovementPlan.review_id == VideoReview.id)
    if post_id:
        service.own_post(db, owner, post_id)
        query = query.filter(VideoImprovementPlan.source_post_id == post_id)
    else:
        account_ids = [x.id for x in db.query(CreatorAccount).filter_by(creator_id=owner.id, platform="douyin").all()]
        query = query.filter(VideoReview.account_id.in_(account_ids or [0]))
    rows = query.order_by(VideoImprovementPlan.id.desc()).limit(limit).all()
    return {"items": [service.plan_out(x) for x in rows]}


@router.put("/homepage", response_model=dict)
def homepage(payload: HomepageIn, db: Session = Depends(get_db)):
    account = service.own_account(db, service.current_owner(db), payload.account_id)
    for post_id in payload.pinned_post_ids:
        post = db.get(PlatformPost, post_id)
        if post is None or post.account_id != account.id:
            raise HTTPException(status_code=400, detail="置顶视频必须属于当前抖音账号")
    extra = account.extra()
    extra["review_homepage"] = {
        "bio": payload.bio,
        "pinned_post_ids": payload.pinned_post_ids,
        "direction_note": payload.direction_note,
    }
    account.extra_config = json.dumps(extra, ensure_ascii=False)
    db.commit()
    return {**extra["review_homepage"], "account_id": account.id, "source": "author", "updated_at": account.last_sync_at}


def _plan(db: Session, plan_id: int) -> VideoImprovementPlan:
    plan = db.get(VideoImprovementPlan, plan_id)
    if plan is None:
        raise LookupError("修改计划不存在")
    service.own_post(db, service.current_owner(db), plan.source_post_id)
    return plan
