"""人设服务：初始化分析、视频预打标签、增量建议（DeepSeek）。

所有 LLM 调用在未配置密钥时安全降级（返回默认值），保证开发/测试离线可跑。
"""

from __future__ import annotations

import re

from ..core.topics import normalize_topics
from .prompt_service import get_prompt
from ..models.persona import PersonaTag
from .llm import DeepSeekClient, LLMError

PERSONA_INIT_SYSTEM = (
    "你是自媒体人设分析专家。根据作者的视频转写稿提炼人设档案。"
    "只输出 JSON，格式："
    '{"tags":[{"label":"简短标签(2-6字)","description":"一句话描述"}],'
    '"redlines":["作者明确不做的表达或内容"]}'
)

PERSONA_UPDATES_SYSTEM = (
    "你是人设迭代专家。基于当前人设档案和一条新视频转写稿，"
    "判断是否有值得扩充的新标签。若没有，返回空列表。"
    '只输出 JSON：{"suggestions":[{"label":"标签","description":"描述","reason":"为什么"}]}'
)


VIDEO_TAGS_SYSTEM = (
    "你是视频内容标注助手。根据视频转写稿输出 JSON："
    '{"main_topics":["求职|面试|赚钱|知识|其他"],"is_ad":false,'
    '"tags":["简短标签1","简短标签2"]}'
    "main_topics 为赛道数组（可多个，至少一个）；is_ad 表示是否为商务广告"
    "（口播中明显推广产品/品牌）。只输出 JSON。"
)



_SENT_SPLIT = re.compile(r"[。！？!?\n]+")


def _split_phrases(text: str, limit: int) -> list[str]:
    out: list[str] = []
    seen = set()
    for part in _SENT_SPLIT.split(text or ""):
        part = part.strip()
        if 6 <= len(part) <= 40 and part not in seen and not part.startswith(("我", "这", "那", "你", "今天", "然后", "就是", "其实")):
            seen.add(part)
            out.append(part)
        if len(out) >= limit:
            break
    return out


def suggest_phrase_candidates(db, limit: int = 12) -> list[dict]:
    """从当前主博主高表现素材里挑短句候选（R-030③ 金句库）。"""
    from ..models.metrics import MetricsSnapshot
    from ..models.video import Video
    from .creator_service import current_creator_id

    cid = current_creator_id(db)
    q = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        q = q.filter(Video.creator_id == cid)
    rows = []
    for v in q.all():
        if not v.transcript:
            continue
        text = v.transcript.corrected_text or v.transcript.transcript_text
        if not text:
            continue
        eng = 0
        snap = (
            db.query(MetricsSnapshot)
            .filter(MetricsSnapshot.video_id == v.id)
            .order_by(MetricsSnapshot.snapshot_date.desc())
            .first()
        )
        if snap:
            eng = snap.plays + snap.likes * 5 + snap.favorites * 3 + snap.comments * 10
        rows.append((eng, v.title or "", text))
    rows.sort(key=lambda x: x[0], reverse=True)
    candidates: list[dict] = []
    seen = set()
    for eng, title, text in rows[:40]:
        for ph in _split_phrases(text, limit=5):
            if ph in seen:
                continue
            seen.add(ph)
            candidates.append({"text": ph, "source_title": title, "engagement": eng})
        if len(candidates) >= limit:
            break
    return candidates


class PersonaService:
    def __init__(self, llm=None):
        self.llm = llm or DeepSeekClient()

    def analyze_initial(self, transcripts: list[str]) -> dict:
        """初始化人设：输入历史转写稿，输出 tags + redlines。"""
        content = "以下是作者的视频转写稿（用 --- 分隔）：\n\n" + "\n---\n".join(
            t for t in transcripts if t
        )
        messages = [
            {"role": "system", "content": get_prompt("persona_init")},
            {"role": "user", "content": content},
        ]
        try:
            data = self.llm.chat_json(messages)
        except LLMError:
            return {"tags": [], "redlines": []}
        result: dict = {"tags": [], "redlines": []}
        for item in data.get("tags") or []:
            label = str(item.get("label", "")).strip() if isinstance(item, dict) else ""
            if label:
                desc = str(item.get("description", "")).strip() if isinstance(item, dict) else ""
                result["tags"].append({"label": label, "description": desc})
        for redline in data.get("redlines") or []:
            text = str(redline).strip()
            if text:
                result["redlines"].append(text)
        return result

    def suggest_video_tags(self, transcript: str) -> dict:
        """AI 预打标签：赛道（可多选）/ 是否广告 / 自定义标签。"""
        messages = [
            {"role": "system", "content": get_prompt("video_tags")},
            {"role": "user", "content": transcript},
        ]
        try:
            data = self.llm.chat_json(messages)
        except LLMError:
            data = {}
        values = data.get("main_topics") or data.get("main_topic") or []
        return {
            "main_topics": normalize_topics(values),
            "is_ad": bool(data.get("is_ad", False)),
            "tags": [str(t).strip() for t in data.get("tags") or [] if str(t).strip()],
        }

    def suggest_updates(self, new_transcript: str, current_tags: list[PersonaTag]) -> dict:
        """新视频进入后，建议人设扩充（标签+描述+理由），待作者确认。"""
        confirmed = [t for t in current_tags if t.status == "confirmed"]
        current_summary = "\n".join(
            f"- {t.label}: {t.description}" for t in confirmed
        ) or "（暂无已确认人设）"
        system = PERSONA_UPDATES_SYSTEM
        user = f"当前人设：\n{current_summary}\n\n新视频转写稿：\n{new_transcript}"
        try:
            data = self.llm.chat_json(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
        except LLMError:
            return {"suggestions": []}
        suggestions = []
        for item in data.get("suggestions") or []:
            label = str(item.get("label", "")).strip() if isinstance(item, dict) else ""
            if label:
                suggestions.append(
                    {
                        "label": label,
                        "description": str(item.get("description", "")).strip(),
                        "reason": str(item.get("reason", "")).strip(),
                    }
                )
        return {"suggestions": suggestions}
