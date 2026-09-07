"""内容导入流水线：转写 → AI 校对 → 预打标签；人设初始化。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import func

from ..config import get_settings
from ..core.transcript import normalize_text
from ..models.persona import PersonaTag
from ..models.video import Transcript, Video
from .llm import LLMError
from .persona import PersonaService
from .prompt_service import get_prompt
from .transcription import Transcriber, TranscriptionError
from .creator_service import current_creator_id


def suggest_persona_updates(db, video, transcript_text: str) -> None:
    """新视频（非广告）进入后，自动建议人设扩充（待作者确认）。"""
    if video.is_ad or not transcript_text:
        return
    cid = video.creator_id or current_creator_id(db)
    current_q = db.query(PersonaTag).filter(PersonaTag.status == "confirmed")
    if cid:
        current_q = current_q.filter(PersonaTag.creator_id == cid)
    current = current_q.all()
    result = PersonaService().suggest_updates(transcript_text, current)
    if not result["suggestions"]:
        return
    latest_q = db.query(PersonaTag).order_by(PersonaTag.version.desc())
    if cid:
        latest_q = latest_q.filter(PersonaTag.creator_id == cid)
    latest = latest_q.first()
    version = latest.version if latest else 1
    for item in result["suggestions"]:
        dup_q = db.query(PersonaTag).filter(
            PersonaTag.label == item["label"], PersonaTag.status.in_(["suggested", "confirmed"])
        )
        if cid:
            dup_q = dup_q.filter(PersonaTag.creator_id == cid)
        if dup_q.first():
            continue
        description = item.get("description", "")
        reason = item.get("reason", "")
        if reason:
            description = f"{description}（依据：{reason}）"
        db.add(
            PersonaTag(
                creator_id=cid,
                label=item["label"],
                description=description,
                category="style",
                source="ai",
                status="suggested",
                version=version,
            )
        )
    db.commit()

CORRECT_SYSTEM = (
    "你是转写校对助手。修正转写稿中的错别字、行业术语（如面试/求职/offer 相关词汇），"
    "保持口语原样，不增删内容。只输出修正后的文本。"
)


def correct_transcript(transcript_text: str, source_text: str = "", llm=None) -> str:
    """AI 校对：结合原始文案修正 ASR 行业词；无密钥时原样返回。"""
    text = normalize_text(transcript_text)
    if not text:
        return ""
    llm = llm or PersonaService().llm
    try:
        user = f"原始文案（仅供参考，可能与口播不一致）：\n{source_text or '无'}\n\n转写稿：\n{text}"
        corrected = llm.chat(
            [
                {"role": "system", "content": get_prompt("correct")},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        return normalize_text(corrected) or text
    except LLMError:
        return text


def import_video_task(db, payload: dict) -> None:
    """后台任务：单条视频 转写→校对→预打标签。"""
    video = db.get(Video, int(payload["video_id"]))
    if video is None:
        return
    settings = get_settings()

    if video.transcript is None or (
        not video.transcript.transcript_text and video.transcript.asr_status != "done"
    ):
        path = settings.videos_dir / video.filename
        transcriber = Transcriber(settings)
        try:
            text = transcriber.transcribe(path)
        except TranscriptionError as exc:
            # R-094：转写失败也落 asr_status=failed，并给可读原因
            model = settings.siliconflow_asr_model if settings.asr_mode == "siliconflow" else ""
            if video.transcript is None:
                video.transcript = Transcript(video_id=video.id, asr_status="failed", asr_provider=settings.asr_mode, asr_model=model)
                db.add(video.transcript)
            else:
                video.transcript.asr_status = "failed"
                video.transcript.asr_provider = settings.asr_mode
                video.transcript.asr_model = model
            db.commit()
            msg = str(exc) or "转写失败"
            if "识别结果为空" in msg:
                msg += "（未识别到有效语音：视频可能无声/只有背景音乐/音量过低或音轨异常，可检查该视频音轨后重试）"
            raise TranscriptionError(msg) from exc
        corrected = correct_transcript(text)
        if video.transcript is None:
            db.add(
                Transcript(
                    video_id=video.id,
                    transcript_text=text,
                    corrected_text=corrected,
                    asr_status="done",
                    asr_provider=settings.asr_mode,
                    asr_model=settings.siliconflow_asr_model if settings.asr_mode == "siliconflow" else "",
                )
            )
        else:
            video.transcript.transcript_text = text
            video.transcript.corrected_text = corrected
            video.transcript.asr_status = "done"
            video.transcript.asr_provider = settings.asr_mode
            video.transcript.asr_model = settings.siliconflow_asr_model if settings.asr_mode == "siliconflow" else ""
        db.commit()
        db.refresh(video)

    transcript = video.transcript
    if transcript:
        text = transcript.corrected_text or transcript.transcript_text
        if not video.tags_confirmed:
            try:
                suggestion = PersonaService().suggest_video_tags(text)
                if suggestion.get("main_topics"):
                    video.main_topics = json.dumps(suggestion["main_topics"], ensure_ascii=False)
                video.is_ad = suggestion["is_ad"]
                video.tags = json.dumps(suggestion["tags"], ensure_ascii=False)
                video.tags_confirmed = True  # R-083：AI 预打标签自动确认，不再要求逐条点「确认标签」
                db.commit()
            except Exception:
                # 预打标签失败不影响转写结果；保持 tags_confirmed=False 待后续重试/手填
                db.rollback()
        # 人设增量建议（广告视频不参与）
        try:
            suggest_persona_updates(db, video, text)
        except Exception:
            db.rollback()


def _norm_label(label: str) -> str:
    """去重键：去首尾/连续空白 + 小写（中文不受影响）。"""
    return " ".join((label or "").split()).lower()


def _analyze_one(text: str) -> dict | None:
    """单篇转写稿调 AI 提炼人设（R-126）。每线程独立 PersonaService；单篇失败不影响其它篇。"""
    try:
        return PersonaService().analyze_one(text)
    except Exception:  # noqa: BLE001
        return None


def persona_init_task(db, payload: dict, update=None) -> None:
    """后台任务：把主博主每篇非广告转写稿逐篇喂 AI，去重后生成人设建议（R-126）。

    不再整批拼接成一个大 prompt（R-125 澄清）；每篇一次调用（4 路并行），
    各篇产出去重 + 跳过当前主博主已确认/待确认的同标签，再以新版本 suggested 落库供前端确认。
    """
    cid = payload.get("creator_id") or current_creator_id(db)
    vq = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        vq = vq.filter(Video.creator_id == cid)
    videos = vq.all()
    texts = []
    for v in videos:
        if v.transcript and (v.transcript.corrected_text or v.transcript.transcript_text):
            texts.append(v.transcript.corrected_text or v.transcript.transcript_text)
    if not texts:
        return
    total = len(texts)
    if update:
        update(3, f"逐篇分析人设（0/{total}）…")
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_analyze_one, t) for t in texts]
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)
            done += 1
            if update:
                update(min(95, 5 + int(90 * done / total)), f"逐篇分析人设（{done}/{total}）…")

    # 已有 confirmed/suggested 标签去重键（被拒标签允许再次建议）
    existing: dict[tuple[str, str], bool] = {}
    eq = db.query(PersonaTag)
    if cid:
        eq = eq.filter(PersonaTag.creator_id == cid)
    for t in eq.all():
        if t.status in ("confirmed", "suggested"):
            existing[(t.category, _norm_label(t.label))] = True

    tags_out: list[dict] = []
    redlines_out: list[str] = []
    seen_tags: set[tuple[str, str]] = set()
    seen_redlines: set[str] = set()
    for res in results:
        for item in res.get("tags") or []:
            label = str(item.get("label", "")).strip() if isinstance(item, dict) else ""
            if not label:
                continue
            tag_key = ("style", _norm_label(label))
            if tag_key in seen_tags or tag_key in existing:
                continue
            seen_tags.add(tag_key)
            tags_out.append(
                {"label": label, "description": str(item.get("description", "")).strip()}
            )
        for redline in res.get("redlines") or []:
            text = str(redline).strip()
            if not text:
                continue
            red_key = _norm_label(text)
            if red_key in seen_redlines or ("redline", red_key) in existing:
                continue
            seen_redlines.add(red_key)
            redlines_out.append(text)

    if not tags_out and not redlines_out:
        return

    ver_q = db.query(func.max(PersonaTag.version))
    if cid:
        ver_q = ver_q.filter(PersonaTag.creator_id == cid)
    current_version = ver_q.scalar() or 0
    version = int(current_version) + 1
    for item in tags_out:
        db.add(
            PersonaTag(
                creator_id=cid,
                label=item["label"],
                description=item["description"],
                category="style",
                source="ai",
                status="suggested",
                version=version,
            )
        )
    for redline in redlines_out:
        db.add(
            PersonaTag(
                creator_id=cid,
                label=redline,
                description="",
                category="redline",
                source="ai",
                status="suggested",
                version=version,
            )
        )
    db.commit()
    if update:
        update(100, f"完成：新增建议 {len(tags_out) + len(redlines_out)} 条")
