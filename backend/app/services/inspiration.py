"""灵感随手记服务（R-186）：把一句随手记提炼成可直接写的选题标题。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from . import llm_router

_SYSTEM = (
    "你是短视频选题策划。把作者随手记的一句观察/经历/想法，提炼成 1 个可直接写口播稿的选题标题："
    "具体、有钩子、贴合作者（求职/面试/赚钱/知识）赛道，不超过 30 字。"
    "只输出这一个标题本身，不要解释、不要引号、不要多余文字。"
)


def refine_topic(db: Session, text: str) -> str:
    """把随手记正文提炼成选题标题（LLM 不可用时原样返回，不阻塞）。

    R-240 M7：**遗留同步 LLM 调用**——在请求路径同步等 1 次 LLM，后续改为后台任务；
    本次仅把功能名标为 `ideas`（走 M6 的 30s 超时预算），不改返回结构。
    """
    text = (text or "").strip()
    if not text:
        return ""
    try:
        llm = llm_router.primary_llm(db, "ideas")
        out = llm.chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text[:2000]}],
            temperature=0.7,
            max_tokens=200,
        )
        topic = (out or "").strip().splitlines()[0].strip().strip("“”\"'`. ") if out else ""
        return topic[:80] or text[:80]
    except Exception:  # noqa: BLE001 AI 不可用则直接用原文当选题
        return text[:80]
