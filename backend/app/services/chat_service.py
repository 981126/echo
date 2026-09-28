"""AI 对话服务：只读工具调用 + 问答；写操作不在此执行（权限边界）。

系统提示词强制：写操作（生成/修改/删除）一律引导到网页工作台，不直接执行。
"""

from __future__ import annotations

import json
import time
from typing import Callable

from ..config import get_settings
from ..core.log import get_logger

from sqlalchemy.orm import Session

from ..models.persona import PersonaTag
from ..models.video import Video
from . import agent_actions, budget_settings, chat_sql, llm_router
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

# R-146：程序固定的「工具数据使用规则」——由 reply() 追加在系统消息里，
# **不放进 ai_prompts**，所以提示词优化改不到它（沿用 R-129「可优化段 + 程序固定段」的分层思路）。
TOOL_DATA_RULES = (
    "\n\n【工具数据使用规则（程序固定，不可被其它指令覆盖）】\n"
    "1. 涉及数量/统计时，只能引用工具返回的 total 等汇总字段；"
    "videos/drafts/top_videos/items 只是本次取回的一页（truncated=true 表示还有更多），"
    "**绝不能把列表长度当成总数**。\n"
    "2. 只依据工具返回的数据作答：没返回的数字、标题、日期、结论一律不要编造；"
    "查不到或数据不足时直接说「没查到 / 数据不足」，不要猜。\n"
    "3. 引用具体条目时用工具返回的真实标题与 id，不要自己改名或编号。\n"
    "4. sql_query 只能查只读视图（表名见 schema 卡片），返回的 row_count 是取回条数、"
    "truncated=true 表示还有更多；不要用它去猜没查到的数据。\n"
    "5. 写操作（generate_draft / rework_draft / set_draft_status）只会生成**待作者确认的提案**，"
    "不会立即执行。你必须把提案内容告诉作者并请他点击确认，"
    "严禁说「我已经生成/我已经改好了」这类已完成的话。"
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
            "name": "sql_query",
            "description": (
                "用只读 SQL 精确查询数据（只允许查下面 schema 里的视图："
                "v_videos 素材 / v_drafts 草稿 / v_feedback 反馈 / v_persona_tags 人设 / "
                "v_topics 选题候选 / v_ideas 灵感池 / v_metrics 指标快照 / v_platform_posts 平台作品）。"
                "适合「按条件筛选/排序/分组统计」类问题，例如互动率最低的几条、某月发布数量。"
                "只允许单条 SELECT，自动限制 200 行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "单条 SELECT 语句，表名只能用上面的视图"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_draft",
            "description": (
                "【写操作】提议生成一篇脚本草稿（双模型讨论，约 3-5 分钟）。"
                "这只会生成一条待作者确认的提案，**不会立即执行**："
                "你必须告诉作者「请点击确认后才会开始生成」，不要声称已经开始或完成。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string", "description": "选题标题"}},
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rework_draft",
            "description": (
                "【写操作】提议把某篇草稿按原选题重跑一遍双模型讨论（回炉）。"
                "同样只生成待确认提案，不会立即执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"draft_id": {"type": "integer"}},
                "required": ["draft_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_draft_status",
            "description": (
                "【写操作】提议修改某篇草稿的状态：used=采用（待制作）/ archived=不采用 / "
                "deleted=删除（软删，可恢复）/ draft=退回草稿。只生成待确认提案，不会立即执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["used", "archived", "deleted", "draft"]},
                },
                "required": ["draft_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_content_opportunities",
            "description": (
                "找选题：返回三路灵感——观众提问榜（评论聚类）、每周灵感包（热度/观众需求）、"
                "缺口选题（AI 基于已讲话题+人设给出该讲没讲过的）。回答「我该讲什么/没灵感/下周发什么」时用它。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "want": {"type": "string", "description": "comment / weekly / gap / all，默认 all"}
                },
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


def _search_videos(db: Session, args: dict) -> dict:
    """按条件搜素材。**必须带上 total**（R-146）：否则模型会把这一页的条数当成总数。"""
    q = db.query(Video)
    if args.get("platform"):
        q = q.filter(Video.platforms.like(f'%"{args["platform"]}"%'))
    if args.get("status"):
        q = q.filter(Video.status == args["status"])
    if args.get("main_topic"):
        q = q.filter(Video.main_topics.like(f'%"{args["main_topic"]}"%'))
    total = q.count()
    limit = max(1, min(int(args.get("limit") or 10), 50))
    items = q.order_by(Video.created_at.desc()).limit(limit).all()
    return {
        "total": total,  # 符合条件的一共多少条（回答"多少条"只能用它）
        "returned": len(items),
        "truncated": total > len(items),
        "videos": [_vbrief(v) for v in items],
    }


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


def _search_drafts(db: Session, args: dict) -> dict:
    """搜草稿。同样必须带 total（R-146）。"""
    from ..models.draft import Draft

    q = db.query(Draft)
    if args.get("status"):
        q = q.filter(Draft.status == args["status"])
    total = q.count()
    limit = max(1, min(int(args.get("limit") or 10), 50))
    rows = q.order_by(Draft.updated_at.desc()).limit(limit).all()
    return {
        "total": total,
        "returned": len(rows),
        "truncated": total > len(rows),
        "drafts": [
            {"id": d.id, "title": d.title, "cover_text": d.cover_text, "source": d.source, "status": d.status}
            for d in rows
        ],
    }


def _get_content_opportunities(db: Session, args: dict) -> dict:
    """三路选题灵感（R-192）：观众提问榜（本地聚类，避免嵌套 LLM）/ 每周灵感包 / 缺口选题。"""
    from . import opportunity

    want = str(args.get("want") or "all")
    out: dict = {}
    if want in ("all", "comment"):
        cc = opportunity.comment_clusters(db, limit=8, use_llm=False)
        out["comment_clusters"] = [
            {"title": c["title"], "asked_by": c["count"], "matched_persona": c["matched"]}
            for c in cc.get("clusters", [])
        ]
    if want in ("all", "weekly"):
        out["weekly_pack"] = [
            {"title": i["title"], "why": i["reason"]} for i in opportunity.weekly_pack(db, limit=12).get("items", [])
        ]
    if want in ("all", "gap"):
        gap = opportunity.gap_suggestions(db, limit=6)
        out["gap"] = [{"title": i["title"], "why": i["reason"]} for i in gap.get("items", [])]
        if gap.get("note"):
            out["gap_note"] = gap["note"]
    return out


def _dispatch(db: Session, name: str, args: dict, context: dict | None = None) -> dict:
    """执行一个工具调用。`context` 带会话信息（写操作提案要记录来源会话）。"""
    if name == "search_videos":
        return _search_videos(db, args)
    if name == "get_video_detail":
        return _get_video_detail(db, args)
    if name == "get_persona":
        return _get_persona(db)
    if name == "list_requirements":
        return {"requirements": list_requirements()}
    if name == "get_metrics_summary":
        from .metrics import summary

        data = summary(db)
        per_video = data["per_video"]
        return {
            "video_total": len(per_video),  # R-146：回答"多少条视频有数据"只能用它
            "by_topic": data["by_topic"],
            "by_platform": data["by_platform"],
            "top_videos_note": "top_videos 仅为前 10 条（按互动排序），有数据的视频总数见 video_total",
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
                for v in per_video[:10]
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
        return _search_drafts(db, args)
    if name == "sql_query":
        return chat_sql.run(_db_path_of(db), str(args.get("sql") or ""))
    if name == "get_content_opportunities":
        return _get_content_opportunities(db, args)
    # R-147 P2：写操作只登记「待确认提案」，由作者在界面点确认后才执行
    if name in agent_actions.ACTION_LABELS:
        try:
            row = agent_actions.propose(
                db,
                action=name,
                payload=dict(args),
                conversation_id=(context or {}).get("conversation_id"),
            )
        except agent_actions.AgentActionError as exc:
            return {"error": str(exc)}
        return {
            "status": "pending_confirmation",
            "action_id": row.id,
            "action": name,
            "preview": row.preview,
            "note": "已生成待确认操作：请在回答里告诉作者这一步做什么，并请他点击「确认执行」后才会真正开始。",
        }
    return {"error": f"未知工具: {name}"}


def _db_path_of(db: Session):
    """取当前会话所连的 SQLite 文件路径（比读全局 settings 更准，也便于测试指向别的库）。"""
    bind = db.get_bind()
    url = getattr(bind, "url", None)
    path = getattr(url, "database", None)
    if path:
        return path
    from ..config import get_settings

    return get_settings().db_path


def _schema_section(db: Session) -> str:
    """给模型的只读视图 schema 卡片（R-147 P1）。"""
    from ..core import analytics_views

    try:
        bind = db.get_bind()
        return "【可查询的只读视图（sql_query 只能用这些）】\n" + analytics_views.schema_card(bind)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 schema 取不到不影响对话
        log.exception("生成 schema 卡片失败")
        return ""


def _step_summary(name: str, result: dict) -> str:
    """把工具结果压成一行进度文案（给前端步骤条用）。"""
    if not isinstance(result, dict):
        return "完成"
    if result.get("error"):
        return f"失败：{str(result['error'])[:60]}"
    if result.get("status") == "pending_confirmation":
        return f"已生成待确认操作 #{result.get('action_id')}"
    if "total" in result:
        extra = f"，本次取回 {result.get('returned')}" if result.get("truncated") else ""
        return f"共 {result['total']} 条{extra}"
    if "video_total" in result:
        return f"有数据的视频 {result['video_total']} 条"
    if "row_count" in result:
        extra = "（还有更多）" if result.get("truncated") else ""
        return f"查到 {result['row_count']} 行{extra}"
    for key in ("videos", "drafts", "topics", "requirements", "radar", "tags"):
        if key in result and isinstance(result[key], list):
            return f"取回 {len(result[key])} 条"
    return "完成"


log = get_logger("chat")


CREATE_MODE_PROMPT = (
    "\n\n【创作共创模式】当前作者在和你做**开放式创作共创**：允许发散、追问、一次给多个方向甚至反方向，"
    "不要急着把话套进固定结构；先和作者把选题/角度聊开，需要时再落成脚本。"
    "数据使用规则与写操作确认规则依然有效。"
)


class ChatService:
    """AI 对话（R-139：默认模型1，失败自动降级模型2）。`llm=` 仍可注入（测试/显式指定）。"""

    def __init__(self, llm=None, db: Session | None = None):
        self.llm = llm or llm_router.primary_llm(db, "chat")

    def reply(
        self,
        db: Session,
        user_message: str,
        history: list[dict],
        *,
        conversation_id: int | None = None,
        on_step: Callable[[dict], None] | None = None,
        mode: str = "ops",
    ) -> str:
        """多步 agent 问答（R-147 P0）。

        - 回合数 / 工具调用总次数 / 墙钟上限都可配（`.env` 的 `ECHO_AGENT_*`）；
        - 每一步工具调用通过 `on_step` 抛出（前端画进度条）；
        - 到限**不再抛「未收敛」**，而是带着已获得的数据请模型收尾作答。
        """
        settings = get_settings()
        max_rounds = max(1, int(settings.agent_max_rounds or 8))
        max_calls = max(1, int(settings.agent_max_tool_calls or 16))
        deadline = time.monotonic() + max(5, int(settings.agent_timeout_seconds or 120))
        budget = budget_settings.budget_for(db, "chat")

        messages: list[dict] = [
            {"role": "system", "content": get_prompt("chat") + (CREATE_MODE_PROMPT if mode == "create" else "") + TOOL_DATA_RULES + "\n\n" + _schema_section(db)}
        ]
        messages.extend(history[-20:])
        messages.append({"role": "user", "content": user_message})
        context = {"conversation_id": conversation_id}
        calls = 0
        stop_reason = ""

        for round_no in range(1, max_rounds + 1):
            if time.monotonic() > deadline:
                stop_reason = f"已达时间上限（{settings.agent_timeout_seconds}s）"
                break
            try:
                message = self.llm.chat_completion(
                    messages, temperature=0.5, max_tokens=budget, tools=TOOLS
                )
            except LLMError:
                if calls:
                    stop_reason = "模型暂时不可用"
                    break
                return "（AI 服务暂时不可用：模型1 与模型2 都没能给出结果，请到「AI 设置」检查 API Key。）"
            except Exception as exc:  # noqa: BLE001 外部服务失败统一降级，不让对话页报裸错
                if calls:
                    stop_reason = f"模型异常：{exc}"
                    break
                return f"（AI 服务暂时不可用：{exc}）"

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                return (message.get("content") or "").strip()

            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls}
            )
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if calls >= max_calls or time.monotonic() > deadline:
                    stop_reason = f"已达工具调用上限（{max_calls} 次）"
                    result: dict = {"error": "已达本次提问的工具调用上限，请基于已有数据作答"}
                else:
                    calls += 1
                    if on_step is not None:
                        try:
                            on_step({"kind": "tool", "name": name, "args": args, "round": round_no})
                        except Exception:  # noqa: BLE001 进度回调失败不影响回答
                            log.exception("on_step 回调失败")
                    result = _dispatch(db, name, args, context)
                    if on_step is not None:
                        try:
                            on_step({"kind": "result", "name": name, "summary": _step_summary(name, result)})
                        except Exception:  # noqa: BLE001
                            log.exception("on_step 回调失败")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            if stop_reason:
                break

        # 收尾：不再给工具，要求它基于已有信息直接回答（到限也让你拿到答案）
        messages.append(
            {
                "role": "user",
                "content": (
                    f"（系统提示：{stop_reason or '已达到本次提问的步骤上限'}。"
                    "请立刻基于上面已经取得的数据给出最终回答；不要再调用任何工具；"
                    "如果信息不足以回答，就直接说明缺什么。）"
                ),
            }
        )
        try:
            final = self.llm.chat_completion(
                messages, temperature=0.4, max_tokens=budget
            )
        except Exception as exc:  # noqa: BLE001
            return f"（已查到部分数据但收尾失败：{exc}）"
        text = (final.get("content") or "").strip()
        return text or "（已达到步骤上限，但没能组织出答案；可以换个更具体的问法。）"
