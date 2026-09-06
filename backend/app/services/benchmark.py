"""R-097：博主对标——对标最新10条取数据 Top3 + “我能不能讲” + 按人设洗稿存草稿。

对标内容只做分析与改写来源，绝不进入主博主人设学习语料（D-028）；
转写补齐产生的对标素材归属对标博主（R-082），天然被主博主语料过滤排除。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.pipeline import today_key  # noqa: F401 保留：未来可扩展
from ..models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from ..models.video import Video

# 互动权重：点赞1 + 收藏2 + 评论5（播放量只做参考不做主排序）
W_LIKE, W_FAV, W_COMMENT = 1, 2, 5


def _latest_stats(db: Session, post_ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not post_ids:
        return out
    for row in (
        db.query(PlatformPostStat)
        .filter(PlatformPostStat.post_id.in_(post_ids))
        .order_by(PlatformPostStat.stat_date)
        .all()
    ):
        out[row.post_id] = {
            "plays": int(row.plays or 0),
            "likes": int(row.likes or 0),
            "favorites": int(row.favorites or 0),
            "comments": int(row.comments or 0),
        }
    return out


def benchmarks_of_owner(db: Session, owner: Creator) -> list[Creator]:
    return (
        db.query(Creator)
        .filter(Creator.kind == "benchmark", Creator.parent_id == owner.id)
        .order_by(Creator.id)
        .all()
    )


def _norm_title(title: str) -> str:
    """规范化标题：去 #话题、统一小写去空白，用于跨平台同款广告过滤（R-100）。"""
    import re

    t = re.sub(r"[#＃][^\s#＃，,。！？!?、]*", "", title or "")
    return re.sub(r"[^\w\u4e00-\u9fa5]", "", t).lower()


def candidates(db: Session, bm: Creator, limit: int = 10) -> list[dict]:
    """对标博主最新 limit 个“作品单元”（跨平台合并 work；未合并单帖）。"""
    acc_ids = [
        a.id for a in db.query(CreatorAccount).filter(CreatorAccount.creator_id == bm.id).all()
    ]
    if not acc_ids:
        return []
    rows = (
        db.query(PlatformPost)
        .filter(PlatformPost.account_id.in_(acc_ids))
        .order_by(PlatformPost.publish_time.desc())
        .all()
    )
    # R-099/R-100：广告不对标；同款跨平台漏标(标题相同)也一并排除
    ad_norms = {_norm_title(x.title) for x in rows if x.is_ad}
    posts = [x for x in rows if not x.is_ad and _norm_title(x.title) not in ad_norms]
    # 按 work 聚合（work_id 相同的算同一作品）
    work_map: dict[int, list[PlatformPost]] = {}
    singles: list[PlatformPost] = []
    for p in posts:
        if p.work_id:
            work_map.setdefault(p.work_id, []).append(p)
        else:
            singles.append(p)
    units: list[dict] = []
    for p in singles:
        units.append({"work_id": None, "post": p})
    for wid, members in work_map.items():
        members = [m for m in members if not m.is_ad]
        if not members:
            continue
        members.sort(key=lambda m: (m.publish_time or _EPOCH), reverse=True)
        units.append({"work_id": wid, "post": members[0], "members": members})
    units.sort(key=lambda u: (u["post"].publish_time or _EPOCH), reverse=True)
    return units[:limit]


_EPOCH = __import__("datetime").datetime(2000, 1, 1)


def _unit_text(db: Session, unit: dict) -> str:
    """取该作品单元已有转写文案（对标转写产物归属对标，仅作分析/洗稿）。"""
    post = unit["post"]
    vids: list[Video] = []
    if post.local_video_id:
        v = db.get(Video, post.local_video_id)
        if v:
            vids.append(v)
    if unit.get("work_id"):
        for v in db.query(Video).filter(Video.work_id == unit["work_id"]).all():
            if v.id not in {x.id for x in vids}:
                vids.append(v)
    # R-099：对标素材文案优先（只）使用 ASR 转写稿；无转写则视为“暂无文案”，由 prepare 下载转写补齐
    for v in vids:
        tr = v.transcript
        if tr and (tr.corrected_text or tr.transcript_text):
            return (tr.corrected_text or tr.transcript_text or "").strip()
    return ""


def _stats_map(db: Session, units: list[dict]) -> dict[int, dict]:
    ids = []
    for u in units:
        ids.append(u["post"].id)
        for m in u.get("members") or []:
            ids.append(m.id)
    return _latest_stats(db, ids)


def score_unit(db: Session, unit: dict, stats_map: dict[int, dict]) -> float:
    posts = unit.get("members") or [unit["post"]]
    score = 0.0
    for p in posts:
        st = stats_map.get(p.id) or {}
        score += int(st.get("likes") or 0) * W_LIKE
        score += int(st.get("favorites") or 0) * W_FAV
        score += int(st.get("comments") or 0) * W_COMMENT
    return score


def ensure_top3_with_text(db: Session, bm: Creator, limit_candidates: int = 10) -> list[dict]:
    """最新 N 条按互动分排序，逐条补齐转写；取前 3 条“有文案”的。

    转写后仍无文案（识别为空/无声等）→ 顺延下一条顶上（R-097 Q3）。
    """
    units = candidates(db, bm, limit=limit_candidates)
    stats_map = _stats_map(db, units)
    ranked = sorted(units, key=lambda u: score_unit(db, u, stats_map), reverse=True)
    picked: list[dict] = []
    for unit in ranked:
        text = _unit_text(db, unit)
        if not text:
            # 缺转写：下载音频+转写（对标素材；失败/无语音则顺延）
            try:
                from .media_ensure import platform_media_task

                platform_media_task(db, {"post_id": unit["post"].id})
            except Exception:  # noqa: BLE001
                db.rollback()
                continue
            text = _unit_text(db, unit)
        if not text:
            continue
        unit["text"] = text
        unit["score"] = score_unit(db, unit, stats_map)
        picked.append(unit)
        if len(picked) >= 3:
            break
    return picked


def unit_payload(db: Session, unit: dict, stats_map: dict[int, dict] | None = None) -> dict:
    """作品单元序列化（含分数/文案/统计，供对标页展示与分析）。"""
    if stats_map is None:
        stats_map = _stats_map(db, [unit])
    posts = unit.get("members") or [unit["post"]]
    platforms = sorted({p.platform for p in posts})
    likes = sum(int((stats_map.get(p.id) or {}).get("likes") or 0) for p in posts)
    fav = sum(int((stats_map.get(p.id) or {}).get("favorites") or 0) for p in posts)
    comments = sum(int((stats_map.get(p.id) or {}).get("comments") or 0) for p in posts)
    plays = sum(int((stats_map.get(p.id) or {}).get("plays") or 0) for p in posts)
    post = unit["post"]
    text = unit.get("text")
    if text is None:
        text = _unit_text(db, unit)  # R-100：首屏也把已有 ASR 转写文案带出来
    return {
        "key": f"w{unit['work_id']}" if unit.get("work_id") else f"p{post.id}",
        "work_id": unit.get("work_id"),
        "post_id": post.id,
        "title": post.title or "",
        "desc": post.desc or "",
        "cover": post.cover_url or "",
        "platforms": platforms,
        "likes": likes,
        "favorites": fav,
        "comments": comments,
        "plays": plays,
        "score": likes * W_LIKE + fav * W_FAV + comments * W_COMMENT,
        "has_text": bool(text),
        "text": text or "",
    }


def persona_lines(db: Session, owner: Creator) -> list[str]:
    from ..models.persona import PersonaTag

    rows = (
        db.query(PersonaTag)
        .filter(PersonaTag.creator_id == owner.id, PersonaTag.status == "confirmed")
        .order_by(PersonaTag.category)
        .all()
    )
    lines: list[str] = []
    for t in rows:
        txt = t.label if t.category == "redline" else f"{t.label}：{t.description or ''}".strip("：")
        lines.append(f"[{t.category}] {txt}")
    return lines


def _llm():
    from ..config import get_settings
    from .llm import get_llm

    settings = get_settings()
    return get_llm((settings.generation_model or "kimi").strip().lower(), settings)


def analyze_talkable(db: Session, owner: Creator, unit: dict) -> dict:
    text = unit.get("text") or _unit_text(db, unit)
    if not text:
        return {"can": False, "reason": "该素材还没有可用文案（先转写补齐）", "suggestion": ""}
    persona = "\n".join(persona_lines(db, owner)) or "（尚未建人设档案）"
    try:
        res = _llm().chat_json(
            [
                {"role": "system", "content": "你是我的内容选题顾问。只输出 JSON：{\"can\":bool,\"reason\":string,\"suggestion\":string}"},
                {"role": "user", "content": f"我的人设/红线：\n{persona}\n\n这是对标博主的一条视频文案：\n{text[:3000]}\n\n判断我能不能讲（是否契合我人设、我能不能讲得动、是否与我已有内容重复）："},
            ],
            temperature=0.4,
            max_tokens=800,
        )
        return {"can": bool(res.get("can")), "reason": str(res.get("reason") or ""), "suggestion": str(res.get("suggestion") or "")}
    except Exception as exc:  # noqa: BLE001
        return {"can": False, "reason": f"AI 分析暂不可用：{exc}", "suggestion": ""}


def rewrite_script(db: Session, owner: Creator, unit: dict, title: str = "") -> dict:
    """按人设改写文案；返回 {title, script, draft_id}。"""
    text = unit.get("text") or _unit_text(db, unit)
    if not text:
        raise ValueError("该素材还没有可用文案（先转写补齐）")
    persona = "\n".join(persona_lines(db, owner)) or "（尚未建人设档案）"
    llm = _llm()
    script = llm.chat(
        [
            {"role": "system", "content": "你是口播脚本代笔。用作者的人设口吻与表达习惯，把给定素材改写成作者能直接录的原创口播稿；不逐字抄袭、保留核心信息与结构，语言自然像本人说话。"},
            {"role": "user", "content": f"我的人设：\n{persona}\n\n参考素材标题：{title or unit['post'].title}\n参考素材文案：\n{text[:4000]}"},
        ],
        temperature=0.7,
        max_tokens=2500,
    ).strip()
    new_title = title or (unit["post"].title or "")[:60]
    # 存脚本草稿（归属当前主博主，标注对标来源）
    from ..models.draft import Draft
    from .creator_service import current_creator_id

    cid = owner.id if owner.kind == "owner" else current_creator_id(db)
    draft = Draft(
        creator_id=cid,
        title=new_title,
        script=script,
        original_script=text,
        source="ai",
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {"title": new_title, "script": script, "draft_id": draft.id}


def analyze_text(db: Session, owner: Creator, text: str) -> dict:
    """对给定文案做“我能不能讲”分析（对标页用，文案来自前端已 prepare 数据）。"""
    if not (text or "").strip():
        return {"can": False, "reason": "该素材还没有可用文案（先转写补齐）", "suggestion": ""}
    persona = "\n".join(persona_lines(db, owner)) or "（尚未建人设档案）"
    try:
        res = _llm().chat_json(
            [
                {"role": "system", "content": "你是我的内容选题顾问。只输出 JSON：{\"can\":bool,\"reason\":string,\"suggestion\":string}"},
                {"role": "user", "content": f"我的人设/红线：\n{persona}\n\n这是对标博主的一条视频文案：\n{text[:3000]}\n\n判断我能不能讲（是否契合我人设、我能不能讲得动、是否与我已有内容重复）："},
            ],
            temperature=0.4,
            max_tokens=800,
        )
        return {"can": bool(res.get("can")), "reason": str(res.get("reason") or ""), "suggestion": str(res.get("suggestion") or "")}
    except Exception as exc:  # noqa: BLE001
        return {"can": False, "reason": f"AI 分析暂不可用：{exc}", "suggestion": ""}


def rewrite_text(db: Session, owner: Creator, title: str, text: str) -> dict:
    """按人设把文案改写成原创口播稿并存脚本草稿。"""
    if not (text or "").strip():
        raise ValueError("该素材还没有可用文案（先转写补齐）")
    persona = "\n".join(persona_lines(db, owner)) or "（尚未建人设档案）"
    llm = _llm()
    script = llm.chat(
        [
            {"role": "system", "content": "你是口播脚本代笔。用作者的人设口吻与表达习惯，把给定素材改写成作者能直接录的原创口播稿；不逐字抄袭、保留核心信息与结构，语言自然像本人说话。"},
            {"role": "user", "content": f"我的人设：\n{persona}\n\n参考素材标题：{title}\n参考素材文案：\n{text[:4000]}"},
        ],
        temperature=0.7,
        max_tokens=2500,
    ).strip()
    new_title = (title or "")[:60] or "对标洗稿"
    from ..models.draft import Draft
    from .creator_service import current_creator_id

    cid = owner.id if owner.kind == "owner" else current_creator_id(db)
    draft = Draft(creator_id=cid, title=new_title, script=script, original_script=text, source="ai", status="draft")
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {"title": new_title, "script": script, "draft_id": draft.id}
