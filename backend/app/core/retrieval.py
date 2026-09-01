from __future__ import annotations

"""纯逻辑（无第三方依赖）：TF-IDF 文本检索（风格样本召回）。"""
import math
import re
from collections import Counter


CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
LATIN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """中文按字符二元组分词（免装分词库），英文/数字按词。"""
    text = (text or "").lower()
    tokens: list[str] = []
    for cjk in CJK_RE.findall(text):
        if len(cjk) == 1:
            tokens.append(cjk)
        else:
            tokens.extend(cjk[i : i + 2] for i in range(len(cjk) - 1))
    tokens.extend(LATIN_RE.findall(text))
    return tokens


class TfidfIndex:
    """极简 TF-IDF 检索，单用户样本量下够用（BM25 可后续替换）。"""

    def __init__(self) -> None:
        self.docs: list[str] = []
        self._tfidf: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}

    def build(self, docs: list[str]) -> "TfidfIndex":
        self.docs = [d or "" for d in docs]
        doc_tokens = [tokenize(d) for d in self.docs]
        df: Counter[str] = Counter()
        for tokens in doc_tokens:
            for term in set(tokens):
                df[term] += 1
        n = max(len(doc_tokens), 1)
        self._idf = {term: math.log((n + 1) / (count + 1)) + 1 for term, count in df.items()}
        self._tfidf = []
        for tokens in doc_tokens:
            tf = Counter(tokens)
            total = max(sum(tf.values()), 1)
            vec = {term: (count / total) * self._idf.get(term, 0.0) for term, count in tf.items()}
            self._tfidf.append(vec)
        return self

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        q_tokens = tokenize(query)
        if not q_tokens or not self._tfidf:
            return []
        q_tf = Counter(q_tokens)
        q_vec = {term: (count / max(sum(q_tf.values()), 1)) * self._idf.get(term, 0.0) for term, count in q_tf.items()}
        scored = []
        for i, vec in enumerate(self._tfidf):
            score = sum(q_vec.get(term, 0.0) * weight for term, weight in vec.items())
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"index": i, "score": round(score, 6), "text": self.docs[i][:500]}
            for score, i in scored[:top_k]
        ]
