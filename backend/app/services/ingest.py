"""内容导入流水线：转写 → AI 校对 → 预打标签；人设初始化。"""

from __future__ import annotations

import json

from sqlalchemy import func

from ..config import get_settings
from ..core.transcript import normalize_text
from ..models.persona import PersonaTag
from ..models.video import Transcript, Video
from .llm import LLMError
from .persona import PersonaService
from .prompt_service import get_prompt
from .transcription import Transcriber
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
        text = transcriber.transcribe(path)
        corrected = correct_transcript(text)
        if video.transcript is None:
            db.add(
                Transcript(
                    video_id=video.id,
                    transcript_text=text,
                    corrected_text=corrected,
                    asr_status="done",
                )
            )
        else:
            video.transcript.transcript_text = text
            video.transcript.corrected_text = corrected
            video.transcript.asr_status = "done"
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


def persona_init_task(db, payload: dict) -> None:
    """后台任务：用当前主博主历史转写稿初始化/刷新人设档案（新版本）。"""
    cid = payload.get("creator_id") or current_creator_id(db)
    vq = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        vq = vq.filter(Video.creator_id == cid)
    videos = vq.all()
    transcripts = []
    for v in videos:
        if v.transcript and (v.transcript.corrected_text or v.transcript.transcript_text):
            transcripts.append(v.transcript.corrected_text or v.transcript.transcript_text)
    if not transcripts:
        return
    result = PersonaService().analyze_initial(transcripts)
    ver_q = db.query(func.max(PersonaTag.version))
    if cid:
        ver_q = ver_q.filter(PersonaTag.creator_id == cid)
    current_version = ver_q.scalar() or 0
    version = int(current_version) + 1
    for item in result["tags"]:
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
    for redline in result["redlines"]:
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
