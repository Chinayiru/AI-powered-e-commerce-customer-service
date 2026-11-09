"""混合检索：关键词 + 一个**假的**向量通道。

ScriptedEmbedder 用字符二元组哈希成固定维度，只为"混合通路能跑、能被评测"，
不产生任何语义能力。报告里必须标注 provider=scripted，否则这组数字会被误读
（CONTRACT §7.3 / AC19）。
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter

from app.contracts.models import Hit, QaDoc
from app.retrieval.keyword import KeywordRetriever, tokenize

DIM = 64


class ScriptedEmbedder:
    name = "scripted"

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in tokenize(text):
            h = int(hashlib.sha256(tok.encode()).hexdigest()[:8], 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class HybridRetriever:
    name = "hybrid"

    def __init__(self, alpha: float = 0.6) -> None:
        self.alpha = alpha
        self.kw = KeywordRetriever()
        self.emb = ScriptedEmbedder()
        self.vecs: list[list[float]] = []
        self.docs: list[QaDoc] = []

    def index(self, docs: list[QaDoc]) -> None:
        self.docs = list(docs)
        self.kw.index(docs)
        self.vecs = [self.emb.embed(" ".join([d.question, d.answer, " ".join(d.tags)])) for d in docs]

    def search(self, query: str, k: int = 5) -> list[Hit]:
        kw_hits = {h.qa_id: h.score for h in self.kw.search(query, k=len(self.docs))}
        kmax = max(kw_hits.values()) if kw_hits else 1.0
        qv = self.emb.embed(query)
        scored: list[tuple[float, str]] = []
        for i, doc in enumerate(self.docs):
            kscore = kw_hits.get(doc.qa_id, 0.0) / kmax if kmax else 0.0
            vscore = _cos(qv, self.vecs[i])
            score = self.alpha * kscore + (1 - self.alpha) * vscore
            if score > 0:
                scored.append((score, doc.qa_id))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [Hit(qa_id=qa, score=round(s, 4), source=self.name) for s, qa in scored[:k]]
