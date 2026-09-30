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
from ..core.log import get_logger
from ..core.matching import keyword_fallback_match
from ..core.pipeline import is_stale, today_key
from ..core.topics import MAIN_TOPICS
from ..models.hot_topic import TopicCandidate, TopicIdea
from ..models.pipeline import PipelineRun
from .creator_service import current_creator_id
from . import model_settings
from .generation import generate_draft
from .ideas_service import annotate_items, persona_profile
from .llm import LLMError
from .notify import send_daily_best, send_daily_digest, send_failure_alert
from .persona import PersonaService
from .topic_mining import fetch_and_store

log = get_logger("pipeline")

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
        data = persona.call_json(
            "ideas",
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
    q = db.query(TopicIdea).filter(
        TopicIdea.source == "comment", TopicIdea.used.is_(False), TopicIdea.snapshot_date >= cutoff
    )
    cid = current_creator_id(db)
    if cid:
        q = q.filter(TopicIdea.creator_id == cid)  # R-135：只取当前主博主的评论灵感（原来会把对标评论串进来）
    rows = (
        q.order_by(TopicIdea.snapshot_date.desc(), TopicIdea.likes.desc(), TopicIdea.id.desc())
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
        data = persona.call_json(
            "ideas",
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
    """组装每日候选：评论区 1 + 热榜 1 + AI 建议 1，缺源回退；其余空位用热榜/评论补充。

    R-140：每日篇数统一取「AI 设置」的运行时配置（`app_kv` > `.env` > 默认），
    与真正生成时的切片口径一致（此前组候选用 `.env`、生成用 `app_kv`，会出现
    「候选 3 条、实际只生成 1 条」的显示不一致）。
    """
    count = int(count if count is not None else model_settings.topics_count(db))
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


def mark_stale_pipeline_runs_on_startup(db: Session | None = None) -> int:
    """启动自愈（R-133）：把遗留 `running` 的 PipelineRun 置 failed。

    否则 `can_run` 会永久拒绝重跑 → 每日选题/脚本生产静默停摆，只能手改库。
    """
    own = db is None
    session = db
    if session is None:
        from ..db import SessionLocal

        session = SessionLocal()
    try:
        rows = session.query(PipelineRun).filter(PipelineRun.status == "running").all()
        for row in rows:
            row.status = "failed"
            row.error = "服务重启/中断，流水线未完成（已自动标记，可直接重跑）"
        session.commit()
        if rows:
            log.warning("启动自愈：%d 个遗留 running 流水线已标记 failed", len(rows))
        return len(rows)
    finally:
        if own:
            session.close()


class PipelineError(RuntimeError):
    """流水线执行失败（R-133）：向上抛，让任务层写 failed + 站内通知，而不是谎报「完成」。"""

    def __init__(self, message: str):
        super().__init__(message)


def _pick_daily_best_index(db: Session, items: list[dict]) -> int:
    """R-208：让 AI 从当天几篇里按「人设契合 × 热点热度」选 1 篇；失败退回分数最高。"""
    if len(items) == 1:
        return 0
    lines = []
    for i, it in enumerate(items):
        lines.append(
            f"{i}. [{SLOT_LABEL.get(it['slot'], it['slot'] or '自定义')}] {it['title']}"
            f"（人设契合分 {it['score']}；入选理由：{it['reason'][:60]}）"
        )
    system = (
        "你是作者的选题主编。今天已生成以下候选选题，请按「与作者人设的契合度 × 当下热度/传播潜力」"
        "选出**最适合今天开拍的一条**。只输出 JSON："
        '{"index":编号,"reason":"一句话说明为什么它今天最值得拍"}'
    )
    user = "候选：\n" + "\n".join(lines)
    try:
        data = PersonaService().call_json(
            "ideas",
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
        )
        raw = (data or {}).get("index")
        idx = int(raw) if raw is not None else -1
        if 0 <= idx < len(items):
            return idx
    except Exception:  # noqa: BLE001 选优失败不能拖垮流水线，退回分数最高
        pass
    return max(range(len(items)), key=lambda i: items[i]["score"])


def push_daily_best(db: Session, run_date: str, settings=None) -> dict | None:
    """R-208：每日「今日最佳」推送——AI 选 1 篇，站内通知 + 邮件推「选题理由 + 完整口播稿」。

    同一天只推一次（Kv 标记防重跑重复推送）；邮件失败不影响（R-141 次要通道）。
    """
    from ..models.draft import Draft
    from ..models.kv import Kv
    from ..tasks import push_notification

    settings = settings or get_settings()
    flag_key = f"daily_best_pushed:{run_date}"
    if db.get(Kv, flag_key) is not None:
        return None
    cands = (
        db.query(TopicCandidate)
        .filter(TopicCandidate.run_date == run_date)
        .order_by(TopicCandidate.score.desc())
        .all()
    )
    items: list[dict] = []
    for c in cands:
        draft = db.get(Draft, c.draft_id) if c.draft_id else None
        if draft is None or not (draft.script or "").strip():
            continue
        items.append(
            {
                "cand": c,
                "draft": draft,
                "title": c.title,
                "slot": c.slot,
                "score": int(c.score or 0),
                "reason": c.reason or "",
            }
        )
    if not items:
        return None
    chosen = items[_pick_daily_best_index(db, items)]
    draft = chosen["draft"]
    c = chosen["cand"]
    slot_label = SLOT_LABEL.get(c.slot, c.slot or "自定义")
    reason = chosen["reason"] or f"来自{slot_label}"
    push_notification(
        db,
        kind="daily_best",
        status="done",
        title=f"今日最佳选题：{c.title[:40]}",
        message=(
            f"【{slot_label}】{c.title}\n\n选题理由：{reason}\n\n"
            f"口播稿：\n{draft.script}"
        ),
        target=f"/drafts?id={draft.id}",
    )
    try:
        send_daily_best(
            {
                "title": c.title,
                "platform": c.platform,
                "score": int(c.score or 0),
                "reason": f"【今日最佳 · {slot_label}】{reason}",
                "cover_text": draft.cover_text or "",
                "script": draft.script or "",
            },
            run_date,
            settings,
        )
    except Exception:  # noqa: BLE001 邮件次要通道，失败不影响
        log.exception("今日最佳邮件推送失败（run_date=%s）", run_date)
    db.add(Kv(key=flag_key, value="1"))
    db.commit()
    return {"draft_id": draft.id, "title": c.title, "reason": reason}


def run_daily_pipeline(db: Session, force: bool = False, settings=None) -> PipelineRun:
    """执行当日流水线。幂等：当天已成功且非 force 直接返回；running 超时视为卡死可重跑。

    失败时把 PipelineRun 置 failed、发邮件告警，**并抛出 PipelineError**（R-133），
    由任务层/定时任务层统一写 failed + 站内通知。
    """
    settings = settings or get_settings()
    key = today_key()
    run = db.query(PipelineRun).filter(PipelineRun.run_date == key).first()
    if run and run.status == "done" and not force:
        return run
    if run and run.status == "running":
        if not is_stale(run.created_at):
            log.info("当日流水线仍在运行中，跳过（run_date=%s）", key)
            return run
        run.status = "failed"
        run.error = "流水线超时未完成，已自动标记（可重跑）"
        db.commit()
        log.warning("当日流水线 running 超时，已标记 failed 并可重跑（run_date=%s）", key)
    if run is None:
        run = PipelineRun(run_date=key, status="running")
        db.add(run)
    run.status = "running"
    run.error = ""
    db.commit()

    try:
        hot_items = fetch_and_store(db, settings)
        # R-138/R-139/R-140：每日生成篇数取「AI 设置」里的运行时配置（Kv > .env > 默认），
        # 组候选与生成切片用同一个值，避免候选数与实际出稿数不一致。
        topics = model_settings.topics_count(db)
        candidates = _compose_daily_candidates(db, [h.to_dict() for h in hot_items], settings, count=topics)
        run.candidates_count = len(candidates)
        db.commit()

        drafts = []
        for c in candidates:
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
        # R-208：每日「今日最佳」——AI 从当天几篇选 1 篇，通知 + 邮件推理由与口播稿全文
        try:
            push_daily_best(db, key, settings)
        except Exception:  # noqa: BLE001 推送失败不能把已生成好的稿子判为失败
            db.rollback()
            log.exception("今日最佳推送失败（run_date=%s）", key)
        # R-140：稿子已经生成好了，邮件（次要通道）失败只记原因，不能把整轮判为 failed
        run.status = "done"
        run.generated_count = len(drafts)
        if not sent:
            from .notify import mail_config_problem

            problem = mail_config_problem(settings)
            run.error = f"邮件未发送：{problem}" if problem else "邮件发送失败（详见日志）"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        run.status = "failed"
        run.error = str(exc)[:2000]
        db.commit()
        log.exception("每日流水线失败（run_date=%s）", key)
        try:
            send_failure_alert(db, run, settings)
        except Exception:  # noqa: BLE001
            log.exception("流水线失败邮件告警发送失败")
        raise PipelineError(f"每日流水线失败：{str(exc)[:300]}") from exc
    return run
