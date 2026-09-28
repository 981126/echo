"""内容机会引擎（R-185）：评论聚类选题榜 + 选题账本 + 每周灵感包。

纯本地统计，不调 LLM：
- 把灵感池里「未使用」的评论按语义相似聚成「观众提问」簇（同一问题被多人问 = 强需求）；
- 与「已讲过」的话题（草稿 used/done + 已发布素材标题）做近义匹配，标注重复、提示缺口；
- 综合 需求强度 × 人设相关 × 热度 × 新鲜度 × 缺口 打分，产出「每周灵感包」。
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from ..models.hot_topic import TopicIdea

_SIM_THRESHOLD = 0.5
_COVERED_THRESHOLD = 0.62
_SCAN_LIMIT = 500  # 只对互动最高的一批评论聚类，避免 O(n²) 卡死
_LLM_SCAN_LIMIT = 60  # 交给模型语义聚类的评论条数上限（太大易超时/截断）
_LLM_DEADLINE = 100.0  # 模型聚类硬超时（秒）：超时立即回退本地聚类，避免界面卡死
_LLM_CACHE_TTL = 21600.0  # 模型聚类结果缓存 6 小时（调用较慢，尽量复用；每周任务会预热）
_CACHE_TTL = 120.0
_CACHE: dict[str, tuple[float, object]] = {}


def _cached(key: str, fn, ttl: float = _CACHE_TTL):
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = fn()
    _CACHE[key] = (now, value)
    if len(_CACHE) > 32:
        _CACHE.clear()
    return value
_EMOJI_TAG = re.compile(r"\[[^\]]{1,8}\]")
_AT_RE = re.compile(r"@\S+")
_QUESTION_HINTS = ("怎么", "如何", "能不能", "是不是", "为什么", "吗", "？", "?", "求", "想问", "请教")
_PRAISE_HINTS = ("支持", "含金量", "点赞", "沙发", "哈哈", "加油", "感谢", "好听", "三连", "关注了", "666", "学到了", "牛", "不错", "笑死", "爱了")


def _clean(text: str) -> str:
    """去掉表情标签/[话题]、@提及与首尾标点，得到适合展示与聚类的问题文本。"""
    t = _EMOJI_TAG.sub("", text or "")
    t = _AT_RE.sub("", t)
    return t.strip(" \t\r\n，。！？!?、,.~—·")


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", _clean(text).lower())


def _is_question(text: str) -> bool:
    return any(h in (text or "") for h in _QUESTION_HINTS)


def _low_value(text: str) -> bool:
    """过滤无信息量的评论（纯赞美/太短/纯符号），避免污染观众提问榜。"""
    t = _clean(text)
    n = _norm(t)
    if len(n) < 4:
        return True
    if _is_question(t):
        return False
    if len(t) <= 14 and any(p in t for p in _PRAISE_HINTS):
        return True
    return False


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def _sim(a: str, b: str) -> float:
    """相似度 = max(子串包含, 字符 bigram Jaccard, SequenceMatcher)，兼顾中文短句。"""
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    ba, bb = _bigrams(a), _bigrams(b)
    jac = len(ba & bb) / len(ba | bb) if (ba | bb) else 0.0
    return max(jac, SequenceMatcher(None, a, b).ratio())


def covered_titles(db: Session, limit: int = 400) -> list[str]:
    """「已讲过」的话题标题（选题账本的事实源）：已完成/待制作草稿 + 已发布素材。"""
    from ..models.draft import Draft
    from ..models.video import Video
    from .creator_service import current_creator_id

    cid = current_creator_id(db)
    titles: list[str] = []
    dq = db.query(Draft).filter(Draft.status.in_(["used", "done"]))
    if cid:
        dq = dq.filter(Draft.creator_id == cid)
    for d in dq.order_by(Draft.id.desc()).limit(limit).all():
        if (d.title or "").strip():
            titles.append(d.title.strip())
    vq = db.query(Video)
    if cid:
        vq = vq.filter(Video.creator_id == cid)
    for v in vq.order_by(Video.id.desc()).limit(limit).all():
        if (v.title or "").strip():
            titles.append(v.title.strip())
    out: list[str] = []
    for t in titles:
        if t not in out:
            out.append(t)
    return out


def _is_covered(title: str, covered_norm: list[str]) -> bool:
    n = _norm(title)
    return any(_sim(n, c) >= _COVERED_THRESHOLD for c in covered_norm)


def _unused_ideas(db: Session, source: str, limit: int | None = None) -> list[TopicIdea]:
    q = (
        db.query(TopicIdea)
        .filter(TopicIdea.source == source, TopicIdea.used.is_(False))
        .order_by(TopicIdea.likes.desc(), TopicIdea.id.desc())
    )
    if limit:
        q = q.limit(limit)
    return q.all()


def _cid(db: Session) -> int | None:
    from .creator_service import current_creator_id

    return current_creator_id(db)


_LLM_CLUSTER_SYSTEM = (
    "你是内容策划。下面是作者评论区里观众的原话（带编号与点赞数）。请把表达**同一类问题/诉求**的评论归为一组，"
    "产出「观众提问榜」：\n"
    "1. 每组给一个**规范化、可直接当选题问题看**的中文标题（≤30 字，不要照抄某一条原话）；\n"
    "2. 列出组成员的编号 members；\n"
    "3. 按需求强度排序（被问次数多、点赞高的组更靠前）；\n"
    "4. 过滤掉纯赞美、无信息、纯表情、广告的评论（不要为它们建组）；\n"
    "5. 只输出 JSON，不要解释："
    '{"groups":[{"title":"规范化问题","members":[1,2,3],"reason":"一句话说明这组在问什么"}]}'
)


def comment_clusters(db: Session, limit: int = 15, use_llm: bool = False) -> dict:
    """观众提问榜（带缓存）：未使用评论聚类。

    use_llm=True（R-192）：先用模型1 做**语义聚类**（把同一类问题归并成规范问题），失败自动回退本地聚类。
    """
    cid = _cid(db) or 0
    if use_llm:
        return _cached(f"ccl:{cid}:{limit}", lambda: _llm_comment_clusters(db, limit), ttl=_LLM_CACHE_TTL)
    return _cached(f"cc:{cid}:{limit}", lambda: _comment_clusters(db, limit))


def _ask_groups(listing: str, deadline: float) -> list:
    """调模型1 做语义聚类，带硬超时（超时返回空 → 调用方回退本地）。"""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FTimeout

    from .persona import PersonaService

    def _run() -> list:
        data = PersonaService().call_json(
            "ideas",
            [
                {"role": "system", "content": _LLM_CLUSTER_SYSTEM},
                {"role": "user", "content": f"作者赛道：求职/面试/赚钱/知识。\n评论区原话：\n{listing}\n\n请分组。"},
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        return data.get("groups") or []

    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(_run).result(timeout=deadline)
    except FTimeout:
        return []
    finally:
        ex.shutdown(wait=False)


def _llm_comment_clusters(db: Session, limit: int) -> dict:
    """模型1 语义聚类（R-192）；失败/无结果返回 None → 调用方回退本地聚类。"""
    from . import ideas_service

    rows = _unused_ideas(db, "comment", _LLM_SCAN_LIMIT)
    total = (
        db.query(TopicIdea)
        .filter(TopicIdea.source == "comment", TopicIdea.used.is_(False))
        .count()
    )
    rows = [r for r in rows if not _low_value(r.title)]
    if len(rows) < 4:
        return _comment_clusters(db, limit)
    ann = {a["id"]: a for a in ideas_service.annotate_items(db, [{"id": r.id, "title": r.title} for r in rows])}
    listing = "\n".join(f"{i}. {_clean(r.title)[:60]}（赞{int(r.likes or 0)}）" for i, r in enumerate(rows, 1))
    try:
        groups = _ask_groups(listing, _LLM_DEADLINE)
    except Exception:  # noqa: BLE001 模型不可用/超时 → 回退本地聚类
        return _comment_clusters(db, limit)
    if not groups:
        return _comment_clusters(db, limit)
    out: list[dict] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        title = str(g.get("title", "")).strip()
        members: list[int] = []
        for x in g.get("members") or []:
            try:
                idx = int(x)
            except (TypeError, ValueError):
                continue
            if 1 <= idx <= len(rows):
                members.append(idx)
        if not title or not members:
            continue
        likes = sum(int(rows[i - 1].likes or 0) for i in members)
        samples: list[str] = []
        for i in members:
            pt = (rows[i - 1].post_title or "")[:60]
            if pt and pt not in samples:
                samples.append(pt)
        matched = any(ann.get(rows[i - 1].id, {}).get("matched") for i in members)
        out.append(
            {
                "title": title[:120],
                "count": len(members),
                "likes": likes,
                "samples": samples[:3],
                "matched": bool(matched),
                "question": _is_question(title),
                "score": len(members) * 10 + round(math.log1p(likes) * 5) + (20 if matched else 0) + (8 if _is_question(title) else 0),
            }
        )
    if not out:
        return _comment_clusters(db, limit)
    out.sort(key=lambda c: c["score"], reverse=True)
    return {"clusters": out[:limit], "total_comments": total, "scanned": len(rows), "engine": "llm"}


def _comment_clusters(db: Session, limit: int) -> dict:
    from . import ideas_service

    rows = _unused_ideas(db, "comment", _SCAN_LIMIT)
    if not rows:
        return {"clusters": [], "total_comments": 0}
    ann = {a["id"]: a for a in ideas_service.annotate_items(db, [{"id": r.id, "title": r.title} for r in rows])}
    clusters: list[dict] = []
    for r in rows:
        title = _clean(r.title)
        n = _norm(title)
        if len(n) < 4 or _low_value(title):
            continue
        for c in clusters:
            if _sim(n, c["_norm"]) >= _SIM_THRESHOLD:
                c["count"] += 1
                c["likes"] += int(r.likes or 0)
                if len(c["samples"]) < 4 and r.post_title:
                    c["samples"].append(r.post_title[:60])
                if ann.get(r.id, {}).get("matched"):
                    c["matched"] = True
                break
        else:
            clusters.append(
                {
                    "title": title[:120],
                    "count": 1,
                    "likes": int(r.likes or 0),
                    "samples": [r.post_title[:60]] if r.post_title else [],
                    "matched": bool(ann.get(r.id, {}).get("matched")),
                    "question": _is_question(title),
                    "_norm": n,
                }
            )
    out: list[dict] = []
    for c in clusters:
        c.pop("_norm", None)
        c["score"] = (
            c["count"] * 10
            + round(math.log1p(c["likes"]) * 5)
            + (20 if c["matched"] else 0)
            + (8 if c.get("question") else 0)
        )
        out.append(c)
    out.sort(key=lambda c: c["score"], reverse=True)
    total = (
        db.query(TopicIdea)
        .filter(TopicIdea.source == "comment", TopicIdea.used.is_(False))
        .count()
    )
    return {"clusters": out[:limit], "total_comments": total, "scanned": len(rows), "engine": "local"}


def weekly_pack(db: Session, limit: int = 20) -> dict:
    """每周灵感补给包（带 120s 缓存）：评论簇 + 热榜，去重/去已讲，综合打分。"""
    cid = _cid(db) or 0
    return _cached(f"wp:{cid}:{limit}", lambda: _weekly_pack(db, limit))


def _weekly_pack(db: Session, limit: int) -> dict:
    from . import ideas_service

    covered = [_norm(t) for t in covered_titles(db)]
    items: list[dict] = []

    cc = comment_clusters(db, limit=40)
    for c in cc["clusters"]:
        items.append(
            {
                "title": c["title"],
                "slot": "comment",
                "demand": c["count"],
                "likes": c["likes"],
                "matched": c["matched"],
                "samples": c["samples"],
                "reason": f"评论区被问 {c['count']} 次" + ("（贴合人设）" if c["matched"] else ""),
            }
        )

    hots = ideas_service.annotate_items(
        db, [{"id": r.id, "title": r.title} for r in _unused_ideas(db, "hot")]
    )
    seen = {_norm(i["title"]) for i in items}
    for h in hots:
        n = _norm(h["title"])
        if not n or any(_sim(n, s) >= _SIM_THRESHOLD for s in seen):
            continue
        seen.add(n)
        items.append(
            {
                "title": h["title"],
                "slot": "hot",
                "demand": 1,
                "likes": 0,
                "matched": h.get("matched", False),
                "samples": [],
                "reason": "今日热榜" + ("·人设匹配" if h.get("matched") else "·人设相关度低"),
            }
        )

    out: list[dict] = []
    good_tags = [_norm(t) for t in (topic_attribution(db).get("good_tags") or [])]
    for it in items:
        duplicate = _is_covered(it["title"], covered)
        nt = _norm(it["title"])
        perf_hit = any(g and (g in nt or nt in g) for g in good_tags)
        score = (
            it["demand"] * 10
            + round(math.log1p(it["likes"]) * 5)
            + (20 if it["matched"] else 0)
            + (15 if not duplicate else -40)
            + (15 if perf_hit else 0)
        )
        it["duplicate"] = duplicate
        it["perf_hit"] = perf_hit
        if perf_hit:
            it["reason"] = (it.get("reason") or "") + "·历史这类表现好"
        it["score"] = max(0, score)
        out.append(it)
    out.sort(key=lambda x: x["score"], reverse=True)
    kept = [x for x in out if not x["duplicate"]][:limit]
    return {"items": kept, "covered_count": len(covered), "generated_at": datetime.now().isoformat()}


_GAP_SYSTEM = (
    "你是选题策划。给你一位自媒体作者的人设、他最近讲过的话题、以及近期热点。"
    "请给出**该讲但还没讲过**的选题——填补他的内容缺口，不要重复已讲过的话题，也不要是宽泛的大词。"
    "每个选题：具体、有钩子、贴合作者人设与赛道（求职/面试/赚钱/知识），并说明为什么值得讲（哪来的缺口/需求）。"
    "只输出 JSON，不要解释："
    '{"topics":[{"title":"完整选题标题(可直接写稿)","reason":"一句话说明缺口/依据"}]}'
)


def gap_suggestions(db: Session, limit: int = 6) -> dict:
    """缺口选题（带 120s 缓存）：AI 基于「已讲话题 + 人设」补位。"""
    cid = _cid(db) or 0
    return _cached(f"gap:{cid}:{limit}", lambda: _gap_suggestions(db, limit))


def _gap_suggestions(db: Session, limit: int) -> dict:
    from ..models.hot_topic import HotTopic
    from ..models.persona import PersonaTag
    from .persona import PersonaService

    cid = _cid(db)
    pq = db.query(PersonaTag).filter(PersonaTag.status == "confirmed")
    if cid:
        pq = pq.filter(PersonaTag.creator_id == cid)
    persona = [
        f"{t.label}: {t.description}".strip(": ")
        for t in pq.order_by(PersonaTag.category, PersonaTag.id).all()
        if t.category in ("style", "topic")
    ]
    covered = covered_titles(db)[:40]
    hots = [h.title for h in db.query(HotTopic).order_by(HotTopic.id.desc()).limit(20).all() if h.title]

    user = "\n".join(
        [
            "作者人设：",
            *[f"- {p}" for p in persona or ["（暂无）"]],
            "",
            "最近讲过的话题（避免重复）：",
            *[f"- {c}" for c in covered or ["（暂无）"]],
            "",
            "近期热点（可结合）：",
            *[f"- {h}" for h in hots or ["（暂无）"]],
            "",
            f"请给出 {limit} 个该讲但没讲过的选题。",
        ]
    )
    try:
        data = PersonaService().call_json(
            "ideas",
            [{"role": "system", "content": _GAP_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.85,
        )
        items: list[dict] = []
        covered_norm = [_norm(c) for c in covered]
        for t in data.get("topics") or []:
            if not isinstance(t, dict):
                continue
            title = str(t.get("title", "")).strip()
            if not title or _is_covered(title, covered_norm):
                continue
            items.append(
                {
                    "title": title[:120],
                    "reason": str(t.get("reason", "")).strip()[:200],
                    "slot": "gap",
                }
            )
        return {"items": items[:limit], "note": ""}
    except Exception as exc:  # noqa: BLE001 AI 不可用不报错
        return {"items": [], "note": f"AI 暂不可用：{str(exc)[:100]}"}


def _engagement(totals: dict) -> float:
    return float(totals.get("plays") or 0) + float(totals.get("likes") or 0) * 5 + float(totals.get("favorites") or 0) * 3 + float(totals.get("comments") or 0) * 10


def topic_attribution(db: Session, limit: int = 15) -> dict:
    """选题归因（R-192）：按草稿标签聚合已发布稿件的表现，看出「哪类选题数据好」。

    数据来自 R-184/R-189 的发布表现回填（drafts.performance）。无数据时返回空。
    """
    cid = _cid(db) or 0
    return _cached(f"attr:{cid}:{limit}", lambda: _topic_attribution(db, limit), ttl=300.0)


def _topic_attribution(db: Session, limit: int) -> dict:
    import json

    from ..models.draft import Draft

    q = db.query(Draft).filter(Draft.status.in_(["used", "done"]))
    cid = _cid(db)
    if cid:
        q = q.filter(Draft.creator_id == cid)
    by_tag: dict[str, list[float]] = {}
    rows: list[dict] = []
    for d in q.all():
        try:
            perf = json.loads(d.performance or "{}")
        except (TypeError, ValueError):
            perf = {}
        totals = perf.get("totals") if isinstance(perf, dict) else None
        if not totals:
            continue
        eng = _engagement(totals)
        rows.append({"title": d.title or "", "engagement": eng, "tags": _draft_tags(d.tags)})
        for tag in _draft_tags(d.tags):
            by_tag.setdefault(tag, []).append(eng)
    if not rows:
        return {"by_tag": [], "top": [], "bottom": [], "draft_count": 0, "good_tags": []}
    tag_stats = [
        {"tag": tag, "count": len(vals), "avg_engagement": round(sum(vals) / len(vals), 1)}
        for tag, vals in by_tag.items()
        if tag
    ]
    tag_stats.sort(key=lambda x: (x["avg_engagement"], x["count"]), reverse=True)
    overall = sum(r["engagement"] for r in rows) / len(rows)
    good = [t["tag"] for t in tag_stats[: max(3, limit // 3)] if t["avg_engagement"] >= overall]
    rows.sort(key=lambda r: r["engagement"], reverse=True)
    return {
        "by_tag": tag_stats[:limit],
        "good_tags": good,
        "draft_count": len(rows),
        "avg_engagement": round(overall, 1),
        "top": [{"title": r["title"], "engagement": r["engagement"]} for r in rows[:5]],
        "bottom": [{"title": r["title"], "engagement": r["engagement"]} for r in rows[-5:]],
    }


def _draft_tags(raw) -> list[str]:
    import json

    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(x).strip() for x in data if str(x).strip()] if isinstance(data, list) else []


def covered(db: Session, limit: int = 300) -> dict:
    """已讲过的话题标题（带 120s 缓存，轻量）——供前端给灵感列表标「可能已讲」。"""
    cid = _cid(db) or 0
    return _cached(f"cov:{cid}:{limit}", lambda: {"titles": covered_titles(db)[:limit]})


def digest_message(pack_items: list[dict], gap_items: list[dict], limit: int = 6) -> tuple[str, int]:
    """把「缺口选题 + 每周灵感包」拼成可推送文案（纯逻辑，供定时任务用）。

    返回 (文案, 总条数)。缺口优先（AI 主动想出来的更稀缺），其后热/评论。
    """
    items: list[tuple[str, str]] = []
    for g in gap_items or []:
        if g.get("title"):
            items.append((f"缺口·{g.get('reason') or '该讲没讲过'}", g["title"]))
    for p in pack_items or []:
        if p.get("title"):
            items.append((p.get("reason") or "灵感", p["title"]))
    top = items[:limit]
    message = "\n".join(f"{i + 1}. {title}（{reason[:30]}）" for i, (reason, title) in enumerate(top))
    if len(items) > limit:
        message += f"\n…另有 {len(items) - limit} 条，去「主页 → 内容机会」查看"
    return message, len(items)


def ledger(db: Session, limit: int = 50) -> dict:
    """选题账本（带 120s 缓存）：已讲过的话题 + 未使用灵感里被判为「可能已讲」的条目。"""
    cid = _cid(db) or 0
    return _cached(f"led:{cid}:{limit}", lambda: _ledger(db, limit))


def _ledger(db: Session, limit: int) -> dict:
    covered = covered_titles(db)
    cc = comment_clusters(db, limit=limit)
    covered_norm = [_norm(t) for t in covered]
    dup = [c for c in cc["clusters"] if _is_covered(c["title"], covered_norm)]
    return {
        "covered": covered[:limit],
        "covered_count": len(covered),
        "maybe_repeated": dup,
        "pool_comments": cc["total_comments"],
    }
