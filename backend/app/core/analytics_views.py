"""只读分析视图（R-147 P1）：给 AI 对话的 `sql_query` 工具提供**安全的查询面**。

设计原则
- **只暴露视图，不暴露原始表**：`app_kv`（含明文模型 Key）、`ai_prompts`（提示词正文）、
  `chat_*`、`schema_migrations`、`background_tasks` 等敏感/内部表一律不进视图，也不在允许名单里。
- **视图即白名单**：`sql_query` 校验「表引用必须全部来自这些视图名」，从根上挡住越权查询。
- **幂等**：每次启动 `DROP VIEW IF EXISTS` + `CREATE VIEW`，改定义即生效（SQLite 无 CREATE OR REPLACE VIEW）。
- **列名 + 中文说明**：SQLite 没有列注释，所以这里维护 `SCHEMA_NOTES` 作为给模型的 schema 卡片。
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect

from ..core.log import get_logger

log = get_logger("analytics_views")

# 视图名 → 定义（只读、已裁掉长文本/敏感字段）
VIEWS: dict[str, str] = {
    "v_videos": """
        SELECT id, title, filename, status, platforms, main_topics, tags,
               is_ad, tags_confirmed, published_at, planned_publish_at, created_at
        FROM videos
    """,
    "v_drafts": """
        SELECT id, title, cover_text, source, status, version,
               length(COALESCE(script, '')) AS script_len,
               substr(COALESCE(script, ''), 1, 120) AS script_preview,
               prompt_version, persona_version, created_at, updated_at
        FROM drafts
    """,
    "v_feedback": """
        SELECT id, draft_id, rating, liked, hook_score, pace_score,
               ending_score, style_score, substr(COALESCE(comment, ''), 1, 120) AS comment, created_at
        FROM feedback
    """,
    "v_persona_tags": """
        SELECT id, label, description, dimension, category, source, status, version, created_at
        FROM persona_tags
    """,
    "v_topics": """
        SELECT id, run_date, slot, title, platform, score, reason, draft_id, created_at
        FROM topic_candidates
    """,
    "v_ideas": """
        SELECT id, source, platform, title, post_title, likes, used, snapshot_date, created_at
        FROM topic_ideas
    """,
    "v_metrics": """
        SELECT m.id, m.video_id, v.title AS video_title, m.snapshot_date,
               m.plays, m.likes, m.favorites, m.comments, m.followers_gained, m.source
        FROM metrics_snapshots m
        LEFT JOIN videos v ON v.id = m.video_id
    """,
    "v_platform_posts": """
        SELECT p.id, p.platform, p.title, p.publish_time, p.is_ad, p.work_id,
               p.local_video_id, c.name AS creator_name, c.kind AS creator_kind
        FROM platform_posts p
        LEFT JOIN creator_accounts a ON a.id = p.account_id
        LEFT JOIN creators c ON c.id = a.creator_id
    """,
}

# 给模型的 schema 卡片：视图 → 一句话说明 + 列的中文含义（只写容易误解的列）
SCHEMA_NOTES: dict[str, dict] = {
    "v_videos": {
        "desc": "素材库（本地/云端视频）",
        "columns": {
            "status": "planned=待发布 / published=已发布",
            "platforms": "JSON 数组文本，如 [\"douyin\"]；判定平台用 LIKE '%\"douyin\"%'",
            "main_topics": "JSON 数组文本：求职/面试/赚钱/知识/其他",
            "tags": "JSON 数组文本（作者确认的标签）",
            "is_ad": "1=广告",
            "tags_confirmed": "1=标签已确认",
            "published_at": "发布时间（北京时间，可能为空）",
        },
    },
    "v_drafts": {
        "desc": "脚本草稿",
        "columns": {
            "status": "draft=草稿 / used=待制作 / archived=不采用 / deleted=已删除",
            "source": "ai=AI 生成 / manual=手写",
            "script_len": "脚本字数（脚本全文不在此视图，需要看内容用 get_video_detail 或直接查草稿接口）",
            "script_preview": "脚本前 120 字",
            "persona_version": "生成时的人设版本",
            "prompt_version": "生成时用的提示词版本",
        },
    },
    "v_feedback": {
        "desc": "作者对草稿的反馈（1-5 分）",
        "columns": {
            "rating": "总评分 1-5",
            "liked": "1=点赞/喜欢",
            "hook_score": "开场钩子分 1-5",
            "pace_score": "内容节奏分 1-5",
            "ending_score": "结尾引导分 1-5",
            "style_score": "像作者程度分 1-5",
        },
    },
    "v_persona_tags": {
        "desc": "人设标签与红线",
        "columns": {
            "status": "confirmed=已确认 / suggested=待确认 / rejected=已拒绝",
            "category": "redline=红线 / 其它为人设分类",
            "dimension": "语气/价值观/口头禅/选题/受众/结构/专业/其他",
        },
    },
    "v_topics": {
        "desc": "每日流水线产出的选题候选",
        "columns": {"slot": "comment=评论区 / hot=热榜 / ai=AI 建议", "score": "匹配分 0-100"},
    },
    "v_ideas": {
        "desc": "灵感池（评论/热榜灵感）",
        "columns": {"source": "comment=评论 / hot=热榜", "used": "1=已被采用", "likes": "评论点赞数"},
    },
    "v_metrics": {
        "desc": "本地素材的指标快照（按天）",
        "columns": {"snapshot_date": "快照日期", "plays": "播放量", "followers_gained": "当日涨粉"},
    },
    "v_platform_posts": {
        "desc": "平台云端作品（抖音/B站/小红书）",
        "columns": {
            "creator_kind": "owner=主博主 / benchmark=对标博主",
            "local_video_id": "已绑定到本地素材的 id（空=未下载）",
            "is_ad": "1=广告/商单",
        },
    },
}


def allowed_views() -> set[str]:
    return set(VIEWS)


def ensure_views(bind: Engine) -> list[str]:
    """幂等创建全部只读视图；返回视图名列表。失败只记日志（不影响启动）。"""
    created: list[str] = []
    for name, body in VIEWS.items():
        try:
            with bind.begin() as conn:
                conn.exec_driver_sql(f"DROP VIEW IF EXISTS {name}")
                conn.exec_driver_sql(f"CREATE VIEW {name} AS {body}")
            created.append(name)
        except Exception:  # noqa: BLE001 视图建不出来不能让服务起不来
            log.exception("创建分析视图失败：%s", name)
    if created:
        log.info("分析视图就绪：%d 个（%s）", len(created), "、".join(created))
    return created


_CARD_CACHE: str | None = None


def schema_card(bind: Engine | None = None) -> str:
    """给模型的 schema 卡片（视图名 + 真实列名 + 中文说明）。

    列名从 SQLite 实际视图读（`inspect`），不是解析 SQL 文本 —— 保证和线上一致。
    视图定义只在部署时变，故缓存一份。
    """
    global _CARD_CACHE
    if _CARD_CACHE is not None:
        return _CARD_CACHE
    lines: list[str] = []
    inspector = inspect(bind) if bind is not None else None
    for name in VIEWS:
        note = SCHEMA_NOTES.get(name, {})
        cols: list[str] = []
        if inspector is not None:
            try:
                cols = [c["name"] for c in inspector.get_columns(name)]
            except Exception:  # noqa: BLE001 视图可能还没建
                cols = []
        lines.append(f"- {name}（{note.get('desc', '')}）：{', '.join(cols) or '（列信息不可用）'}")
        for col, desc in (note.get("columns") or {}).items():
            lines.append(f"    · {col}：{desc}")
    _CARD_CACHE = "\n".join(lines)
    return _CARD_CACHE


__all__ = ["SCHEMA_NOTES", "VIEWS", "allowed_views", "ensure_views", "schema_card"]
