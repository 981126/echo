"""AI 对话服务：只读工具调用 + 问答；写操作不在此执行（权限边界）。

系统提示词强制：写操作（生成/修改/删除）一律引导到网页工作台，不直接执行。
"""
import json

from sqlalchemy.orm import Session

from ..models.persona import PersonaTag
from ..models.video import Video
from .llm import DeepSeekClient, LLMError
from .requirements_service import list_requirements

SYSTEM_PROMPT = (
    "你是 echo 系统的 AI 助手，帮助作者查询和分析自媒体创作数据（抖音/B站/小红书，"
    "赛道：求职/面试/赚钱/知识）。你可以调用只读工具查询素材库、人设、需求、指标、选题。"
    "严格禁止执行任何写操作（生成、修改、删除）：如果作者要求写操作，"
    "礼貌说明请到网页工作台操作或等待作者确认。用简体中文回答，简洁、口语化、直接。"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_videos",
            "description": "按条件搜索素材库视频（可组合平台/状态/主赛道/是否广告）",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "douyin/bilibili/xiaohongshu"},
                    "status": {"type": "string", "description": "planned/published"},
                    "main_topic": {"type": "string", "description": "求职/面试/赚钱/知识/其他"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_video_detail",
            "description": "获取单个视频详情（含转写稿）",
            "parameters": {
                "type": "object",
                "properties": {"video_id": {"type": "integer"}},
                "required": ["video_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_persona",
            "description": "获取当前已确认的人设档案（标签+描述+红线）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_requirements",
            "description": "列出需求归档",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metrics_summary",
            "description": "获取指标汇总（M4 前不可用）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_topics",
            "description": "获取今日选题（M3 前不可用）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _search_videos(db: Session, args: dict) -> list[dict]:
    q = db.query(Video)
    if args.get("platform"):
        q = q.filter(Video.platform == args["platform"])
    if args.get("status"):
        q = q.filter(Video.status == args["status"])
    if args.get("main_topic"):
        q = q.filter(Video.main_topic == args["main_topic"])
    limit = min(int(args.get("limit") or 10), 50)
    items = q.order_by(Video.created_at.desc()).limit(limit).all()
    return [
        {
            "id": v.id,
            "filename": v.filename,
            "platform": v.platform,
            "status": v.status,
            "main_topic": v.main_topic,
            "is_ad": v.is_ad,
            "tags_confirmed": v.tags_confirmed,
            "created_at": str(v.created_at),
        }
        for v in items
    ]


def _get_video_detail(db: Session, args: dict) -> dict:
    video = db.get(Video, int(args.get("video_id") or 0))
    if video is None:
        return {"error": "视频不存在"}
    transcript = ""
    if video.transcript:
        transcript = video.transcript.corrected_text or video.transcript.transcript_text
    return {
        "id": video.id,
        "filename": video.filename,
        "platform": video.platform,
        "status": video.status,
        "main_topic": video.main_topic,
        "is_ad": video.is_ad,
        "tags_confirmed": video.tags_confirmed,
        "transcript": transcript[:2000],
    }


def _get_persona(db: Session) -> dict:
    tags = (
        db.query(PersonaTag)
        .filter(PersonaTag.status == "confirmed")
        .order_by(PersonaTag.category, PersonaTag.id)
        .all()
    )
    return {
        "tags": [{"label": t.label, "description": t.description, "category": t.category} for t in tags]
    }


def _dispatch(db: Session, name: str, args: dict) -> dict:
    if name == "search_videos":
        return {"videos": _search_videos(db, args)}
    if name == "get_video_detail":
        return _get_video_detail(db, args)
    if name == "get_persona":
        return _get_persona(db)
    if name == "list_requirements":
        return {"requirements": list_requirements()}
    if name == "get_metrics_summary":
        return {"available": False, "message": "指标看板将在 M4 上线，敬请期待"}
    if name == "get_today_topics":
        return {"available": False, "message": "每日选题将在 M3 上线，目前可手动生成"}
    return {"error": f"未知工具: {name}"}


class ChatService:
    def __init__(self, llm=None):
        self.llm = llm or DeepSeekClient()

    def reply(self, db: Session, user_message: str, history: list[dict]) -> str:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history[-20:])
        messages.append({"role": "user", "content": user_message})

        for _ in range(3):
            try:
                message = self.llm.chat_completion(messages, temperature=0.5, tools=TOOLS)
            except LLMError:
                return "（当前未配置 DeepSeek 密钥，暂无法回答。请先在 .env 配置 ECHO_DEEPSEEK_API_KEY。）"
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                return (message.get("content") or "").strip()
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = _dispatch(db, name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        raise LLMError("对话在多次工具调用后未收敛")
