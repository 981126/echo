from __future__ import annotations

"""纯逻辑（无第三方依赖）：无 LLM 时的关键词兜底匹配打分。"""


def keyword_fallback_match(
    hot_items: list[dict],
    keywords: list[str],
    top_n: int = 5,
) -> list[dict]:
    """按关键词在热点标题中的命中数打分，返回前 top_n。

    hot_items: [{"title": "...", "platform": "...", "heat": "..."}]
    keywords: 人设/赛道关键词，如 ["求职", "面试", "赚钱"]
    """
    scored = []
    for item in hot_items:
        title = (item.get("title") or "").lower()
        hits = [k for k in keywords if k and k.lower() in title]
        if not hits:
            continue
        scored.append(
            {
                "title": item.get("title", ""),
                "platform": item.get("platform", ""),
                "heat": item.get("heat", ""),
                "score": min(len(hits) * 20, 100),
                "reason": "命中关键词：" + "、".join(hits),
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]
