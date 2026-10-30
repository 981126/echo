from __future__ import annotations

import math

from sqlalchemy.orm import Session

from ..models.persona import PersonaTag
from ..models.platform import Creator, PlatformPost, PlatformPostComment
from ..models.video import Transcript, Video
from .video_review_comparison import loads
from .video_review_rules import comment_questions


def _keywords(db: Session, owner: Creator) -> set[str]:
    result = {"求职", "面试", "赚钱", "知识"}
    for video in db.query(Video).filter_by(creator_id=owner.id).all():
        for value in loads(video.main_topics, []) + loads(video.tags, []):
            if str(value).strip():
                result.add(str(value).strip().lower())
    return result


def _has_material(db: Session, owner: Creator) -> bool:
    """是否有「视频 + 非空转写」的素材（一次 JOIN 查询，避免逐视频懒加载 transcript）。"""
    row = (
        db.query(Transcript.id)
        .join(Video, Video.id == Transcript.video_id)
        .filter(Video.creator_id == owner.id)
        .filter((Transcript.corrected_text != "") | (Transcript.transcript_text != ""))
        .first()
    )
    return row is not None


def _fit(
    db: Session,
    owner: Creator,
    topic: str,
    *,
    keywords: set[str] | None = None,
    has_material: bool | None = None,
    persona: list[PersonaTag] | None = None,
) -> tuple[int, list[str]]:
    """人设契合度打分（R-240 S6：循环外预算好的 keywords/has_material/persona 可直接传入）。"""
    words = _keywords(db, owner) if keywords is None else keywords
    related = [word for word in words if word.lower() in topic.lower()]
    score = 8 if related else 0
    reasons = [f"与你讲过的{'、'.join(related[:2])}内容相关"] if related else []
    confirmed = persona if persona is not None else db.query(PersonaTag).filter_by(creator_id=owner.id, status="confirmed").all()
    persona_matches = [p for p in confirmed if p.layer != "forbidden" and any(word in (p.label + p.description + topic) for word in related)]
    if persona_matches:
        score += 6
        reasons.append(f"符合你的人设「{persona_matches[0].label}」")
    material = _has_material(db, owner) if has_material is None else has_material
    if material:
        score += 6
        reasons.append("你已有真实视频和转写可以作为内容依据")
    if any(p.layer == "forbidden" and p.label and p.label in topic for p in confirmed):
        return 0, ["命中人设禁区"]
    return score, reasons


def _candidate(topic: str, source_types: list[str], evidence: list[dict], target_metric: str = "plays") -> dict:
    return {"topic": topic.strip(), "source_types": source_types, "evidence": evidence, "target_metric": target_metric}


def _score(
    db: Session,
    owner: Creator,
    candidate: dict,
    facts: dict,
    comment_count: int,
    comment_likes: int,
    *,
    keywords: set[str] | None = None,
    has_material: bool | None = None,
    persona: list[PersonaTag] | None = None,
) -> dict:
    follower = 0
    if "own_results" in candidate["source_types"]:
        if facts["follower_per_1k"]["state"] == "high":
            follower += 20
        if facts["follower_gain"]["state"] == "high":
            follower += 10
    demand = 0
    if "audience_comment" in candidate["source_types"]:
        demand = min(15, round(3 * math.log2(1 + comment_count))) + min(5, round(math.log2(1 + comment_likes)))
    fit, fit_reasons = _fit(
        db,
        owner,
        candidate["topic"],
        keywords=keywords,
        has_material=has_material,
        persona=persona,
    )
    public = min(10, sum(1 for x in candidate["source_types"] if x == "peer") * 5) + min(5, sum(1 for x in candidate["source_types"] if x == "low_fan") * 2)
    fresh = 10 if candidate["source_types"] else 0
    score = max(0, follower + demand + fit + public + fresh)
    return {
        "follower": follower,
        "demand": demand,
        "fit": fit,
        "public": public,
        "freshness": fresh,
        "total": score,
        "fit_reasons": fit_reasons,
    }


def recommend_topics(
    db: Session,
    owner: Creator,
    post: PlatformPost,
    comparison: dict,
    comments: list[PlatformPostComment],
    peer_items: list[dict],
    low_fan_items: list[dict],
) -> dict:
    facts = comparison["facts"]
    candidates: list[dict] = []
    if post.title and ("high" in (facts["follower_gain"]["state"], facts["follower_per_1k"]["state"], facts["plays"]["state"])):
        candidates.append(_candidate(
            post.title,
            ["own_content", "own_results"],
            [{"evidence_id": f"post:{post.id}", "title": post.title, "reason": "这条自己的视频已有较好数据"}],
            "followers" if "high" in (facts["follower_gain"]["state"], facts["follower_per_1k"]["state"]) else "plays",
        ))
    questions = comment_questions(comments)
    for question in questions:
        candidates.append(_candidate(
            question["group_title"],
            ["audience_comment", "own_content"],
            [{"evidence_id": f"comment:{question['comment_ids'][0]}", "comments": question["comments"], "reason": "观众在原评论中追问"}],
            "followers",
        ))
    for item in peer_items[:8]:
        candidates.append(_candidate(
            item["title"], ["peer"],
            [{"evidence_id": item["id"], "title": item["title"], "reason": f"播放是该同行平时的{item['verdict_evidence']['play_multiple']}倍"}],
        ))
    for item in low_fan_items[:8]:
        if item["relevance"] < 40:
            continue
        candidates.append(_candidate(
            item["title"], ["low_fan"],
            [{"evidence_id": item["id"], "title": item["title"], "reason": "官方低粉爆款，且与你的内容相关"}],
        ))
    unique: dict[str, dict] = {}
    for candidate in candidates:
        key = "".join(candidate["topic"].lower().split())
        if not key:
            continue
        if key in unique:
            unique[key]["source_types"] = sorted(set(unique[key]["source_types"] + candidate["source_types"]))
            unique[key]["evidence"].extend(candidate["evidence"])
        else:
            unique[key] = candidate
    # R-240 S6：人设关键词/素材/确认标签循环外各算一次，循环内纯计算
    keywords = _keywords(db, owner)
    has_material = _has_material(db, owner)
    persona = db.query(PersonaTag).filter_by(creator_id=owner.id, status="confirmed").all()
    question_count = sum(x["commenter_count"] for x in questions)
    question_likes = sum(x["likes"] for x in questions)
    scored = []
    for candidate in unique.values():
        detail = _score(
            db,
            owner,
            candidate,
            facts,
            question_count,
            question_likes,
            keywords=keywords,
            has_material=has_material,
            persona=persona,
        )
        if detail["fit"] <= 0:
            continue
        candidate["score_detail"] = detail
        candidate["score"] = detail["total"]
        candidate["fit_reason"] = "；".join(detail["fit_reasons"]) or "与你的现有内容有一定关联"
        candidate["reason"] = "；".join(dict.fromkeys(e["reason"] for e in candidate["evidence"]))
        scored.append(candidate)
    scored.sort(key=lambda x: (x["score"], x["score_detail"]["follower"], x["score_detail"]["demand"]), reverse=True)
    primary = next((x for x in scored if len(x["source_types"]) >= 2 and x["score_detail"]["fit"] >= 12), None)
    primary_note = ""
    if primary is None:
        # 真实数据冒烟：多数账号暂时只有「同行公开爆款」单一依据，仍应给出 1 个首选 + 2 个备选，
        # 但要明确标注依据有限，避免页面永远没有首选。
        primary = next((x for x in scored if x["score_detail"]["fit"] >= 12 and x["score"] >= 20), None)
        if primary is not None:
            primary_note = "首选主要依据同行公开爆款，建议补充本条转写、评论和涨粉数据后再确认"
    backups = [x for x in scored if x is not primary][:2]
    follow_ups = []
    if primary:
        roles = ("吸引新观众", "帮助了解作者", "加强关注理由")
        templates = ("最常见的问题怎么解决", "容易犯的错误和避免方法", "可以照着做的具体步骤")
        for index, (role, suffix) in enumerate(zip(roles, templates), 1):
            follow_ups.append({
                "topic": f"{primary['topic']}：{suffix}", "role": "follow_up", "rank": index,
                "reason": f"延续首选主题，{role}", "fit_reason": primary["fit_reason"],
                "evidence": primary["evidence"], "outline": ["先回答一个具体问题", "再给出你的真实经验或已有素材", "最后说明下一条继续讲什么"],
                "opening_line": f"很多人还在问{primary['topic']}，这次直接讲{suffix}。",
                "target_metric": primary["target_metric"], "follow_up_role": role,
                "source_types": primary["source_types"], "score": primary["score"], "score_detail": primary["score_detail"],
            })
    used = {id(x) for x in [primary, *backups] if x}
    new_topics = [
        {
            "topic": x["topic"], "reason": x["reason"], "fit_reason": x["fit_reason"],
            "evidence": x["evidence"], "first_step": f"先围绕“{x['topic']}”回答一个具体问题",
            "target_metric": x["target_metric"],
        }
        for x in scored if id(x) not in used
    ][:3]
    return {"primary": primary, "backups": backups, "follow_ups": follow_ups, "new_topics": new_topics, "primary_note": primary_note}
