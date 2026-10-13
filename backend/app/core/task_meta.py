"""后台任务展示元数据（R-202）：中文名 + 前端跳转目标。

抽出来供 `app/tasks.py`（写通知）与 `app/api/tasks.py`（任务列表/进行中指示器）共用，
避免 api 反向依赖 tasks 的私有函数。
"""

from __future__ import annotations

KIND_LABELS = {
    "import_video": "素材转写",
    "persona_init": "人设初始化",
    "persona_rebuild": "人设重建",
    "persona_incremental": "人设增量校验",
    "persona_auto_confirm_backlog": "待确认建议清理",
    "prompt_eval": "提示词候选评测",
    "prompt_rule_optimize": "规则型提示词优化",
    "prompt_optimize": "提示词优化",
    "prompt_refresh_hint": "提示词优化提醒",
    "daily_pipeline": "每日流水线",
    "diff_analysis": "草稿差异分析",
    "feedback_analysis": "反馈学习分析",
    "generate_draft": "AI 文案生成",
    "platform_sync": "平台数据同步",
    "platform_sync_single": "素材数据同步",
    "platform_media": "素材媒体补齐",
    "card_sync": "素材同步",
    "benchmark_rerun": "重新对标",
    "benchmark_prepare": "对标转写补齐",
    "benchmark_analyze": "AI 分析",
    "benchmark_rewrite": "洗稿",
    "opportunity_clusters": "观众提问榜",
    "opportunity_weekly": "每周灵感包",
    "opportunity_gap": "缺口选题",
    "draft_angles": "生成角度",
    "draft_suggest_meta": "生成标题封面标签",
    "hot_refresh": "抓取热点",
    "publish_backfill": "回填历史发布",
    "llm_fallback": "模型降级",
    "model_selfcheck": "双模型兼容性自检",
    "schema_check": "库结构自检",
    "task_interrupted": "任务中断",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def target(kind: str, payload: dict | None = None, result=None) -> str:
    """任务完成/进行中时前端点击要跳转的路径。"""
    payload = payload or {}
    if kind == "import_video":
        return f"/videos?edit={payload.get('video_id', '')}"
    if kind == "platform_media":
        if isinstance(result, dict) and result.get("video_id"):
            return f"/videos?edit={result['video_id']}"
        return "/videos"
    if kind in ("persona_init", "persona_rebuild", "persona_incremental", "persona_auto_confirm_backlog"):
        return "/persona"
    if kind == "prompt_eval":
        return f"/prompts?key={payload.get('key', '')}"
    if kind in ("prompt_rule_optimize", "prompt_optimize"):
        return f"/prompts?key={payload.get('key', '')}" if payload.get("key") else "/prompts"
    if kind == "prompt_refresh_hint":
        return "/prompts?key=generation"
    if kind == "daily_pipeline":
        return "/home"
    if kind == "diff_analysis":
        return f"/drafts?id={payload.get('draft_id', '')}"
    if kind == "feedback_analysis":
        return f"/drafts?id={payload.get('draft_id', '')}"
    if kind == "generate_draft":
        if isinstance(result, dict) and result.get("draft_id"):
            return f"/drafts?id={result['draft_id']}"
        return "/drafts"
    if kind in ("platform_sync", "platform_sync_single"):
        return "/creators"
    if kind in ("benchmark_rerun", "benchmark_prepare", "benchmark_analyze", "benchmark_rewrite"):
        return "/benchmark"
    if kind in ("opportunity_clusters", "opportunity_weekly", "opportunity_gap", "hot_refresh", "publish_backfill"):
        return "/home"
    if kind == "draft_angles":
        return "/home"
    if kind == "draft_suggest_meta":
        return f"/drafts?id={payload.get('draft_id', '')}"
    if kind == "model_selfcheck":
        return "/prompts"
    return "/home"
