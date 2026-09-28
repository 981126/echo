"""内容机会引擎接口（R-185）：观众提问榜 / 每周灵感包 / 选题账本。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import opportunity

router = APIRouter()


@router.get("/comments", response_model=dict)
def comment_clusters(limit: int = 15, use_llm: bool = True, db: Session = Depends(get_db)):
    """观众提问榜：未使用评论聚类，按需求分排序。

    R-192：默认用**模型1 语义聚类**（use_llm=true）；失败自动回退本地聚类；use_llm=false 强制本地。
    """
    return opportunity.comment_clusters(db, limit=max(1, min(limit, 50)), use_llm=use_llm)


@router.get("/weekly", response_model=dict)
def weekly_pack(limit: int = 20, db: Session = Depends(get_db)):
    """每周灵感补给包：需求 × 人设 × 热度 × 缺口 综合打分，去重去已讲。"""
    return opportunity.weekly_pack(db, limit=max(1, min(limit, 40)))


@router.get("/ledger", response_model=dict)
def topic_ledger(limit: int = 50, db: Session = Depends(get_db)):
    """选题账本：已讲过的话题与「可能已讲」的池中灵感。"""
    return opportunity.ledger(db, limit=max(1, min(limit, 200)))


@router.get("/gap", response_model=dict)
def gap_suggestions(limit: int = 6, db: Session = Depends(get_db)):
    """缺口选题（R-187）：AI 基于「已讲话题 + 人设」给出该讲但没讲过的选题。"""
    return opportunity.gap_suggestions(db, limit=max(1, min(limit, 12)))


@router.get("/covered", response_model=dict)
def covered_titles(limit: int = 300, db: Session = Depends(get_db)):
    """已讲过的话题标题（R-191，轻量）：供前端给灵感列表标「可能已讲」。"""
    return opportunity.covered(db, limit=max(1, min(limit, 800)))


@router.get("/attribution", response_model=dict)
def topic_attribution(limit: int = 15, db: Session = Depends(get_db)):
    """选题归因（R-192）：按标签聚合已发布稿件的表现，看出哪类选题数据好。"""
    return opportunity.topic_attribution(db, limit=max(1, min(limit, 50)))
