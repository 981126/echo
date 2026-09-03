"""纯逻辑（无第三方依赖）：从全量文案统计"作者风格画像"。

用途：生成时把统计出的语言习惯（口头禅/句长/语气）写入 prompt，
让模型"按数据模仿"而不是只靠几条样本临场发挥。
"""

from __future__ import annotations

import re
from collections import Counter

SENT_SPLIT = re.compile(r"[。！？!?…\n]+")
CJK_ALNUM = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")

# 高频功能词（不计入口头禅候选）
STOP_PHRASES = {
    "一个", "我们", "你们", "他们", "自己", "什么", "怎么", "这个", "那个",
    "因为", "所以", "但是", "如果", "就是", "然后", "而且", "其实", "真的",
    "可以", "没有", "不是", "这么", "那样", "一下", "时候", "现在", "可能",
    "觉得", "大家", "很多", "一些", "这种", "那些", "这样", "今天", "比如",
    "东西", "事情", "感觉", "知道", "应该", "还是", "已经", "不会", "不是",
    "出来", "起来", "过去", "开始", "之后", "之前", "有些", "有点", "一点",
}

STYLE_WORDS = ["其实", "真的", "我觉得", "说白了", "反正", "确实", "说实话", "讲真"]


def _phrase_counts(texts: list[str], n: int = 2, min_count: int = 3) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for text in texts:
        for seg in CJK_ALNUM.findall(text or ""):
            if len(seg) < n:
                continue
            for i in range(len(seg) - n + 1):
                phrase = seg[i : i + n]
                if n == 2 and phrase in STOP_PHRASES:
                    continue
                counter[phrase] += 1
    return [
        (ph, cnt) for ph, cnt in counter.most_common(200) if cnt >= min_count
    ][:12]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def build_style_profile(texts: list[str]) -> dict:
    """输入全部（非广告）文案 → 风格画像。"""
    docs = [t.strip() for t in texts if t and t.strip()]
    joined = "\n".join(docs)
    if not docs:
        return {"empty": True}

    sentences = [s for s in SENT_SPLIT.split(joined) if s.strip()]
    sent_lens = [float(len(s)) for s in sentences]

    def ratio(marks: str) -> float:
        if not sentences:
            return 0.0
        n = sum(1 for s in sentences if s.strip().endswith(tuple(marks)))
        return round(n / len(sentences), 3)

    style_word_counts = {w: joined.count(w) for w in STYLE_WORDS}
    bigrams = _phrase_counts(docs, 2)
    trigrams = _phrase_counts(docs, 3, min_count=2)
    return {
        "empty": False,
        "doc_count": len(docs),
        "avg_doc_len": round(sum(len(d) for d in docs) / len(docs), 1),
        "avg_sent_len": round(sum(sent_lens) / len(sent_lens), 1) if sent_lens else 0,
        "median_sent_len": _median(sent_lens),
        "question_ratio": ratio("？?"),
        "exclaim_ratio": ratio("！!"),
        "top_phrases": [p for p, _ in bigrams],
        "top_triples": [p for p, _ in trigrams],
        "style_words": {k: v for k, v in style_word_counts.items() if v > 0},
    }


def format_style_profile(profile: dict) -> str:
    if profile.get("empty"):
        return "（素材不足，暂无统计）"
    lines = [
        f"共统计 {profile['doc_count']} 条文案；平均每条 {profile['avg_doc_len']} 字。",
        f"句子平均 {profile['avg_sent_len']} 字（中位 {profile['median_sent_len']} 字）",
        f"反问/提问句占比 {profile['question_ratio']}；感叹句占比 {profile['exclaim_ratio']}。",
    ]
    if profile.get("top_phrases"):
        lines.append("高频口头禅/用词：" + "、".join(profile["top_phrases"][:8]))
    if profile.get("top_triples"):
        lines.append("常用短句片段：" + "、".join(profile["top_triples"][:6]))
    if profile.get("style_words"):
        words = "、".join(f"{k}({v})" for k, v in list(profile["style_words"].items())[:6])
        lines.append("标志性语气词：" + words)
    return "\n".join(lines)
