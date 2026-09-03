"""每日流水线：抓热点 → 匹配 → 生成 → 发邮件（幂等 + 失败告警）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.matching import keyword_fallback_match
from ..core.pipeline import can_run, today_key
from ..models.hot_topic import TopicCandidate
from ..models.pipeline import PipelineRun
from .generation import generate_draft
from .llm import LLMError
from .notify import send_daily_digest, send_failure_alert
from .persona import PersonaService
from .topic_mining import fetch_and_store


def _match_candidates(db: Session, hot_items: list[dict], settings) -> list[dict]:
    """人设×热点匹配：先试 LLM，失败/无密钥时用关键词兜底。"""
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
        # LLM 匹配：人设 + 热点 → 排序后的候选
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
                    }
                )
        if cands:
            return cands
    except LLMError:
        pass

    fallback = keyword_fallback_match(hot_items, confirmed_keywords, top_n=settings.pipeline_topics_count)
    return [
        {
            "title": f["title"],
            "platform": f["platform"],
            "score": f["score"],
            "reason": f["reason"],
        }
        for f in fallback
    ]


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
        candidates = _match_candidates(db, [h.to_dict() for h in hot_items], settings)
        run.candidates_count = len(candidates)
        db.commit()

        drafts = []
        for c in candidates[: settings.pipeline_topics_count]:
            draft = generate_draft(db, c["title"], settings)
            drafts.append(draft)
            db.add(
                TopicCandidate(
                    run_date=key,
                    title=c["title"],
                    platform=c.get("platform", ""),
                    score=c.get("score", 0),
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
