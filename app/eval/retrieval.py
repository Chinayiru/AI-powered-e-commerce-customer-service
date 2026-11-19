"""检索评测：recall@5 与 keyword/hybrid 对比（AC17–AC19）。

    python -m app.eval.retrieval --retriever keyword
    python -m app.eval.retrieval --compare

输出 reports/retrieval_v0.json；数字只对 synthetic 数据集负责。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.contracts.models import QaDoc
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.keyword import KeywordRetriever

ROOT = Path(__file__).resolve().parents[2]
KB = ROOT / "data" / "kb" / "qa_40.jsonl"
EVAL = ROOT / "data" / "eval" / "queries_60.jsonl"
OUT = ROOT / "reports" / "retrieval_v0.json"
THRESHOLD_PT = 0.03


def decide_vector(delta: float, threshold: float = THRESHOLD_PT) -> bool:
    """向量通道只在相对 keyword 有 >= threshold 的提升时开启（AC19）。"""
    return round(delta, 4) >= threshold


def load() -> tuple[list[QaDoc], list[dict]]:
    docs = [QaDoc.model_validate(json.loads(line)) for line in KB.read_text(encoding="utf-8").splitlines() if line.strip()]
    queries = [json.loads(line) for line in EVAL.read_text(encoding="utf-8").splitlines() if line.strip()]
    return docs, queries


def evaluate(retriever, docs: list[QaDoc], queries: list[dict], k: int = 5) -> dict:
    retriever.index(docs)
    unlabeled = [q["query_id"] for q in queries if not q.get("gold")]
    hits = 0
    misses: list[dict] = []
    for q in queries:
        got = [h.qa_id for h in retriever.search(q["query"], k=k)]
        if any(g in got for g in q["gold"]):
            hits += 1
        else:
            misses.append({"query_id": q["query_id"], "query": q["query"], "gold": q["gold"], "top5": got})
    return {
        "retriever": retriever.name,
        "recall_at_5": round(hits / len(queries), 4),
        "n_queries": len(queries),
        "n_hits": hits,
        "unlabeled": len(unlabeled),
        "misses": misses,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retriever", choices=["keyword", "hybrid"], default="keyword")
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args(argv)

    docs, queries = load()
    payload: dict = {
        "dataset": "synthetic",
        "provider": "scripted",
        "k": 5,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if args.compare:
        kw = evaluate(KeywordRetriever(), docs, queries)
        hy = evaluate(HybridRetriever(), docs, queries)
        delta = round(hy["recall_at_5"] - kw["recall_at_5"], 4)
        payload.update({
            "keyword": kw,
            "hybrid": hy,
            "delta_pt": delta,
            "vector_enabled": decide_vector(delta),
            "note": "hybrid 的向量通道是 ScriptedEmbedder，不产生语义收益；delta 只用于验证阈值逻辑",
        })
    else:
        retriever = KeywordRetriever() if args.retriever == "keyword" else HybridRetriever()
        payload["result"] = evaluate(retriever, docs, queries)
        payload["retriever"] = retriever.name

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.compare:
        print(f"keyword recall@5={payload['keyword']['recall_at_5']:.3f}  hybrid recall@5={payload['hybrid']['recall_at_5']:.3f}  delta={delta:+.3f}")
        print(f"vector_enabled={payload['vector_enabled']}  (threshold {THRESHOLD_PT:.2f})")
    else:
        r = payload["result"]
        print(f"{r['retriever']} recall@5={r['recall_at_5']:.3f}  hits={r['n_hits']}/{r['n_queries']}  unlabeled={r['unlabeled']}")
        for m in r["misses"][:10]:
            print(f"  miss {m['query_id']} {m['query']} -> {m['top5']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
