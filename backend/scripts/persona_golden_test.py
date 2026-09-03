"""人设验收样例（golden test）：生成一段"像作者"的样稿供人工验收。

用法：
    cd backend && pip install -r requirements.txt
    python scripts/persona_golden_test.py "为什么面试总被挂"
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models.persona import PersonaTag  # noqa: E402
from app.models.video import Video  # noqa: E402
from app.services.llm import DeepSeekClient, LLMError  # noqa: E402

SYSTEM_PROMPT = (
    "你是口播脚本模仿专家。严格模仿作者的语气、用词习惯和节奏，"
    "不要写成通用文案。只输出脚本正文，不要解释。"
)


def collect_context(db) -> dict:
    tags = (
        db.query(PersonaTag)
        .filter(PersonaTag.status == "confirmed", PersonaTag.category == "style")
        .all()
    )
    redlines = (
        db.query(PersonaTag)
        .filter(PersonaTag.status == "confirmed", PersonaTag.category == "redline")
        .all()
    )
    videos = db.query(Video).filter(Video.is_ad.is_(False)).all()
    samples = []
    for v in videos:
        if v.transcript and (v.transcript.corrected_text or v.transcript.transcript_text):
            samples.append(v.transcript.corrected_text or v.transcript.transcript_text)
    return {
        "tags": [f"{t.label}: {t.description}" for t in tags],
        "redlines": [r.label for r in redlines],
        "samples": samples[:3],  # 精选风格样本（前 3 条）
    }


def build_user_prompt(topic: str, ctx: dict) -> str:
    parts = [f"主题：{topic}", ""]
    parts.append("作者人设（标签+描述）：")
    parts.extend(f"- {t}" for t in ctx["tags"] or ["（暂无）"])
    parts.append("")
    parts.append("红线（不要违反）：")
    parts.extend(f"- {r}" for r in ctx["redlines"] or ["（无）"])
    parts.append("")
    parts.append("作者风格样本（模仿其语气）：")
    parts.extend(f"--- 样本{i+1} ---\n{s[:500]}" for i, s in enumerate(ctx["samples"]))
    parts.append("")
    parts.append("请用作者的语气写一段 60~90 字的口播开头。")
    return "\n".join(parts)


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "求职面试常见误区"
    init_db()
    db = SessionLocal()
    try:
        ctx = collect_context(db)
    finally:
        db.close()

    out_dir = get_settings().data_dir / "golden"
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = DeepSeekClient()
    try:
        sample = llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(topic, ctx)},
            ],
            temperature=0.8,
            max_tokens=500,
        )
    except LLMError:
        sample = (
            f"[mock 验收样稿，未配置 DeepSeek 密钥] 大家好，今天想聊聊{topic}。"
            "很多人把这件事想复杂了，其实核心就三步：先想清楚，再敢行动，最后复盘。"
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"golden_{stamp}.md"
    out.write_text(
        f"# 人设验收样例\n\n- 时间: {stamp}\n- 主题: {topic}\n- 状态: 待作者验收\n\n## 样稿\n\n{sample}\n",
        encoding="utf-8",
    )
    print("=" * 40)
    print(sample)
    print("=" * 40)
    print(f"已保存到: {out}")
    print("验收方式：通读样稿，判断语气像不像你；不像则先完善人设档案再重跑。")


if __name__ == "__main__":
    main()
