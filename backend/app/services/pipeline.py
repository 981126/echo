"""每日流水线（R-073）：候选按三槽组合 —— 评论区 1 + 热榜 1 + AI 建议 1，均需符合人设。

流程：抓热点 → 组装三槽候选 → 逐篇生成（完整人设/风格上下文）→ 写 TopicCandidate(slot) → 邮件。
幂等：当天已成功且非 force 不重跑；失败可重试。
"""

from __future__ import annotations

import datetime as _dt
import json
import re

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.matching import keyword_fallback_match
from ..core.pipeline import can_run, today_key
from ..core.topics import MAIN_TOPICS
from ..models.hot_topic import TopicCandidate, TopicIdea
from ..models.pipeline import PipelineRun
from .creator_service import current_creator_id
from .generation import generate_draft
from .ideas_service import annotate_items, persona_profile
from .llm import LLMError
from .notify import send_daily_digest, send_failure_alert
from .persona import PersonaService
from .topic_mining import fetch_and_store

SLOT_COMMENT = "comment"
SLOT_HOT = "hot"
SLOT_AI = "ai"
SLOT_LABEL = {SLOT_COMMENT: "评论区", SLOT_HOT: "热榜", SLOT_AI: "AI 建议"}

_PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()【】\[\]《》<>#＃\-—…]+")


def _title_key(title: str) -> str:
    return _PUNCT_RE.sub("", title or "").strip().lower()


def _dedupe_candidates(cands: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in cands:
        k = _title_key(c.get("title", ""))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def _match_candidates(db: Session, hot_items: list[dict], settings) -> list[dict]:
    """人设×热点匹配（兜底/补充用）：先试 LLM，失败/无密钥时用关键词兜底。"""
    persona = PersonaService()
    confirmed_keywords = []
    from ..models.persona import PersonaTag

    for t in (
        db.query(PersonaTag)
        .filter(PersonaTag.status == "confirmed", PersonaTag.category != "redline")
        .all()
    ):
        confirmed_keywords.append(t.label)
    confirmed_keywords += ["求职", "面试", "赚钱", "知识"]

    try:
        items_text = "\n".join(
            f"- [{i['platform']}] {i['title']} (热度:{i.get('heat','')})" for i in hot_items
        )
        tags = "\n".join(f"- {t}" for t in confirmed_keywords) or "（无）"
        system = (
            "你是自媒体选题匹配专家。从热点列表中挑出最匹配作者人设和赛道的选题，"
            "改写为更贴合作者的标题。只输出 JSON："
            '{"candidates":[{"title":"改写后的选题","platform":"来源平台",'
            '"score":0-100,"reason":"为什么匹配"}]}'
        )
        user = f"作者赛道/风格关键词：\n{tags}\n\n今日热点：\n{items_text}"
        data = persona.llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.4,
        )
        cands = []
        for c in data.get("candidates") or []:
            title = str(c.get("title", "")).strip() if isinstance(c, dict) else ""
            if title:
                cands.append(
                    {
                        "title": title,
                        "platform": str(c.get("platform", "")),
                        "score": max(0, min(100, int(c.get("score") or 0))),
                        "reason": str(c.get("reason", "")),
                        "slot": "",
                    }
                )
        if cands:
            return cands
    except LLMError:
        pass

    fallback = keyword_fallback_match(hot_items, confirmed_keywords, top_n=10)
    return [
        {
            "title": f["title"],
            "platform": f["platform"],
            "score": f["score"],
            "reason": f["reason"],
            "slot": "",
        }
        for f in fallback
    ]


# ---------- R-073：三槽候选 ----------

def _comment_candidates(db: Session, profile: dict, days: int = 7) -> list[dict]:
    """近 days 天评论区灵感：人设命中的排前，再按点赞。"""
    cutoff = (_dt.date.today() - _dt.timedelta(days=max(1, days))).isoformat()
    rows = (
        db.query(TopicIdea)
        .filter(TopicIdea.source == "comment", TopicIdea.used.is_(False), TopicIdea.snapshot_date >= cutoff)
        .order_by(TopicIdea.snapshot_date.desc(), TopicIdea.likes.desc(), TopicIdea.id.desc())
        .limit(200)
        .all()
    )
    items = [
        {
            "title": r.title,
            "platform": r.platform or "",
            "likes": r.likes or 0,
            "post_title": r.post_title or "",
            "snapshot_date": r.snapshot_date,
        }
        for r in rows
    ]
    ann = annotate_items(db, items, profile)
    # 人设命中优先，其次点赞高；都不命中也能作为“评论区问题”兜底（最后才用）
    ann.sort(key=lambda x: (x["matched"], x.get("likes", 0)), reverse=True)
    return ann


def _hot_candidates(db: Session, hot_items: list[dict], profile: dict) -> list[dict]:
    """今日热榜：人设打分排序，红线词剔除。"""
    items = [
        {"platform": h.get("platform", ""), "title": h.get("title", ""), "heat": h.get("heat", ""), "url": h.get("url", "")}
        for h in hot_items
    ]
    ann = annotate_items(db, items, profile)
    ann = [x for x in ann if not x["redlined"]]
    ann.sort(key=lambda x: (x["matched"], x["score"]), reverse=True)
    return ann


def _ai_fallback(db: Session, profile: dict) -> dict | None:
    """无 LLM/无 key 时：按「赛道缺口 + 评论区高频」给一条 AI 建议（启发式）。"""
    from ..models.video import Video

    cid = current_creator_id(db)
    counts = {t: 0 for t in MAIN_TOPICS if t != "其他"}
    if cid:
        videos = (
            db.query(Video)
            .filter(Video.creator_id == cid, Video.is_ad.is_(False), Video.status == "published")
            .all()
        )
        for v in videos:
            try:
                topics = json.loads(v.main_topics or "[]") if isinstance(v.main_topics, str) else (v.main_topics or [])
            except json.JSONDecodeError:
                topics = []
            for t in topics:
                if t in counts:
                    counts[t] += 1
    least = sorted(counts.items(), key=lambda kv: kv[1])[0] if counts else ("求职", 0)
    topic = least[0]
    # 评论区该赛道相关问题数（近 7 天）
    ask = 0
    for it in _comment_candidates(db, profile, days=7)[:50]:
        if topic in (it.get("title") or ""):
            ask += 1
    return {
        "title": f"关于{topic}，评论区问得最多的那几件事",
        "platform": "ai",
        "score": 60,
        "reason": f"AI 建议（启发式兜底）：{topic} 赛道近期发布较少、评论区相关提问 {ask} 条",
        "slot": SLOT_AI,
        "matched": True,
    }


def _ai_candidate(db: Session, hot_cands: list[dict], profile: dict) -> dict | None:
    """AI 槽：让模型基于 人设 + 今日热榜 + 评论区高频 + 赛道缺口 建议一条作者能讲的选题。"""
    persona = PersonaService()
    keywords = profile.get("keywords") or []
    avoid = profile.get("avoid") or []
    comments = _comment_candidates(db, profile, days=7)[:5]
    comment_lines = "\n".join(f"- {c['title']}" for c in comments) or "（暂无）"
    hot_lines = "\n".join(f"- [{c.get('platform','')}] {c['title']}" for c in hot_cands[:10]) or "（暂无）"
    kw_lines = "、".join(keywords[:30]) or "（暂无，作者需要先确认人设标签）"
    av_lines = "、".join(avoid[:20]) or "（无）"
    system = (
        "你是了解作者人设的自媒体选题策划。请基于作者人设、今日热榜、评论区高频问题和赛道缺口，"
        "给出**一条**作者适合讲、又可能出圈的选题（观点/角度要新，不能是别人都讲烂的）。"
        '只输出 JSON：{"title":"完整选题标题","score":0-100,"reason":"为什么适合作者讲"}'
    )
    user = (
        f"作者人设关键词：{kw_lines}\n"
        f"红线（不要提）：{av_lines}\n\n"
        f"评论区最近高频提问：\n{comment_lines}\n\n"
        f"今日热榜（可参考切入角度）：\n{hot_lines}"
    )
    try:
        data = persona.llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.7,
        )
        title = str((data or {}).get("title", "")).strip()
        if title:
            return {
                "title": title,
                "platform": "ai",
                "score": max(0, min(100, int((data or {}).get("score") or 60))),
                "reason": str((data or {}).get("reason", "")),
                "slot": SLOT_AI,
                "matched": True,
            }
    except LLMError:
        pass
    except Exception:  # noqa: BLE001 单槽失败降级启发式
        pass
    return _ai_fallback(db, profile)


def _compose_daily_candidates(db: Session, hot_items: list[dict], settings, count: int | None = None) -> list[dict]:
    """组装每日候选：评论区 1 + 热榜 1 + AI 建议 1，缺源回退；其余空位用热榜/评论补充。"""
    count = int(count if count is not None else getattr(settings, "pipeline_topics_count", 3))
    profile = persona_profile(db)
    comments = _comment_candidates(db, profile)
    hots = _hot_candidates(db, hot_items, profile)
    ai = _ai_candidate(db, hots, profile)

    cands: list[dict] = []
    # 评论槽：优先人设命中；没有命中也取最近一条（保证“有评论区来源”）
    if comments:
        pick = next((c for c in comments if c.get("matched")), comments[0])
        cands.append(
            {
                "title": pick.get("title", ""),
                "platform": pick.get("platform", ""),
                "score": int(pick.get("score") or 0),
                "reason": f"来自评论区（《{(pick.get('post_title') or '')[:30]}》）"
                + ("" if pick.get("matched") else "；人设未命中，仅作问题参考"),
                "slot": SLOT_COMMENT,
            }
        )
    # 热榜槽：人设匹配优先
    hot_pick = next((c for c in hots if c.get("matched")), hots[0] if hots else None)
    if hot_pick:
        cands.append(
            {
                "title": hot_pick.get("title", ""),
                "platform": hot_pick.get("platform", ""),
                "score": int(hot_pick.get("score") or 0),
                "reason": "今日热榜 · 人设匹配" if hot_pick.get("matched") else "今日热榜（人设相关度低，作兜底）",
                "slot": SLOT_HOT,
            }
        )
    if ai:
        cands.append(
            {
                "title": ai["title"],
                "platform": ai.get("platform", "ai"),
                "score": int(ai.get("score") or 60),
                "reason": ai.get("reason", "AI 根据人设建议"),
                "slot": SLOT_AI,
            }
        )
    # 补足剩余空位：从热榜/评论（人设命中优先）补充，保证不重复
    for extra in hots:
        if len(cands) >= count:
            break
        cands.append(
            {
                "title": extra.get("title", ""),
                "platform": extra.get("platform", ""),
                "score": int(extra.get("score") or 0),
                "reason": "热榜补充 · 人设匹配" if extra.get("matched") else "热榜补充",
                "slot": SLOT_HOT,
            }
        )
    cands = _dedupe_candidates(cands)[:count]
    if not cands:
        # 极端无任何源：退回原人设×热榜匹配，保证流水线仍能出稿
        cands = _match_candidates(db, hot_items, settings)[:count]
    return cands


def run_daily_pipeline(db: Session, force: bool = False, settings=None) -> PipelineRun:
    """执行当日流水线。幂等：当天已成功且非 force 时直接返回。"""
    settings = settings or get_settings()
    key = today_key()
    run = db.query(PipelineRun).filter(PipelineRun.run_date == key).first()
    if run and run.status == "done" and not force:
        return run
    if run and not can_run(run.status):
        return run
    if run is None:
        run = PipelineRun(run_date=key, status="running")
        db.add(run)
    run.status = "running"
    run.error = ""
    db.commit()

    try:
        hot_items = fetch_and_store(db, settings)
        candidates = _compose_daily_candidates(db, [h.to_dict() for h in hot_items], settings)
        run.candidates_count = len(candidates)
        db.commit()

        drafts = []
        for c in candidates[: max(1, int(settings.pipeline_topics_count or 3))]:
            draft = generate_draft(db, c["title"], settings)
            drafts.append(draft)
            db.add(
                TopicCandidate(
                    run_date=key,
                    title=c["title"],
                    platform=c.get("platform", ""),
                    score=c.get("score", 0),
                    slot=c.get("slot", ""),
                    reason=c.get("reason", ""),
                    draft_id=draft.id,
                )
            )
        db.commit()

        sent = send_daily_digest(db, key, settings)
        run.status = "done"
        run.generated_count = len(drafts)
        if not sent:
            run.error = "邮件未发送：SMTP 未配置（开发模式）"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        run.status = "failed"
        run.error = str(exc)[:2000]
        db.commit()
        try:
            send_failure_alert(db, run, settings)
        except Exception:  # noqa: BLE001
            pass
    return run
