"""R-266 Phase B：生成时有选择地注入开头样本（自己高/低 + 同行高）。

规则（见开发设计 5.6）：
- 自己的样本 <20 条 → 不注入；
- 主题与样本相关度 <0.15 → 不注入；
- 有 experience 证据（第一人称经历）→ 不注入同行；纯经历且自己高留人 <3 条 → 整篇不注入；
- 上限 11 条：自己高 5、自己低 3、同行高 3；不注入时不占位、只记原因。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.opening_sample import OpeningSample
from .author_assets import _cosine

MIN_OWN_SAMPLES = 20
RELEVANCE_MIN = 0.08  # 与作者资产检索同阈值；开头句很短，0.15 会把绝大多数主题挡在门外
MAX_TOTAL = 11
OWN_HIGH_LIMIT = 5
OWN_LOW_LIMIT = 3
PEER_HIGH_LIMIT = 3
MIN_OWN_HIGH_FOR_EXPERIENCE = 3


def _metric_text(sample: OpeningSample) -> str:
    if sample.source_kind == "own" and sample.finish_5s_rate is not None:
        text = f"5 秒完播 {sample.finish_5s_rate * 100:.0f}%（样本内第 {sample.rank_score:.0f} 分位）"
        if sample.negative_reason:
            text += f"，这条{sample.negative_reason}"
        return text
    return f"播放 {sample.rank_score:.1f} 倍于该账号中位（公开数据）"


def _sample_out(sample: OpeningSample) -> dict:
    return {
        "id": sample.id,
        "source_kind": sample.source_kind,
        "polarity": sample.polarity,
        "text": sample.text,
        "hook_type": sample.hook_type,
        "metric": _metric_text(sample),
    }


def _prompt_block(selected: list[dict]) -> str:
    lines = ["【开头参考】只借结构与节奏，不得连续照抄 8 字以上；同行内容不得写成你自己的经历。"]
    for item in selected:
        label = "自己" if item["source_kind"] == "own" else "同行"
        tag = "反例" if item["polarity"] == "low" else "参考"
        lines.append(f"- 开头{tag}·{label}·{item['metric']}：「{item['text']}」")
    return "\n".join(lines)


def select_opening_samples(
    db: Session,
    creator_id: int,
    topic: str,
    input_text: str = "",
    *,
    has_experience: bool = False,
) -> dict:
    """返回 {injected, reason, samples, prompt, counts}；不注入时 samples=[]。"""
    own = (
        db.query(OpeningSample)
        .filter(OpeningSample.source_kind == "own", OpeningSample.creator_id == creator_id)
        .all()
    )
    if len(own) < MIN_OWN_SAMPLES:
        return {
            "injected": False,
            "reason": f"自己的开头样本只有 {len(own)} 条（需 ≥{MIN_OWN_SAMPLES}）",
            "samples": [],
            "prompt": "",
            "counts": {"own": len(own), "peer": 0},
        }

    query = f"{topic}\n{input_text}".strip()
    scored = sorted(((_cosine(query, row.text), row) for row in own), key=lambda item: item[0], reverse=True)
    best = scored[0][0] if scored else 0.0
    if best < RELEVANCE_MIN:
        return {
            "injected": False,
            "reason": f"与开头样本相关度 {best:.2f} 低于 {RELEVANCE_MIN}",
            "samples": [],
            "prompt": "",
            "counts": {"own": len(own), "peer": 0},
        }

    high = [row for _score, row in scored if row.polarity == "high"][:OWN_HIGH_LIMIT]
    low = sorted(
        (row for _score, row in scored if row.polarity == "low"),
        key=lambda row: row.rank_score,
    )[:OWN_LOW_LIMIT]

    if has_experience and len(high) < MIN_OWN_HIGH_FOR_EXPERIENCE:
        return {
            "injected": False,
            "reason": "纯经历主题且自己的高留人开头不足 3 条，宁缺毋滥",
            "samples": [],
            "prompt": "",
            "counts": {"own": len(own), "peer": 0},
        }

    selected: list[dict] = [*[_sample_out(row) for row in high], *[_sample_out(row) for row in low]]

    peer_count = 0
    if not has_experience:
        peers = db.query(OpeningSample).filter(OpeningSample.source_kind == "peer").all()
        peer_high = sorted(
            (
                row
                for row in peers
                if row.polarity == "high" and _cosine(query, row.text) >= RELEVANCE_MIN
            ),
            key=lambda row: row.rank_score,
            reverse=True,
        )[:PEER_HIGH_LIMIT]
        peer_count = len(peer_high)
        selected.extend(_sample_out(row) for row in peer_high)

    seen: set[int] = set()
    unique: list[dict] = []
    for item in selected:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
        if len(unique) >= MAX_TOTAL:
            break

    if not unique:
        return {
            "injected": False,
            "reason": "没有可用的高/低留人样本（可能都在中间档）",
            "samples": [],
            "prompt": "",
            "counts": {"own": len(own), "peer": 0},
        }

    return {
        "injected": True,
        "reason": "",
        "samples": unique,
        "prompt": _prompt_block(unique),
        "counts": {"own": len(own), "peer": peer_count},
    }
