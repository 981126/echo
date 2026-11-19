"""作者内容资产的提取、原文校验、去重、检索与学习（R-263）。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from typing import Any, Iterable

from sqlalchemy.orm import Session, selectinload

from ..core.retrieval import TfidfIndex, tokenize
from ..core.timeutil import now as _app_now
from ..models.author_generation import AuthorAsset
from ..models.video import Transcript, Video
from . import llm_router
from .generation_validators import json_dict, json_list
from .prompt_service import get_prompt

ASSET_KINDS = {"fact", "viewpoint", "experience", "structure", "expression"}
TOPIC_KINDS = {"fact", "viewpoint", "experience"}

AUTHOR_ASSET_EXTRACT_SYSTEM = """你在整理一位作者自己的口播内容资产，不是在创作。
只能提取原文明确存在的信息，不得补充时间、数字、人物、结果、因果或适用条件。
资产类型：fact=作者稳定事实；viewpoint=带理由和边界的观点；experience=目标/行动/结果明确或不明的真实经历；
structure=开头承诺/推进/转折/收尾方式；expression=句长节奏/称呼/比喻/情绪变化。
每条资产必须原子化、保留成立条件，并附原文逐字 quote；structure/expression 聚合资产至少引用两篇不同 video_id。
只输出 JSON：{"assets":[{"asset_kind":"fact|viewpoint|experience|structure|expression","content":"一条资产",
"context":{"topic":"议题","conditions":"适用条件","limitations":"边界或未知项"},
"evidence":[{"video_id":123,"quote":"与对应视频原文逐字一致的连续片段"}]}]}。
没有可靠资产就返回空数组，绝不能编造。"""


def transcript_text(video: Video) -> str:
    transcript = video.transcript
    if transcript is None:
        return ""
    return (transcript.corrected_text or transcript.transcript_text or "").strip()


def content_hash(creator_id: int, asset_kind: str, content: str) -> str:
    normalized = re.sub(r"\s+", "", content or "").lower()
    return hashlib.sha256(f"{creator_id}:{asset_kind}:{normalized}".encode("utf-8")).hexdigest()


def _transcript_map(videos: Iterable[Video]) -> dict[int, tuple[Transcript, str]]:
    return {
        video.id: (video.transcript, transcript_text(video))
        for video in videos
        if video.transcript is not None and transcript_text(video)
    }


def resolve_evidence(
    raw: Any,
    transcripts: dict[int, tuple[Transcript, str]],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return resolved
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            video_id = int(item.get("video_id") or 0)
        except (TypeError, ValueError):
            continue
        pair = transcripts.get(video_id)
        quote = str(item.get("quote") or "").strip()
        if pair is None or not quote:
            continue
        transcript, text = pair
        start = text.find(quote)
        if start < 0:
            continue
        resolved.append(
            {
                "video_id": video_id,
                "transcript_id": transcript.id,
                "start_char": start,
                "end_char": start + len(quote),
                "quote": quote,
            }
        )
    return resolved


def validate_asset_evidence(db: Session, asset: AuthorAsset) -> bool:
    refs = json_list(asset.evidence_refs)
    if not refs:
        return False
    video_refs = [ref for ref in refs if isinstance(ref, dict) and ref.get("video_id")]
    other_refs = [ref for ref in refs if ref not in video_refs]
    video_ids = [ref.get("video_id") for ref in video_refs]
    rows = (
        db.query(Video)
        .options(selectinload(Video.transcript))
        .filter(Video.id.in_(video_ids), Video.creator_id == asset.creator_id, Video.is_ad.is_(False))
        .all()
        if video_ids
        else []
    )
    transcripts = _transcript_map(rows)
    if len(resolve_evidence(video_refs, transcripts)) != len(video_refs):
        return False
    from ..models.author_generation import GenerationRun
    from ..models.draft import Draft
    from ..models.draft_version import DraftVersion

    for ref in other_refs:
        if not isinstance(ref, dict):
            return False
        quote = str(ref.get("quote") or "")
        if ref.get("draft_id"):
            draft = db.get(Draft, int(ref["draft_id"]))
            version = db.get(DraftVersion, int(ref.get("version_id") or 0)) if ref.get("version_id") else None
            text = version.script if version is not None else draft.script if draft is not None else ""
            if draft is None or draft.creator_id != asset.creator_id or not quote or quote not in text:
                return False
        elif ref.get("run_id"):
            run = db.get(GenerationRun, int(ref["run_id"]))
            if run is None or run.creator_id != asset.creator_id or not quote:
                return False
            if quote not in run.topic + "\n" + run.input_context:
                return False
        else:
            return False
    return True


def upsert_asset(
    db: Session,
    *,
    creator_id: int,
    asset_kind: str,
    source_kind: str,
    source_id: str,
    content: str,
    context: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
    status: str,
    quality_score: float,
) -> AuthorAsset:
    digest = content_hash(creator_id, asset_kind, content)
    row = (
        db.query(AuthorAsset)
        .filter(
            AuthorAsset.creator_id == creator_id,
            AuthorAsset.asset_kind == asset_kind,
            AuthorAsset.content_hash == digest,
        )
        .first()
    )
    if row is None:
        row = AuthorAsset(
            creator_id=creator_id,
            asset_kind=asset_kind,
            source_kind=source_kind,
            source_id=source_id,
            content=content.strip(),
            content_hash=digest,
        )
        db.add(row)
    old_refs = json_list(row.evidence_refs)
    merged = old_refs + [ref for ref in evidence_refs if ref not in old_refs]
    row.context_json = json.dumps(context, ensure_ascii=False)
    row.evidence_refs = json.dumps(merged, ensure_ascii=False)
    row.quality_score = max(float(row.quality_score or 0), quality_score)
    row.status = status if row.status != "active" or status == "archived" else "active"
    row.updated_at = _app_now()
    return row


def extract_assets_from_videos(
    db: Session,
    videos: list[Video],
    *,
    llm: Any | None = None,
    aggregate: bool = False,
) -> dict[str, int]:
    usable = [video for video in videos if not video.is_ad and transcript_text(video)]
    if not usable:
        return {"created": 0, "rejected": 0}
    client = llm or llm_router.primary_llm(db, "persona_updates")
    transcripts = _transcript_map(usable)
    source = "\n\n".join(
        f"【video_id={video.id}｜标题={video.title or '无题'}】\n{transcript_text(video)}"
        for video in usable
    )
    data = client.chat_json(
        [
            {"role": "system", "content": get_prompt("author_asset_extract", db)},
            {
                "role": "user",
                "content": ("请聚合多篇资产，结构与表达必须引用至少两篇。" if aggregate else "请逐篇提取这篇原文的资产。")
                + "\n\n"
                + source,
            },
        ],
        temperature=0.2,
        max_tokens=8000,
        require=("assets",),
    )
    stats = {"created": 0, "rejected": 0}
    for item in data.get("assets") or []:
        if not isinstance(item, dict):
            stats["rejected"] += 1
            continue
        kind = str(item.get("asset_kind") or "").strip()
        content = str(item.get("content") or "").strip()
        refs = resolve_evidence(item.get("evidence"), transcripts)
        distinct_videos = {ref["video_id"] for ref in refs}
        valid = bool(kind in ASSET_KINDS and content and refs)
        if aggregate and kind in {"structure", "expression"} and len(distinct_videos) < 2:
            valid = False
        if not valid:
            stats["rejected"] += 1
            continue
        raw_context = item.get("context")
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        status = "active" if kind in TOPIC_KINDS or aggregate else "candidate"
        source_id = f"video:{usable[0].id}" if len(usable) == 1 else ""
        published = all(video.status == "published" for video in usable)
        upsert_asset(
            db,
            creator_id=usable[0].creator_id or 0,
            asset_kind=kind,
            source_kind="published" if published else "asr",
            source_id=source_id,
            content=content,
            context=context,
            evidence_refs=refs,
            status=status,
            quality_score=(1.0 if published else 0.8) if len(refs) == 1 else 1.0,
        )
        stats["created"] += 1
    db.commit()
    return stats


def rebuild_author_assets(
    db: Session,
    creator_id: int,
    *,
    llm: Any | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from ..db import SessionLocal

    videos = (
        db.query(Video)
        .options(selectinload(Video.transcript))
        .filter(Video.creator_id == creator_id, Video.is_ad.is_(False))
        .order_by(Video.id)
        .all()
    )
    usable = [video for video in videos if transcript_text(video)]
    db.query(AuthorAsset).filter(
        AuthorAsset.creator_id == creator_id, AuthorAsset.source_kind.in_(["asr", "published"])
    ).update({"status": "archived"}, synchronize_session=False)
    db.commit()
    report: dict[str, Any] = {"total": len(usable), "succeeded": 0, "failed": 0, "rejected": 0, "errors": []}

    def _one(video_id: int) -> dict[str, int]:
        session = SessionLocal()
        try:
            video = session.get(Video, video_id)
            if video is None:
                raise ValueError("视频不存在")
            client = llm or llm_router.primary_llm(session, "persona_updates")
            return extract_assets_from_videos(session, [video], llm=client)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=min(4, max(len(usable), 1)), thread_name_prefix="author-assets") as executor:
        futures = {executor.submit(_one, video.id): video.id for video in usable}
        for index, future in enumerate(as_completed(futures), 1):
            video_id = futures[future]
            if progress:
                progress(index, len(usable), f"已完成 {index}/{len(usable)} 篇 ASR")
            try:
                result = future.result()
                report["succeeded"] += 1
                report["rejected"] += result["rejected"]
            except Exception as exc:  # noqa: BLE001 单篇失败不丢其它篇，报告必须留痕
                report["failed"] += 1
                report["errors"].append({"video_id": video_id, "error": str(exc)[:300]})
    if len(usable) >= 2:
        try:
            client = llm or llm_router.primary_llm(db, "persona_updates")
            result = extract_assets_from_videos(db, usable[:12], llm=client, aggregate=True)
            report["rejected"] += result["rejected"]
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            report["errors"].append({"aggregate": True, "error": str(exc)[:300]})
    style_count = db.query(AuthorAsset).filter(
        AuthorAsset.creator_id == creator_id,
        AuthorAsset.asset_kind.in_(["structure", "expression"]),
        AuthorAsset.status == "active",
    ).count()
    if not style_count:
        build_programmatic_style_assets(db, creator_id, usable[:12])
    counts: dict[str, int] = {}
    for kind, status in (
        db.query(AuthorAsset.asset_kind, AuthorAsset.status)
        .filter(AuthorAsset.creator_id == creator_id)
        .all()
    ):
        key = f"{kind}:{status}"
        counts[key] = counts.get(key, 0) + 1
    report["counts"] = counts
    return report


def build_programmatic_style_assets(db: Session, creator_id: int, videos: list[Video]) -> int:
    """用真实样本统计补结构/表达，避免模型聚合失败导致两类资产长期为空。"""
    from ..core.style_profile import build_style_profile

    usable = [video for video in videos if video.creator_id == creator_id and not video.is_ad and transcript_text(video)]
    if len(usable) < 2:
        return 0

    def evidence(video: Video, quote: str) -> dict[str, Any]:
        transcript = video.transcript
        assert transcript is not None
        text = transcript_text(video)
        start = text.index(quote)
        return {
            "video_id": video.id,
            "transcript_id": transcript.id,
            "start_char": start,
            "end_char": start + len(quote),
            "quote": quote,
        }

    openings = [re.split(r"[。！？!?…\n]+", transcript_text(video), maxsplit=1)[0].strip() for video in usable]
    endings = [
        [sentence.strip() for sentence in re.split(r"[。！？!?…\n]+", transcript_text(video)) if sentence.strip()][-1]
        for video in usable
    ]
    question_count = sum(1 for text in openings if text.endswith(("？", "?")))
    action_count = sum(
        1 for text in endings if re.search(r"先|把|去|别|不要|可以|应该|记得|直接|行动|试|做", text)
    )
    structure_refs = [evidence(video, quote) for video, quote in zip(usable[:2], openings[:2])]
    structure_refs += [evidence(video, quote) for video, quote in zip(usable[-2:], endings[-2:])]
    upsert_asset(
        db,
        creator_id=creator_id,
        asset_kind="structure",
        source_kind="published" if all(video.status == "published" for video in usable) else "asr",
        source_id="",
        content=(
            f"抽样 {len(usable)} 篇：{question_count} 篇以问题/反问开场，{action_count} 篇以行动或建议收尾；"
            "主体按开场承诺→具体论证→结尾回扣组织，结构随主题变化，不设固定模板"
        ),
        context={"sample_size": len(usable), "generated_by": "programmatic_counts"},
        evidence_refs=structure_refs,
        status="active",
        quality_score=1.0,
    )
    profile = build_style_profile([transcript_text(video) for video in usable])
    expression_refs = [evidence(video, opening) for video, opening in zip(usable[:2], openings[:2])]
    upsert_asset(
        db,
        creator_id=creator_id,
        asset_kind="expression",
        source_kind="published" if all(video.status == "published" for video in usable) else "asr",
        source_id="",
        content=(
            f"句子平均 {profile['avg_sent_len']} 字（中位 {profile['median_sent_len']}）；"
            f"提问占比 {profile['question_ratio']}，感叹占比 {profile['exclaim_ratio']}；"
            "高频词仅作节奏参考，不机械塞入口头禅"
        ),
        context={"sample_size": len(usable), "top_phrases": profile.get("top_phrases") or []},
        evidence_refs=expression_refs,
        status="active",
        quality_score=1.0,
    )
    db.commit()
    return 2


def _cosine(query: str, document: str) -> float:
    left, right = Counter(tokenize(query)), Counter(tokenize(document))
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(term, 0) for term, value in left.items())
    denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(
        sum(value * value for value in right.values())
    )
    return dot / denominator if denominator else 0.0


def _performance(asset: AuthorAsset, maximum: float) -> float:
    stats = json_dict(asset.usage_stats)
    raw = stats.get("performance")
    if not isinstance(raw, (int, float)) or raw < 0:
        return 0.4
    if maximum <= 0:
        return 0.4
    return min(math.log1p(float(raw)) / maximum, 1.0)


def retrieve_author_assets(db: Session, creator_id: int, topic: str, input_text: str = "") -> list[dict[str, Any]]:
    rows = (
        db.query(AuthorAsset)
        .filter(AuthorAsset.creator_id == creator_id, AuthorAsset.status == "active")
        .order_by(AuthorAsset.updated_at.desc(), AuthorAsset.id.desc())
        .all()
    )
    rows = [asset for asset in rows if validate_asset_evidence(db, asset)]
    topic_rows = [asset for asset in rows if asset.asset_kind in TOPIC_KINDS]
    query = f"{topic}\n{input_text}".strip()
    documents = [asset.content + " " + asset.context_json for asset in topic_rows]
    index = TfidfIndex().build(documents)
    hits = index.search(query, top_k=40)
    candidates: list[tuple[AuthorAsset, float]] = []
    for hit in hits:
        asset = topic_rows[int(hit["index"])]
        relevance = _cosine(query, documents[int(hit["index"])])
        if relevance >= 0.08:
            candidates.append((asset, relevance))
    maximum_relevance = max((value for _asset, value in candidates), default=1.0)
    maximum_performance = max(
        (math.log1p(float(json_dict(asset.usage_stats).get("performance") or 0)) for asset in rows),
        default=0.0,
    )
    ranked: list[dict[str, Any]] = []
    for asset, relevance in candidates:
        refs = json_list(asset.evidence_refs)
        evidence_strength = 1.0 if len({ref.get("video_id") for ref in refs}) >= 2 else 0.8
        confirmation = {"published": 1.0, "draft_edit": 0.9, "author_input": 0.9}.get(
            asset.source_kind, 0.8
        )
        normalized_relevance = relevance / maximum_relevance if maximum_relevance else 0.0
        performance = _performance(asset, maximum_performance)
        score = 100 * (
            0.45 * normalized_relevance
            + 0.25 * evidence_strength
            + 0.20 * confirmation
            + 0.10 * performance
        )
        ranked.append(
            {
                "asset": asset,
                "id": asset.id,
                "kind": asset.asset_kind,
                "content": asset.content,
                "context": json_dict(asset.context_json),
                "evidence_refs": refs,
                "score": round(score, 3),
                "score_parts": {
                    "topic_relevance": round(normalized_relevance, 4),
                    "evidence_strength": evidence_strength,
                    "author_confirmation": confirmation,
                    "normalized_performance": round(performance, 4),
                },
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    selected = ranked[:12]
    for kind in ("structure", "expression"):
        for asset in [row for row in rows if row.asset_kind == kind][:2]:
            selected.append(
                {
                    "asset": asset,
                    "id": asset.id,
                    "kind": asset.asset_kind,
                    "content": asset.content,
                    "context": json_dict(asset.context_json),
                    "evidence_refs": json_list(asset.evidence_refs),
                    "score": 100.0,
                    "score_parts": {"reason": "近期高确认结构/表达资产"},
                }
            )
    used_at = _app_now()
    for item in selected:
        asset = item.pop("asset")
        asset.last_used_at = used_at
        stats = json_dict(asset.usage_stats)
        stats["used"] = int(stats.get("used") or 0) + 1
        asset.usage_stats = json.dumps(stats, ensure_ascii=False)
    db.commit()
    return selected


def public_asset(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "asset"}


def assets_prompt(selected: list[dict[str, Any]]) -> str:
    return json.dumps(
        [
            {
                "id": item["id"],
                "kind": item["kind"],
                "content": item["content"],
                "context": item["context"],
                "evidence": item["evidence_refs"],
            }
            for item in selected
        ],
        ensure_ascii=False,
    )


def author_asset_task(db: Session, payload: dict[str, Any], update: Any = None) -> dict[str, Any]:
    creator_id = int(payload.get("creator_id") or 0)
    video_id = int(payload.get("video_id") or 0)
    if not creator_id:
        raise ValueError("缺少作者资产所属主博主")
    if video_id:
        video = db.get(Video, video_id)
        if video is None or video.creator_id != creator_id or video.is_ad:
            return {"created": 0, "rejected": 0, "skipped": True}
        result = extract_assets_from_videos(db, [video])
        transcript_count = (
            db.query(Transcript)
            .join(Video, Video.id == Transcript.video_id)
            .filter(Video.creator_id == creator_id, Video.is_ad.is_(False))
            .count()
        )
        if transcript_count % 5 == 0:
            videos = (
                db.query(Video)
                .options(selectinload(Video.transcript))
                .filter(Video.creator_id == creator_id, Video.is_ad.is_(False))
                .order_by(Video.id.desc())
                .limit(12)
                .all()
            )
            extract_assets_from_videos(db, videos, aggregate=True)
        return result
    def progress(index: int, total: int, note: str) -> None:
        if update:
            update(max(1, int(index / max(total, 1) * 95)), note)
    report = rebuild_author_assets(db, creator_id, progress=progress)
    if not report["errors"]:
        from ..models.kv import Kv

        key = f"author_assets_rebuilt:{creator_id}"
        if db.get(Kv, key) is None:
            db.add(Kv(key=key, value=str(report["total"])))
        db.commit()
    if update:
        update(100, "作者内容资产整理完成")
    return report


def maybe_rebuild_author_assets_on_startup() -> None:
    from ..models.platform import Creator
    from ..db import SessionLocal
    from ..tasks import start_task

    db = SessionLocal()
    try:
        from ..models.kv import Kv

        owners = db.query(Creator).filter(Creator.kind == "owner").all()
        for owner in owners:
            if db.get(Kv, f"author_assets_rebuilt:{owner.id}") is not None:
                continue
            videos = (
                db.query(Video)
                .options(selectinload(Video.transcript))
                .filter(Video.creator_id == owner.id, Video.is_ad.is_(False))
                .all()
            )
            if any(transcript_text(video) for video in videos):
                start_task("author_assets", {"creator_id": owner.id}, author_asset_task)
    finally:
        db.close()


__all__ = [
    "AUTHOR_ASSET_EXTRACT_SYSTEM",
    "author_asset_task",
    "assets_prompt",
    "build_programmatic_style_assets",
    "content_hash",
    "extract_assets_from_videos",
    "public_asset",
    "rebuild_author_assets",
    "resolve_evidence",
    "retrieve_author_assets",
    "transcript_text",
    "upsert_asset",
    "validate_asset_evidence",
]
