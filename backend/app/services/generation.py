"""选题生成服务：DeepSeek 生成三件套（标题/封面字/脚本）+ 平台外壳。

语气一致性：人设档案（标签+红线）+ 风格样本（本地 TF-IDF 检索）。
无密钥时输出确定性 mock 稿，保证开发/测试离线可跑。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..core.retrieval import TfidfIndex
from ..models.draft import Draft
from ..models.persona import PersonaTag
from ..models.video import Video
from .llm import DeepSeekClient, LLMError

GENERATION_SYSTEM = (
    "你是短视频口播脚本创作专家。严格模仿作者的语气与用词习惯，"
    "结合人设档案与风格样本，围绕给定选题创作。"
    "只输出 JSON："
    '{"title":"视频标题（抓眼球但不过度）","cover_text":"封面字（与标题不同，3-8字，适合压在图上的大字）",'
    '"script":"完整口播脚本（1-2分钟，约200-400字，口语化，有钩子有结尾互动）",'
    '"shells":{"douyin":"抖音发布文案+话题标签","bilibili":"B站简介","xiaohongshu":"小红书笔记正文（含emoji与话题）"}}'
)


def _persona_context(db: Session) -> dict:
    tags = (
        db.query(PersonaTag)
        .filter(PersonaTag.status == "confirmed")
        .order_by(PersonaTag.category, PersonaTag.id)
        .all()
    )
    return {
        "tags": [f"{t.label}: {t.description}" for t in tags if t.category != "redline"],
        "redlines": [t.label for t in tags if t.category == "redline"],
    }


def _style_samples(db: Session, topic: str, k: int = 3) -> list[str]:
    docs = []
    for v in db.query(Video).filter(Video.is_ad.is_(False)).all():
        if v.transcript and (v.transcript.corrected_text or v.transcript.transcript_text):
            docs.append(v.transcript.corrected_text or v.transcript.transcript_text)
    if not docs:
        return []
    index = TfidfIndex().build(docs)
    return [hit["text"] for hit in index.search(topic, top_k=k)]


def generate_draft(db: Session, topic: str, settings=None) -> Draft:
    ctx = _persona_context(db)
    samples = _style_samples(db, topic)
    user = "\n".join(
        [
            f"选题：{topic}",
            "",
            "作者人设：",
            *[f"- {t}" for t in ctx["tags"] or ["（暂无）"]],
            "",
            "红线（不要违反）：",
            *[f"- {r}" for r in ctx["redlines"] or ["（无）"]],
            "",
            "风格样本（模仿语气）：",
            *[f"--- 样本{i+1} ---\n{s[:400]}" for i, s in enumerate(samples)],
        ]
    )

    llm = DeepSeekClient(settings)
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": GENERATION_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.8,
            max_tokens=2500,
        )
        title = str(data.get("title", "")).strip()
        cover = str(data.get("cover_text", "")).strip()
        script = str(data.get("script", "")).strip()
        shells = data.get("shells") if isinstance(data.get("shells"), dict) else {}
    except LLMError:
        title = f"{topic}（mock 标题）"
        cover = (topic or "今日话题")[:8]
        script = (
            f"[mock 脚本] 大家好，今天想聊聊{topic}。"
            "很多人对这件事有误区，其实只要抓住三个关键点，结果会完全不一样。"
            "第一，先想清楚目标；第二，小步快跑试错；第三，持续复盘优化。"
            "如果你也有类似困惑，评论区告诉我，我们下期见。"
        )
        shells = {
            "douyin": f"#{topic} 短视频 干货分享",
            "bilibili": f"{topic} | 亲测有效的 3 个方法",
            "xiaohongshu": f"🔥 {topic}，建议收藏！",
        }

    draft = Draft(
        title=title or topic,
        cover_text=cover,
        script=script or topic,
        platform_shells=json.dumps(shells, ensure_ascii=False),
        source="ai",
        original_script=script or topic,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft
