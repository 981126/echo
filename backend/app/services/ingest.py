"""内容导入流水线：转写 → AI 校对 → 预打标签；人设初始化。"""
import json

from sqlalchemy import func

from ..config import get_settings
from ..core.transcript import normalize_text
from ..models.persona import PersonaTag
from ..models.video import Transcript, Video
from .llm import LLMError
from .persona import PersonaService
from .transcription import Transcriber, TranscriptionError


def suggest_persona_updates(db, video, transcript_text: str) -> None:
    """新视频（非广告）进入后，自动建议人设扩充（待作者确认）。"""
    if video.is_ad or not transcript_text:
        return
    current = db.query(PersonaTag).filter(PersonaTag.status == "confirmed").all()
    result = PersonaService().suggest_updates(transcript_text, current)
    if not result["suggestions"]:
        return
    latest = db.query(PersonaTag).order_by(PersonaTag.version.desc()).first()
    version = latest.version if latest else 1
    for item in result["suggestions"]:
        dup = (
            db.query(PersonaTag)
            .filter(PersonaTag.label == item["label"], PersonaTag.status.in_(["suggested", "confirmed"]))
            .first()
        )
        if dup:
            continue
        description = item.get("description", "")
        reason = item.get("reason", "")
        if reason:
            description = f"{description}（依据：{reason}）"
        db.add(
            PersonaTag(
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
                {"role": "system", "content": CORRECT_SYSTEM},
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

    if video.transcript is None:
        path = settings.videos_dir / video.filename
        transcriber = Transcriber(settings)
        text = transcriber.transcribe(path)
        corrected = correct_transcript(text)
        db.add(
            Transcript(
                video_id=video.id,
                transcript_text=text,
                corrected_text=corrected,
                asr_status="done",
            )
        )
        db.commit()
        db.refresh(video)

    transcript = video.transcript
    if transcript:
        text = transcript.corrected_text or transcript.transcript_text
        if not video.tags_confirmed:
            try:
                suggestion = PersonaService().suggest_video_tags(text)
                video.main_topic = suggestion["main_topic"]
                video.is_ad = suggestion["is_ad"]
                video.tags = json.dumps(suggestion["tags"], ensure_ascii=False)
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
    """后台任务：用全部历史转写稿初始化/刷新人设档案（新版本）。"""
    videos = db.query(Video).filter(Video.is_ad.is_(False)).all()
    transcripts = []
    for v in videos:
        if v.transcript and (v.transcript.corrected_text or v.transcript.transcript_text):
            transcripts.append(v.transcript.corrected_text or v.transcript.transcript_text)
    if not transcripts:
        return
    result = PersonaService().analyze_initial(transcripts)
    current_version = db.query(func.max(PersonaTag.version)).scalar() or 0
    version = int(current_version) + 1
    for item in result["tags"]:
        db.add(
            PersonaTag(
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
                label=redline,
                description="",
                category="redline",
                source="ai",
                status="suggested",
                version=version,
            )
        )
    db.commit()
