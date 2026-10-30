"""R-097：博主对标——对标最新15条取前3 + 最新一篇（R-174，原 R-152 前2+最新）+ “我能不能讲” + 按人设洗稿存草稿。

对标内容只做分析与改写来源，绝不进入主博主人设学习语料（D-028）；
转写补齐产生的对标素材归属对标博主（R-082），天然被主博主语料过滤排除。
"""

from __future__ import annotations

import json

from sqlalchemy import or_
from sqlalchemy.orm import Session, load_only

from ..core.pipeline import today_key  # noqa: F401 保留：未来可扩展
from ..models.kv import Kv
from ..models.platform import Creator, CreatorAccount, PlatformPost, PlatformPostStat
from ..models.video import Transcript, Video
from . import budget_settings
from .text_tags import strip_hashtags

# 互动权重：点赞1 + 收藏2 + 评论5（播放量只做参考不做主排序）
W_LIKE, W_FAV, W_COMMENT = 1, 2, 5

_EPOCH = __import__("datetime").datetime(2000, 1, 1)

# R-240 S1：作品列表只需展示/排序字段；不加载 raw（约 19KB/行，/top 全量会白搬几十 MB）
_POST_FIELDS = load_only(
    PlatformPost.id,
    PlatformPost.account_id,
    PlatformPost.platform,
    PlatformPost.platform_post_id,
    PlatformPost.title,
    PlatformPost.desc,
    PlatformPost.tags,
    PlatformPost.is_ad,
    PlatformPost.cover_url,
    PlatformPost.cover_path,
    PlatformPost.publish_time,
    PlatformPost.local_video_id,
    PlatformPost.work_id,
)



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


def _ad_video_ids(db: Session, linked_ids: list[int]) -> set[int]:
    """R-099/R-100：一次 IN 取「已标广告」的本地视频 id（绑定了它的帖也算广告）。"""
    if not linked_ids:
        return set()
    return {v.id for v in db.query(Video).filter(Video.is_ad.is_(True), Video.id.in_(linked_ids)).all()}


def _candidate_units(rows: list[PlatformPost], ad_vid_ids: set[int], limit: int) -> list[dict]:
    """把某个对标博主已排序的作品行转成候选单元（纯内存；R-240 单博主/批量两条路径共用）。"""
    # R-099/R-100/R-106：广告不对标；绑定了“已标广告本地视频”的帖也算广告；
    # 同款跨平台漏标(标题相同)也一并排除
    def _is_ad_post(p: PlatformPost) -> bool:
        return bool(p.is_ad or (p.local_video_id and p.local_video_id in ad_vid_ids))

    ad_norms = {_norm_title(x.title) for x in rows if _is_ad_post(x)}
    posts = [x for x in rows if not _is_ad_post(x) and _norm_title(x.title) not in ad_norms]
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


def candidates(db: Session, bm: Creator, limit: int = 15) -> list[dict]:
    """对标博主最新 limit 个“作品单元”（跨平台合并 work；未合并单帖）。R-109：10 → 15。"""
    acc_ids = [
        a.id
        for a in db.query(CreatorAccount).filter(
            CreatorAccount.creator_id == bm.id, CreatorAccount.enabled.is_(True)  # R-101
        ).all()
    ]
    if not acc_ids:
        return []
    rows = (
        db.query(PlatformPost)
        .options(_POST_FIELDS)
        .filter(PlatformPost.account_id.in_(acc_ids))
        .order_by(PlatformPost.publish_time.desc(), PlatformPost.id.desc())
        .all()
    )
    return _candidate_units(rows, _ad_video_ids(db, [p.local_video_id for p in rows if p.local_video_id]), limit)


def candidates_many(db: Session, bms: list[Creator], limit: int = 15) -> dict[int, list[dict]]:
    """R-240 S1：一次批量取多个对标的作品单元（accounts / posts / 广告视频各 1 条 SQL）。

    过滤/排序/去重口径与 `candidates()` 完全一致；供 `/api/benchmark/top` 首屏预取。
    """
    out: dict[int, list[dict]] = {bm.id: [] for bm in bms}
    if not bms:
        return out
    accounts = (
        db.query(CreatorAccount)
        .filter(CreatorAccount.creator_id.in_([bm.id for bm in bms]), CreatorAccount.enabled.is_(True))
        .all()
    )
    acc_to_bm = {a.id: a.creator_id for a in accounts}
    if not acc_to_bm:
        return out
    rows = (
        db.query(PlatformPost)
        .options(_POST_FIELDS)
        .filter(PlatformPost.account_id.in_(list(acc_to_bm)))
        .order_by(PlatformPost.publish_time.desc(), PlatformPost.id.desc())
        .all()
    )
    rows_by_bm: dict[int, list[PlatformPost]] = {bm_id: [] for bm_id in out}
    for p in rows:
        rows_by_bm[acc_to_bm[p.account_id]].append(p)
    ad_vid_ids = _ad_video_ids(db, [p.local_video_id for p in rows if p.local_video_id])
    for bm_id, bm_rows in rows_by_bm.items():
        out[bm_id] = _candidate_units(bm_rows, ad_vid_ids, limit)
    return out


def unit_key(unit: dict) -> str:
    """作品单元的稳定 key（前端卡片 key / R-114 分析结果 key 共用）。"""
    return f"w{unit['work_id']}" if unit.get("work_id") else f"p{unit['post'].id}"


def unit_text_map(db: Session, units: list[dict]) -> dict[int, str]:
    """R-240 S1：一次取「作品单元 → 已有转写文案」映射（post_id → text）。

    `videos LEFT JOIN transcripts` 一次查完，每个视频按 `transcript.id` 倒序取一条（防
    `Video.transcript` 的 uselist=False 重复行告警）；本地绑定视频优先、同 work 其它平台视频兜底，
    与 `_unit_text` 逐条查询的取值口径一致。
    """
    video_ids: set[int] = set()
    work_ids: set[int] = set()
    for unit in units:
        post = unit["post"]
        if post.local_video_id:
            video_ids.add(post.local_video_id)
        if unit.get("work_id"):
            work_ids.add(unit["work_id"])
    if not video_ids and not work_ids:
        return {}
    filters = []
    if video_ids:
        filters.append(Video.id.in_(video_ids))
    if work_ids:
        filters.append(Video.work_id.in_(work_ids))
    text_by_video: dict[int, str] = {}
    video_work: dict[int, int | None] = {}
    rows = (
        db.query(Video.id, Video.work_id, Transcript.corrected_text, Transcript.transcript_text)
        .outerjoin(Transcript, Transcript.video_id == Video.id)
        .filter(or_(*filters))
        .order_by(Video.id, Transcript.id.desc())
        .all()
    )
    for video_id, work_id, corrected, transcript in rows:
        if video_id in video_work:
            continue  # 同一视频的多条转写：只取 transcript.id 最大的一条
        video_work[video_id] = work_id
        text_by_video[video_id] = (corrected or transcript or "").strip()
    videos_by_work: dict[int, list[int]] = {}
    for video_id, work_id in video_work.items():
        if work_id:
            videos_by_work.setdefault(work_id, []).append(video_id)
    out: dict[int, str] = {}
    for unit in units:
        post = unit["post"]
        vids: list[int] = []
        if post.local_video_id:
            vids.append(post.local_video_id)
        if unit.get("work_id"):
            vids.extend(v for v in videos_by_work.get(unit["work_id"], []) if v not in vids)
        out[post.id] = next((text_by_video[v] for v in vids if text_by_video.get(v)), "")
    return out


def _unit_text(db: Session, unit: dict, *, video_text_map: dict[int, str] | None = None) -> str:
    """取该作品单元已有转写文案（对标转写产物归属对标，仅作分析/洗稿）。

    R-240 S1：传入 `video_text_map`（`unit_text_map()` 一次预取）时直接命中，不再逐条查库。
    """
    if video_text_map is not None:
        return video_text_map.get(unit["post"].id, "")
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


def _flag_unit_ad(db: Session, unit: dict) -> None:
    """把作品单元（含跨平台成员）标为广告，落库后 candidates() 自动排除。"""
    posts = unit.get("members") or [unit["post"]]
    changed = False
    for p in posts:
        if not p.is_ad:
            p.is_ad = True
            changed = True
    if changed:
        db.commit()


_AD_JUDGE_RULES = (
    "你是内容审核。判断这条视频口播是否属于「广告/商单/带货/引流」：包括明示广告、品牌商单、"
    "付费推广、卖课/训练营/社群/私域引流、推广自己或第三方的产品/工具/软件/小程序/App 等。"
    "普通知识内容里顺带提到某个工具、案例或书籍不算广告。"
)
_AD_JUDGE_SYSTEM = _AD_JUDGE_RULES + '只输出 JSON：{"is_ad":true或false,"reason":"简短原因"}'
_AD_BATCH_SYSTEM = (
    _AD_JUDGE_RULES
    + "一次判断多条候选，只输出 JSON："
    + '{"results":[{"id":<输入id>,"is_ad":true或false,"reason":"简短原因"}]}'
)


def _unit_is_ad(db: Session, unit: dict, text: str = "") -> bool:
    """判断对标作品单元是否为广告/软广（R-103/R-106）：已标记的直接命中；有文案则用 LLM 严格审核。

    平台列表接口不带广告标记（抖音 raw commerce_info.is_ad 恒 false），普通预打标也常把
    “推自家小程序/卖课/引流”判为非广告，故对标用更严格的独立审核；
    LLM 不可用时宁可不排除（不误杀），无文案的帖子无法判断。
    """
    posts = unit.get("members") or [unit["post"]]
    if any(p.is_ad for p in posts):
        return True
    if not (text or "").strip():
        return False
    try:
        title = (unit["post"].title or "")[:200]
        llm = _llm(db)
        data = llm.chat_json(
            [
                {"role": "system", "content": _AD_JUDGE_SYSTEM},
                {"role": "user", "content": f"标题：{title}\n\n口播文案：\n{(text or '')[:3000]}"},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        return bool((data or {}).get("is_ad", False))
    except Exception:  # noqa: BLE001 LLM 不可用不误杀
        return False


def _units_are_ad(db: Session, units: list[dict], texts: list[str]) -> dict[int, bool]:
    """R-240 S8：多条候选合并为一次 LLM 广告判定，返回 post_id → is_ad。

    - 已标记广告的单元直接命中，不再送审；
    - 输出契约 `{"results":[{"id":<输入id>,"is_ad":bool,...}]}`，解析失败/LLM 异常 → 全部按 False
      （宁可不误杀，与逐条判定口径一致）。
    """
    flags = {unit["post"].id: any(p.is_ad for p in (unit.get("members") or [unit["post"]])) for unit in units}
    batch = [
        {"id": unit["post"].id, "title": (unit["post"].title or "")[:200], "text": (text or "")[:3000]}
        for unit, text in zip(units, texts)
        if not flags[unit["post"].id] and (text or "").strip()
    ]
    if not batch:
        return flags
    try:
        data = _llm(db).chat_json(
            [
                {"role": "system", "content": _AD_BATCH_SYSTEM},
                {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        results = (data or {}).get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return flags
        for item in results:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            if raw_id is None:
                continue
            try:
                post_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if post_id in flags:
                flags[post_id] = bool(item.get("is_ad", False))
    except Exception:  # noqa: BLE001 LLM 不可用不误杀
        return flags
    return flags


def _sorted_by_score(db: Session, units: list[dict], stats_map: dict[int, dict] | None = None) -> list[dict]:
    """按互动分降序（R-152 抽取，供展示/补齐/目标选取共用）。"""
    if stats_map is None:
        stats_map = _stats_map(db, units)
    return sorted(units, key=lambda u: score_unit(db, u, stats_map), reverse=True)


# R-174 对标展示口径：前 N（互动分）+ 最新一篇 = 共 N+1 条（R-152 原为前 2 + 最新 = 3 条）
BENCH_TOP_N = 3


def target_units(
    db: Session,
    bm: Creator,
    limit_candidates: int = 15,
    with_text_first: bool = False,
    *,
    units: list[dict] | None = None,
    video_text_map: dict[int, str] | None = None,
    stats_map: dict[int, dict] | None = None,
) -> list[dict]:
    """R-174 对标展示口径：前 3 + 第四篇 = 该对标最新一篇（共 4 条；R-152 原为前 2 + 最新 = 3 条）。

    - 候选仍为最新 N 条（广告/同款漏标已在 candidates() 过滤）。
    - 前 3 = 按互动分降序前三条；with_text_first=True 时先把「有文案」的排前（R-106 展示口径）。
    - 第四篇 = 最新一篇（publish_time 最大）；若它已在前 3 里，则按互动分顺延补位（保底 4 条）。
    - 候选不足 4 条时返回可用的全部。
    - R-240 S1：`units/video_text_map/stats_map` 为 /top 批量预取结果（缺省时回退逐条查询）。
    """
    if units is None:
        units = candidates(db, bm, limit=limit_candidates)
    if not units:
        return []
    total = BENCH_TOP_N + 1
    ranked = _sorted_by_score(db, units, stats_map)
    if with_text_first:
        # R-106：有文案优先。每个单元只取一次文案（原来两个列表推导各调一次 _unit_text）
        if video_text_map is None:
            has_text = [bool(_unit_text(db, u)) for u in ranked]
        else:
            has_text = [bool(video_text_map.get(u["post"].id)) for u in ranked]
        ranked = [u for u, ok in zip(ranked, has_text) if ok] + [u for u, ok in zip(ranked, has_text) if not ok]
    latest = max(units, key=lambda u: (u["post"].publish_time or _EPOCH))
    picked: list[dict] = list(ranked[:BENCH_TOP_N])
    if latest not in picked:
        picked.append(latest)
    for unit in ranked:  # 顺延补位（重叠或候选不足时保底 4 条）
        if len(picked) >= total:
            break
        if unit not in picked:
            picked.append(unit)
    return picked[:total]


def ensure_top_with_text(db: Session, bm: Creator, limit_candidates: int = 15) -> list[dict]:  # R-109：10 → 15
    """R-174：取「前 3（互动分）+ 最新一篇」，逐条补齐转写；广告/无文案顺延，保底 4 条有文案。

    转写后仍无文案（识别为空/无声等）→ 顺延下一条顶上（R-097 Q3）。
    R-240 S8：统计 `_stats_map` 循环外一次；有文案候选凑批后合并为一次 LLM 广告判定。
    """
    units = candidates(db, bm, limit=limit_candidates)
    if not units:
        return []
    total = BENCH_TOP_N + 1
    stats_map = _stats_map(db, units)  # R-240 S8：循环外一次，避免每条候选重复查
    ranked = _sorted_by_score(db, units, stats_map)
    latest = max(units, key=lambda u: (u["post"].publish_time or _EPOCH))
    order: list[dict] = list(ranked[:BENCH_TOP_N])
    if latest not in order:
        order.append(latest)
    for unit in ranked:  # 前 3 / 最新 之外的按分顺延，用于补位
        if unit not in order:
            order.append(unit)

    picked: list[dict] = []
    pending: list[tuple[dict, str]] = []

    def _judge(batch: list[tuple[dict, str]]) -> None:
        """一批候选一次 LLM 判广；命中广告的落库标记并顺延。"""
        flags = _units_are_ad(db, [u for u, _t in batch], [t for _u, t in batch])
        for unit, text in batch:
            if len(picked) >= total:
                return
            if flags.get(unit["post"].id):
                _flag_unit_ad(db, unit)  # R-103：广告/商单不进对标，顺延下一条
                continue
            unit["text"] = text
            unit["score"] = score_unit(db, unit, stats_map)
            picked.append(unit)

    for unit in order:
        if len(picked) >= total:
            break
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
        pending.append((unit, text))
        # R-240 复核修复：按「还差几条」凑批，而不是固定 4 条 —— 避免尾部批次多触达 ≤3 个候选
        # 的文案补齐/广告判定（旧逐条实现判定到第 4 条即停；多处理的媒体补齐属旧版没有的副作用）。
        need = max(1, total - len(picked))
        if len(pending) >= need:  # 典型场景：4 条一批、全程 1 次 LLM
            _judge(pending)
            pending = []
            if len(picked) >= total:
                break
    if pending and len(picked) < total:
        _judge(pending)
    return picked


def _analysis_key(owner_id: int, key: str) -> str:
    return f"ba:{owner_id}:{key}"


def get_analysis(db: Session, owner_id: int | None, key: str) -> dict | None:
    """读取已保存的“能不能讲”分析结果（R-114：切页不丢）。"""
    if not owner_id:
        return None
    row = db.get(Kv, _analysis_key(owner_id, key))
    if row is None or not row.value:
        return None
    try:
        data = json.loads(row.value)
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None


def get_analysis_map(db: Session, owner_id: int | None, keys: list[str]) -> dict[str, dict]:
    """R-240 S1：一次 IN 取多个单元「能不能讲」分析结果（unit key → 已解析 dict）。"""
    out: dict[str, dict] = {}
    if not owner_id or not keys:
        return out
    prefix = _analysis_key(owner_id, "")
    for row in db.query(Kv).filter(Kv.key.in_([f"{prefix}{key}" for key in keys])).all():
        if not row.value:
            continue
        try:
            data = json.loads(row.value)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            out[row.key[len(prefix):]] = data
    return out


def set_analysis(db: Session, owner_id: int, key: str, data: dict) -> None:
    kv_key = _analysis_key(owner_id, key)
    row = db.get(Kv, kv_key)
    value = json.dumps(data, ensure_ascii=False)
    if row is None:
        db.add(Kv(key=kv_key, value=value))
    else:
        row.value = value
    db.commit()


def unit_payload(
    db: Session,
    unit: dict,
    stats_map: dict[int, dict] | None = None,
    owner_id: int | None = None,
    *,
    text: str | None = None,
    analysis_map: dict[str, dict] | None = None,
) -> dict:
    """作品单元序列化（含分数/文案/统计，供对标页展示与分析）。

    R-240 S1：`text` / `analysis_map` 为 /top 批量预取结果，缺省时回退逐条查询。
    """
    if stats_map is None:
        stats_map = _stats_map(db, [unit])
    posts = unit.get("members") or [unit["post"]]
    platforms = sorted({p.platform for p in posts})
    tags: list[str] = []
    for _p in posts:
        try:
            _ptags = json.loads(_p.tags or "[]")
            if isinstance(_ptags, list):
                for _t in _ptags:
                    if _t and _t not in tags:
                        tags.append(_t)
        except (TypeError, ValueError):
            pass
    likes = sum(int((stats_map.get(p.id) or {}).get("likes") or 0) for p in posts)
    fav = sum(int((stats_map.get(p.id) or {}).get("favorites") or 0) for p in posts)
    comments = sum(int((stats_map.get(p.id) or {}).get("comments") or 0) for p in posts)
    plays = sum(int((stats_map.get(p.id) or {}).get("plays") or 0) for p in posts)
    post = unit["post"]
    if text is None:
        text = unit.get("text")
    if text is None:
        text = _unit_text(db, unit)  # R-100：首屏也把已有 ASR 转写文案带出来
    key = unit_key(unit)
    analysis = analysis_map.get(key) if analysis_map is not None else get_analysis(db, owner_id, key)
    return {
        "key": key,
        "work_id": unit.get("work_id"),
        "post_id": post.id,
        "title": post.title or "",
        "desc": post.desc or "",
        "cover": post.cover_url_local or "",  # R-167：用本地封面（远端 URL 防盗链 403 裂开）
        "platforms": platforms,
        "likes": likes,
        "favorites": fav,
        "comments": comments,
        "plays": plays,
        "score": likes * W_LIKE + fav * W_FAV + comments * W_COMMENT,
        "has_text": bool(text),
        "text": text or "",
        "tags": tags,
        "analysis": analysis,
    }


def benchmarks_top(db: Session, owner: Creator) -> dict:
    """R-240 S1：对标页首屏（GET /api/benchmark/top）批量预取 + 组装。

    候选单元 / 转写文案 / 最新统计 / 已存分析各一次批量查询，SQL 数不随对标数增长；
    展示排序（有文案优先、前3+最新）与分析结果口径不变。
    """
    bms = benchmarks_of_owner(db, owner)
    units_by_bm = candidates_many(db, bms, limit=15)
    all_units = [unit for bm in bms for unit in units_by_bm.get(bm.id) or []]
    video_text_map = unit_text_map(db, all_units)
    stats_map = _stats_map(db, all_units)
    analysis_map = get_analysis_map(db, owner.id, [unit_key(unit) for unit in all_units])
    out = []
    for bm in bms:
        picked = target_units(
            db,
            bm,
            limit_candidates=15,
            with_text_first=True,
            units=units_by_bm.get(bm.id) or [],
            video_text_map=video_text_map,
            stats_map=stats_map,
        )
        items = [
            unit_payload(
                db,
                unit,
                stats_map=stats_map,
                owner_id=owner.id,
                text=video_text_map.get(unit["post"].id, ""),
                analysis_map=analysis_map,
            )
            for unit in picked
        ]
        out.append({"benchmark_id": bm.id, "name": bm.name, "note": bm.note or "", "items": items})
    return {"owner_id": owner.id, "owner_name": owner.name, "benchmarks": out}


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


REWRITE_SYSTEM = (
    "你是口播脚本代笔。只把给定素材当作**选题与信息线索**，"
    "用作者的人设口吻与表达习惯，写成作者能直接录的原创口播稿。\n"
    "内容硬要求（最重要，评审会按这条挑）：\n"
    "1) 全篇要有 2-4 条明确、可辩驳的论点（不是堆正确废话），并在 outlines 里逐条列出；\n"
    "2) 每条论点都必须配一个具体的支撑（事例/数据/亲身经历：谁/何时/发生了什么/结果，或具体数字），"
    "写进该条的 support，不要只喊口号；\n"
    "3) 优先用【站内真实素材·你的】里的真实经历/说法；没有就用【联网事实素材】里的至少 1 条"
    "（口语化转述，不要念 URL）；用到的联网编号写进 sources。"
    "【对标】素材只能当参考，**禁止写成你自己的经历**；\n"
    "4) 严禁编造具体数字/人名/机构/经历；没有可靠事实就只讲作者的判断，宁可不要数字；\n"
    "5) 删掉「要努力/要相信自己/坚持就会成功」这类正确但没用的空话。\n"
    "表达要求：不逐字抄袭，不复用原文的结构、核心比喻和句群；语言自然口语，"
    "像作者本人对着镜头说话（不是书面稿、不是念素材）。\n"
    "严格按末尾输出契约返回，不输出额外文字：\n"
    '只输出 JSON：{"title":"视频标题(与素材原标题不同)","cover_text":"3-8字封面字",'
    '"script":"完整口播脚本(1-2分钟)","tags":["3-6个内容标签"],'
    '"outlines":[{"claim":"本条论点(一句话)","support":"支撑它的具体事例/数据/经历"}],'
    '"sources":[引用到的联网事实编号，如[1,3]；没有则[]]}'
)


def _rewrite_user(db: Session, title: str, text: str, evidence_block: str = "") -> str:
    """参考改写（洗稿）的 user 上下文：作者完整人设+风格上下文 + 素材 + 联网证据（R-181/R-227）。"""
    from .generation import author_style_context

    parts = [
        author_style_context(db, title),
        "",
        "【参考素材·只借选题与信息线索，不借结构与措辞】",
        f"素材标题：{title}",
        "素材原文：",
        text[:4000],
    ]
    if evidence_block:
        parts += ["", evidence_block]
    return "\n".join(parts)


def _llm(db: Session | None = None):
    """对标分析用模型（R-139）：模型1 主用，失败自动降级模型2。"""
    from . import llm_router

    return llm_router.primary_llm(db, "benchmark")


def analyze_text(db: Session, owner: Creator, text: str) -> dict:
    """对给定文案做“我能不能讲”分析（对标页用，文案来自前端已 prepare 数据）。"""
    if not (text or "").strip():
        return {"can": False, "reason": "该素材还没有可用文案（先转写补齐）", "suggestion": ""}
    persona = "\n".join(persona_lines(db, owner)) or "（尚未建人设档案）"
    try:
        res = _llm(db).chat_json(
            [
                {"role": "system", "content": "你是我的内容选题顾问。只输出 JSON：{\"can\":bool,\"reason\":string,\"suggestion\":string}"},
                {"role": "user", "content": f"我的人设/红线：\n{persona}\n\n这是对标博主的一条视频文案：\n{text[:3000]}\n\n判断我能不能讲（是否契合我人设、我能不能讲得动、是否与我已有内容重复）："},
            ],
            temperature=0.4,
            max_tokens=budget_settings.budget_for(db, "benchmark_analyze"),
        )
        return {"can": bool(res.get("can")), "reason": str(res.get("reason") or ""), "suggestion": str(res.get("suggestion") or "")}
    except Exception as exc:  # noqa: BLE001
        return {"can": False, "reason": f"AI 分析暂不可用：{exc}", "suggestion": ""}


def _json_list(raw: str) -> list[str]:
    try:
        arr = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(x) for x in arr if x] if isinstance(arr, list) else []


def _posts_tags(posts: list[PlatformPost]) -> list[str]:
    tags: list[str] = []
    for p in posts:
        for t in _json_list(p.tags):
            if t not in tags:
                tags.append(t)
    return tags


def _video_asr_text(video: Video) -> str:
    tr = video.transcript
    if tr is None:
        return ""
    return (tr.corrected_text or tr.transcript_text or "").strip()


def _creator_of_posts(db: Session, posts: list[PlatformPost]) -> Creator | None:
    post = posts[0]
    if post.account_id:
        acc = db.get(CreatorAccount, post.account_id)
        if acc is not None:
            return db.get(Creator, acc.creator_id)
    if post.work_id:
        from ..models.work import Work

        work = db.get(Work, post.work_id)
        if work is not None and work.creator_id:
            return db.get(Creator, work.creator_id)
    return None


def _source_payload(
    owner: Creator,
    creator: Creator | None,
    *,
    title: str,
    text: str,
    key: str,
    post_id: int | None,
    work_id: int | None,
    tags: list[str],
) -> dict:
    if creator is not None and creator.id == owner.id:
        raise ValueError("这是主博主自己的素材，不需要洗稿")
    if not (text or "").strip():
        raise ValueError("该素材还没有可用文案（先把语音转成文字）")
    return {
        "title": (title or "").strip(),
        "text": text.strip(),
        "key": key,
        "benchmark_name": creator.name if (creator is not None and creator.kind == "benchmark") else "",
        "post_id": post_id,
        "work_id": work_id,
        "tags": tags,
    }


def resolve_rewrite_source(
    db: Session, owner: Creator, video_id: int = 0, post_id: int = 0, work_id: int = 0
) -> dict:
    """R-152：素材库「洗稿」入口——解析出 rewrite_worker 需要的 payload。

    支持三种来源：本地素材 video_id、云端作品 work_id、云端单条 post_id。
    文案只取 ASR 转写稿（与对标口径一致，R-099）；非主博主素材才允许洗稿。
    """
    if video_id:
        video = db.get(Video, video_id)
        if video is None:
            raise ValueError("素材不存在或已删除")
        creator = db.get(Creator, video.creator_id) if video.creator_id else None
        bound = db.query(PlatformPost).filter(PlatformPost.local_video_id == video.id).all()
        if not bound and video.work_id:
            bound = db.query(PlatformPost).filter(PlatformPost.work_id == video.work_id).all()
        bound.sort(key=lambda m: (m.publish_time or _EPOCH), reverse=True)
        first = bound[0] if bound else None
        topics = _json_list(video.main_topics)
        tags = topics + [t for t in _json_list(video.tags) if t not in topics]
        return _source_payload(
            owner,
            creator,
            title=strip_hashtags(video.title or (first.title if first else "") or ""),
            text=_video_asr_text(video),
            key=f"v{video.id}",
            post_id=first.id if first else None,
            work_id=video.work_id or (first.work_id if first else None),
            tags=tags,
        )

    posts: list[PlatformPost] = []
    if work_id:
        posts = db.query(PlatformPost).filter(PlatformPost.work_id == work_id).all()
        key = f"w{work_id}"
    elif post_id:
        p = db.get(PlatformPost, post_id)
        posts = [p] if p is not None else []
        key = f"p{post_id}"
    else:
        raise ValueError("缺少素材标识")
    if not posts:
        raise ValueError("素材不存在或已删除")
    posts.sort(key=lambda m: (m.publish_time or _EPOCH), reverse=True)
    unit: dict = {"work_id": posts[0].work_id, "post": posts[0]}
    if posts[0].work_id:
        unit["members"] = posts
    return _source_payload(
        owner,
        _creator_of_posts(db, posts),
        title=strip_hashtags(posts[0].title or ""),
        text=_unit_text(db, unit),
        key=key,
        post_id=posts[0].id,
        work_id=posts[0].work_id,
        tags=_posts_tags(posts),
    )


def analyze_worker(db: Session, payload: dict, update=None) -> dict:
    """后台任务：AI 分析（R-116：落后台留痕，切页可恢复）。"""
    owner = db.get(Creator, int(payload.get("owner_id") or 0))
    if owner is None:
        raise ValueError("主博主不存在")
    res = analyze_text(db, owner, payload.get("text") or "")
    key = payload.get("key") or ""
    if key:
        set_analysis(
            db,
            owner.id,
            key,
            {
                "can": bool(res.get("can")),
                "reason": str(res.get("reason") or ""),
                "suggestion": str(res.get("suggestion") or ""),
            },
        )
    if update:
        update(80, "分析完成")
    return {"key": key, **res}


def rewrite_worker(db: Session, payload: dict, update=None) -> dict:
    """后台任务：洗稿（R-116 后台留痕；R-117 记录来源素材；R-118 双模型多轮讨论）。

    R-173：失败时给草稿留下「中断」标记（`run_rewrite_debate` 会把 draft_id 回写进 payload），
    否则卡片会一直显示「讨论中」。
    """
    from . import draft_status
    from .debate import run_rewrite_debate

    if update:
        update(10, "启动双模型讨论…")
    try:
        res = run_rewrite_debate(db, payload)
    except Exception as exc:  # noqa: BLE001 标记后原样抛出，交给任务运行器记 failed + 通知
        try:
            draft_status.set_failed(
                db,
                int(payload.get("draft_id") or 0),
                f"洗稿中断：{str(exc)[:150]}",
                kind="rewrite",
            )
        except Exception:  # noqa: BLE001 标记失败不能掩盖原始错误
            db.rollback()
        raise
    return {"key": payload.get("key") or "", **res}


def rerun_benchmarks(db: Session, owner: Creator, update=None, refetch: bool = True) -> dict:
    """R-102/R-109/R-152/R-174：重跑当前主博主所有对标——逐账号重捞最新15条 + 自动补「前3+最新」文案。

    refetch=True（手动「重新对标」）：重捞最新 15 条后重算「前3+最新」；
    refetch=False（R-109 每日同步完成后自动触发）：不重复拉取，仅基于已同步数据重算/补缺转写。
    update(pct, note) 可选：由后台任务运行器注入，实时回写进度（R-081 同款）。

    R-240 M2：按对标博主 `sync_pool.gather` 并发（每博主独立 Session，DB Session 不跨线程），
    进度由主线程 `on_result` 累计；BudgetExceeded 用 cancel 事件让后续博主快速退出；
    单博主失败不阻断其它，返回结构不变。
    """
    from ..core.timeutil import now as _app_now
    from .platform.budget import BudgetExceeded
    from .platform_sync import sync_account
    from .sync_pool import gather, new_cancel, pool_size, session_factory

    bms = benchmarks_of_owner(db, owner)
    if not bms:
        raise ValueError("还没有对标博主，先去「博主管理」添加")
    jobs = [(bm.id, bm.name or f"对标#{bm.id}") for bm in bms]
    order = {bm_id: index for index, (bm_id, _name) in enumerate(jobs)}
    total = len(jobs)
    summary: list[dict] = []
    ok_count = 0
    text_count = 0
    done = 0
    cancel = new_cancel()
    budget_errors: list[BudgetExceeded] = []
    factory = session_factory(db)

    def _run_one(job: tuple[int, str]) -> dict:
        bm_id, _name = job
        if cancel.is_set():
            raise BudgetExceeded("今日 TikHub 请求预算已用完，后续对标已取消")
        session = factory()
        try:
            bm = session.get(Creator, bm_id)
            if bm is None:
                raise ValueError("对标博主不存在")
            accounts = (
                session.query(CreatorAccount)
                .filter(CreatorAccount.creator_id == bm.id, CreatorAccount.enabled.is_(True))
                .order_by(CreatorAccount.id)
                .all()
            )
            if refetch:
                for acc in accounts:
                    if cancel.is_set():
                        raise BudgetExceeded("今日 TikHub 请求预算已用完，后续对标已取消")
                    try:
                        sync_account(session, acc, scope="benchmark", top_n=15, with_comments=False)  # R-109：10 → 15
                        acc2 = session.get(CreatorAccount, acc.id)
                        if acc2 is not None:
                            acc2.sync_status = "done"
                            acc2.sync_message = ""
                            acc2.last_sync_at = _app_now()
                            session.commit()
                    except BudgetExceeded:
                        raise
                    except Exception:  # noqa: BLE001 单账号失败不影响该对标其它账号
                        session.rollback()
            if cancel.is_set():  # R-240 复核：预算已耗尽 → 不再做补齐媒体/转写
                raise BudgetExceeded("今日 TikHub 请求预算已用完，后续对标已取消")
            picked = ensure_top_with_text(session, bm, limit_candidates=15)  # R-109：10 → 15
            return {"benchmark_id": bm_id, "name": _name, "top_with_text": len(picked), "error": ""}
        finally:
            session.close()

    def _on_result(job: tuple[int, str], result: object) -> None:
        nonlocal done, ok_count, text_count
        bm_id, name = job
        if isinstance(result, BudgetExceeded):
            if not budget_errors:
                budget_errors.append(result)
                cancel.set()
            return
        done += 1
        if isinstance(result, Exception):
            summary.append({"benchmark_id": bm_id, "name": name, "top_with_text": 0, "error": str(result)[:200]})
            note = "失败"
        else:
            payload = result if isinstance(result, dict) else {}
            count = int(payload.get("top_with_text") or 0)
            ok_count += 1
            text_count += count
            summary.append({"benchmark_id": bm_id, "name": name, "top_with_text": count, "error": ""})
            note = f"完成（前3+最新有文案 {count} 条）"
        if update is not None:
            overall = max(5, min(99, int(done / total * 100)))
            update(overall, f"[{done}/{total}] {name}：{note}")

    if update is not None:
        update(5, f"[1/{total}] {jobs[0][1]}：{'捞数据中…' if refetch else '重算对标中…'}")
    gather(_run_one, jobs, workers=pool_size("creator"), on_result=_on_result)
    if budget_errors:
        raise budget_errors[0]
    summary.sort(key=lambda row: order.get(row["benchmark_id"], 0))
    return {
        "title": f"共 {ok_count}/{total} 个对标已更新（前3+最新有文案 {text_count} 条）",
        "summary": summary,
        "benchmark_count": total,
        "ok_count": ok_count,
        "top_with_text_total": text_count,
    }


def rerun_worker(db: Session, payload: dict, update=None) -> dict:
    """后台任务体（R-102/R-105/R-109）：按 owner_id 重跑当前主博主所有对标。

    refetch=True（默认，手动「重新对标」）重捞最新 15 条；
    refetch=False（R-109：每日同步完成后自动触发）不重复拉取、只重算「前3+最新」。
    """
    from ..models.platform import Creator

    owner = db.get(Creator, int((payload or {}).get("owner_id") or 0))
    if owner is None:
        raise ValueError("主博主不存在，请先创建并切换主博主")
    refetch = bool((payload or {}).get("refetch", True))
    return rerun_benchmarks(db, owner, update=update, refetch=refetch)


def maybe_start_benchmark_rerun(db: Session, refetch: bool = True) -> str:
    """「重新对标」守卫 + 启动（R-109：每日同步完成后自动触发，refetch=False 不重捞）。

    返回结果：no_owner / no_benchmark / already_running / started:<task_id>。
    无对标或已有重新对标任务在跑时静默跳过（不产生失败通知）。
    """
    from ..models.task import BackgroundTask
    from .creator_service import get_current_creator

    owner = get_current_creator(db)
    if owner is None:
        return "no_owner"
    if not benchmarks_of_owner(db, owner):
        return "no_benchmark"
    running = (
        db.query(BackgroundTask)
        .filter(
            BackgroundTask.kind == "benchmark_rerun",
            BackgroundTask.status.in_(["pending", "running"]),
        )
        .first()
    )
    if running is not None:
        return "already_running"
    from ..tasks import start_task

    task_id = start_task("benchmark_rerun", {"owner_id": owner.id, "refetch": refetch}, rerun_worker)
    return f"started:{task_id}"


# ---------- R-202：转写补齐改为后台任务（原同步，转写耗时几分钟） ----------

def prepare_worker(db: Session, payload: dict, update=None) -> dict:
    bm = db.get(Creator, int(payload.get("benchmark_id") or 0))
    if bm is None:
        raise ValueError("对标博主不存在")
    picked = ensure_top_with_text(db, bm, limit_candidates=15)
    return {"benchmark_id": bm.id, "name": bm.name, "count": len(picked)}
