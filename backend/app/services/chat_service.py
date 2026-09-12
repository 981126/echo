"""AI 对话服务：只读工具调用 + 问答；写操作不在此执行（权限边界）。

系统提示词强制：写操作（生成/修改/删除）一律引导到网页工作台，不直接执行。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models.persona import PersonaTag
from ..models.video import Video
from . import budget_settings, llm_router
from .llm import LLMError
from .prompt_service import get_prompt
from .requirements_service import list_requirements

SYSTEM_PROMPT = (
    "你是 echo 系统的 AI 助手，帮助作者查询和分析自媒体创作数据（抖音/B站/小红书，"
    "赛道：求职/面试/赚钱/知识）。你可以调用工具查询素材库、人设、需求、指标、选题、复盘，"
    "也可以在作者明确同意后生成脚本草稿（写操作）。"
    "写操作规则：涉及生成/修改/删除时必须先向作者说明并征得明确同意，才允许调用工具执行；"
    "作者未明确同意时，只提供方案不执行。用简体中文回答，简洁、口语化、直接。"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_videos",
            "description": "按条件搜索素材库视频；平台/赛道为多选，命中任一即可（可组合平台/状态/赛道）",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "douyin/bilibili/xiaohongshu（匹配视频任一平台）"},
                    "status": {"type": "string", "description": "planned/published"},
                    "main_topic": {"type": "string", "description": "求职/面试/赚钱/知识/其他（匹配视频任一赛道）"},
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
            "description": "获取指标汇总（按视频/赛道/平台）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_topics",
            "description": "获取最新一批匹配选题",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_radar",
            "description": "获取赛道雷达（各赛道互动率）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_drafts",
            "description": "搜索脚本草稿",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_draft",
            "description": "根据选题生成脚本草稿（写操作，必须先获得作者明确同意）",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    },
]


def _vlist(raw) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _vbrief(v: Video) -> dict:
    platforms = _vlist(v.platforms)
    main_topics = _vlist(v.main_topics)
    return {
        "id": v.id,
        "filename": v.filename,
        "platforms": platforms,
        "platform": "、".join(platforms),
        "status": v.status,
        "main_topics": main_topics,
        "main_topic": "、".join(main_topics),
        "is_ad": v.is_ad,
        "tags_confirmed": v.tags_confirmed,
        "created_at": str(v.created_at),
    }


def _search_videos(db: Session, args: dict) -> list[dict]:
    q = db.query(Video)
    if args.get("platform"):
        q = q.filter(Video.platforms.like(f'%"{args["platform"]}"%'))
    if args.get("status"):
        q = q.filter(Video.status == args["status"])
    if args.get("main_topic"):
        q = q.filter(Video.main_topics.like(f'%"{args["main_topic"]}"%'))
    limit = min(int(args.get("limit") or 10), 50)
    items = q.order_by(Video.created_at.desc()).limit(limit).all()
    return [_vbrief(v) for v in items]


def _get_video_detail(db: Session, args: dict) -> dict:
    video = db.get(Video, int(args.get("video_id") or 0))
    if video is None:
        return {"error": "视频不存在"}
    transcript = ""
    if video.transcript:
        transcript = video.transcript.corrected_text or video.transcript.transcript_text
    brief = _vbrief(video)
    brief["transcript"] = transcript[:2000]
    return brief


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


def _search_drafts(db: Session, args: dict) -> list[dict]:
    from ..models.draft import Draft

    limit = min(int(args.get("limit") or 10), 50)
    rows = db.query(Draft).order_by(Draft.updated_at.desc()).limit(limit).all()
    return [
        {"id": d.id, "title": d.title, "cover_text": d.cover_text, "source": d.source, "status": d.status}
        for d in rows
    ]


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
        from .metrics import summary

        data = summary(db)
        return {
            "by_topic": data["by_topic"],
            "by_platform": data["by_platform"],
            "top_videos": [
                {
                    "filename": v["filename"],
                    "plays": v["plays"],
                    "likes": v["likes"],
                    "favorites": v["favorites"],
                    "comments": v["comments"],
                    "main_topics": v.get("main_topics") or [],
                    "platforms": v.get("platforms") or [],
                }
                for v in data["per_video"][:10]
            ],
        }
    if name == "get_today_topics":
        from ..models.hot_topic import TopicCandidate
        from ..core.pipeline import today_key

        key = today_key()
        rows = (
            db.query(TopicCandidate)
            .filter(TopicCandidate.run_date == key)
            .order_by(TopicCandidate.score.desc())
            .all()
        )
        if not rows:
            # 回退到最近一批
            latest = (
                db.query(TopicCandidate)
                .order_by(TopicCandidate.run_date.desc())
                .first()
            )
            if latest:
                rows = (
                    db.query(TopicCandidate)
                    .filter(TopicCandidate.run_date == latest.run_date)
                    .order_by(TopicCandidate.score.desc())
                    .all()
                )
        return {
            "topics": [
                {"title": r.title, "platform": r.platform, "score": r.score, "draft_id": r.draft_id}
                for r in rows
            ]
        }
    if name == "get_radar":
        from .metrics import radar

        return {"radar": radar(db)}
    if name == "search_drafts":
        return {"drafts": _search_drafts(db, args)}
    if name == "generate_draft":
        from .generation import generate_draft

        draft = generate_draft(db, str(args.get("topic", "")))
        return {
            "draft_id": draft.id,
            "title": draft.title,
            "cover_text": draft.cover_text,
            "script": draft.script,
        }
    return {"error": f"未知工具: {name}"}


class ChatService:
    """AI 对话（R-139：默认模型1，失败自动降级模型2）。`llm=` 仍可注入（测试/显式指定）。"""

    def __init__(self, llm=None, db: Session | None = None):
        self.llm = llm or llm_router.primary_llm(db, "chat")

    def reply(self, db: Session, user_message: str, history: list[dict]) -> str:
        messages: list[dict] = [{"role": "system", "content": get_prompt("chat")}]
        messages.extend(history[-20:])
        messages.append({"role": "user", "content": user_message})

        for _ in range(3):
            try:
                message = self.llm.chat_completion(
                    messages,
                    temperature=0.5,
                    max_tokens=budget_settings.budget_for(db, "chat"),
                    tools=TOOLS,
                )
            except LLMError:
                return "（AI 服务暂时不可用：模型1 与模型2 都没能给出结果，请到「AI 设置」检查 API Key。）"
            except Exception as exc:  # noqa: BLE001 外部服务失败统一降级，不让对话页报裸错
                return f"（AI 服务暂时不可用：{exc}）"
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
