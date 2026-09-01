from __future__ import annotations

"""纯逻辑（无第三方依赖）：复盘启发式兜底。"""


def best_topic_by_engagement(topic_stats: list[dict]) -> dict | None:
    """从各赛道统计中选出互动率最高者。topic_stats: [{topic, engagement}]"""
    valid = [t for t in topic_stats if t.get("engagement", 0) > 0]
    if not valid:
        return None
    return max(valid, key=lambda t: t["engagement"])


def heuristic_direction(best: dict | None, worst: dict | None) -> str:
    if best and worst:
        return (
            f"建议重点试错「{best['topic']}」方向（互动率 {best['engagement']}% 最高）；"
            f"「{worst['topic']}」表现偏弱（{worst['engagement']}%），可暂时减少投入或换切入角度。"
        )
    if best:
        return f"建议重点试错「{best['topic']}」方向。"
    return "数据还不足以判断方向，建议先稳定更新几期再复盘。"
