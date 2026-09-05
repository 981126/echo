"""脚本体检（R-030⑦）：生成稿是否踩红线 / 有钩子 / 有结尾引导 / 长度健康。

纯逻辑、无第三方依赖；由草稿接口调用，作者可"一键回炉"重写一轮。
"""

from __future__ import annotations

_HOOK_MARKS = ("？", "！", "?", "!", "你敢", "别", "为什么", "真相", "其实", "3 件事", "3件事", "避坑")
_ENDING_HINTS = ("关注", "评论", "点赞", "收藏", "下期", "一起聊聊", "评论区", "留言", "私信", "告诉我")


def check_script(script: str, redlines: list[str] | None = None, topic: str = "") -> dict:
    """返回体检结果：issues 列表 + ok 是否自动回炉。

    - 红线词命中 → 必须回炉
    - 无结尾引导 / 首句无钩子 / 篇幅异常 → 提示回炉一轮
    """
    text = (script or "").strip()
    issues: list[str] = []
    for r in (redlines or []):
        r = (r or "").strip()
        if r and r in text:
            issues.append(f"命中红线：「{r}」")
    if not text:
        issues.append("脚本为空")
    else:
        first = text[:40]
        if not any(m in first for m in _HOOK_MARKS):
            issues.append("开头 40 字缺少钩子（问句/感叹/反常识）")
        if not any(h in text[-120:] for h in _ENDING_HINTS):
            issues.append("结尾缺少互动引导（关注/评论/下期等）")
        length = len(text)
        if length < 120:
            issues.append(f"篇幅过短（{length} 字，建议 200-400）")
        elif length > 700:
            issues.append(f"篇幅过长（{length} 字，可能超过 2 分钟）")
    need = len(issues) > 0
    return {"ok": not need, "issues": issues, "length": len(text)}
