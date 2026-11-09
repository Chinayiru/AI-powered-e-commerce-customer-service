"""检索层：接口 + 关键词实现（BM25 over 中文字符二元组）。

一期不引入向量库（CONTRACT §7）：200 条 QA 的暴力余弦没有任何工程收益，
先把"能不能被检索到"这件事测出来，再决定要不要上库。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

from app.contracts.models import Hit, QaDoc

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
ASCII_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    toks: list[str] = ASCII_RE.findall(text)
    for seg in CJK_RE.findall(text):
        toks.extend(seg[i : i + 2] for i in range(len(seg) - 1))
        toks.extend(seg)  # 单字兜底，短查询也能命中
    return toks


class Retriever(Protocol):
    name: str

    def index(self, docs: list[QaDoc]) -> None: ...
    def search(self, query: str, k: int = 5) -> list[Hit]: ...


class KeywordRetriever:
    name = "keyword"

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs: list[QaDoc] = []
        self.tfs: list[Counter[str]] = []
        self.lens: list[int] = []
        self.df: Counter[str] = Counter()
        self.avg_len = 0.0
        self.N = 0

    def _text(self, doc: QaDoc) -> str:
        return " ".join([doc.question, doc.answer, " ".join(doc.tags), doc.category])

    def index(self, docs: list[QaDoc]) -> None:
        self.docs = list(docs)
        self.tfs = [Counter(tokenize(self._text(d))) for d in self.docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.N = len(self.docs)
        self.avg_len = (sum(self.lens) / self.N) if self.N else 0.0
        self.df = Counter()
        for tf in self.tfs:
            self.df.update(tf.keys())

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.N - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 5) -> list[Hit]:
        q_terms = Counter(tokenize(query))
        scored: list[tuple[float, int]] = []
        for i, tf in enumerate(self.tfs):
            score = 0.0
            norm = 1 - self.b + self.b * (self.lens[i] / self.avg_len if self.avg_len else 1)
            for term, qn in q_terms.items():
                f = tf.get(term, 0)
                if not f:
                    continue
                score += self._idf(term) * (f * (self.k1 + 1)) / (f + self.k1 * norm) * qn
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda x: (-x[0], self.docs[x[1]].qa_id))
        return [
            Hit(qa_id=self.docs[i].qa_id, score=round(s, 4), source=self.name)
            for s, i in scored[:k]
        ]
