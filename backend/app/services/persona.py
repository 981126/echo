"""人设服务：初始化分析、视频预打标签、增量建议（DeepSeek）。

所有 LLM 调用在未配置密钥时安全降级（返回默认值），保证开发/测试离线可跑。
"""
from ..core.topics import normalize_main_topic
from ..models.persona import PersonaTag
from .llm import DeepSeekClient, LLMError

PERSONA_INIT_SYSTEM = (
    "你是自媒体人设分析专家。根据作者的视频转写稿提炼人设档案。"
    "只输出 JSON，格式："
    '{"tags":[{"label":"简短标签(2-6字)","description":"一句话描述"}],'
    '"redlines":["作者明确不做的表达或内容"]}'
)

VIDEO_TAGS_SYSTEM = (
    "你是视频内容标注助手。根据视频转写稿输出 JSON："
    '{"main_topic":"求职|面试|赚钱|知识|其他","is_ad":false,'
    '"tags":["简短标签1","简短标签2"]}'
    "is_ad 表示是否为商务广告（口播中明显推广产品/品牌）。只输出 JSON。"
)


class PersonaService:
    def __init__(self, llm=None):
        self.llm = llm or DeepSeekClient()

    def analyze_initial(self, transcripts: list[str]) -> dict:
        """初始化人设：输入历史转写稿，输出 tags + redlines。"""
        content = "以下是作者的视频转写稿（用 --- 分隔）：\n\n" + "\n---\n".join(
            t for t in transcripts if t
        )
        messages = [
            {"role": "system", "content": PERSONA_INIT_SYSTEM},
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
        """AI 预打标签：主赛道 / 是否广告 / 自定义标签。"""
        messages = [
            {"role": "system", "content": VIDEO_TAGS_SYSTEM},
            {"role": "user", "content": transcript},
        ]
        try:
            data = self.llm.chat_json(messages)
        except LLMError:
            data = {}
        return {
            "main_topic": normalize_main_topic(str(data.get("main_topic", ""))),
            "is_ad": bool(data.get("is_ad", False)),
            "tags": [str(t).strip() for t in data.get("tags") or [] if str(t).strip()],
        }

    def suggest_updates(self, new_transcript: str, current_tags: list[PersonaTag]) -> dict:
        """新视频进入后，建议人设扩充（标签+描述+理由），待作者确认。"""
        confirmed = [t for t in current_tags if t.status == "confirmed"]
        current_summary = "\n".join(
            f"- {t.label}: {t.description}" for t in confirmed
        ) or "（暂无已确认人设）"
        system = (
            "你是人设迭代专家。基于当前人设档案和一条新视频转写稿，"
            "判断是否有值得扩充的新标签。若没有，返回空列表。"
            '只输出 JSON：{"suggestions":[{"label":"标签","description":"描述","reason":"为什么"}]}'
        )
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
