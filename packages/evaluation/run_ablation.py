"""Retrieval and grounding ablations on the real corpus in data/corpus/.

  E1   fixed-size chunks + dense
  E2   structure-aware chunks + dense
  E2b  E2 + contextual chunk headers
  E3   E2b + hybrid (dense + full-text, fused with RRF)
  E7   E3 + grounded generation + claim verification (citation precision, abstention)

Not run: reranker (needs sentence-transformers, which is not a dependency yet), query rewriting
(needs multi-turn golden questions) and parent-child context (not built). They are listed as Planned.

    python -m packages.evaluation.run_ablation --only E1,E2,E2b,E3,E7
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from packages.evaluation.corpus import NoCorpusError, gold_ids_for, ingest_corpus, ranked_gold_ids
from packages.evaluation.loaders import load_golden_questions
from packages.evaluation.metrics import mrr_at_k, ndcg_at_k, percentile, recall_at_k
from packages.llm_gateway import gateway
from packages.retrieval.db import new_session
from packages.retrieval.generation import generate_grounded_answer
from packages.retrieval.hybrid import RetrievalConfig, hybrid_retrieve
from packages.verification.pipeline import verify_grounded_answer

# Ten results so recall@10 really looks at ten; the answer step uses the first five, as the API does.
DENSE_ONLY = RetrievalConfig(use_dense=True, use_sparse=False, top_k=10)
HYBRID = RetrievalConfig(use_dense=True, use_sparse=True, top_k=10)
ANSWER_TOP_K = 5

EXPERIMENTS: dict[str, dict[str, Any]] = {
    "E1": {"name": "Fixed chunks + dense", "chunking": "fixed", "headers": False, "config": DENSE_ONLY},
    "E2": {"name": "Structure-aware chunks + dense", "chunking": "structure", "headers": False, "config": DENSE_ONLY},
    "E2b": {"name": "E2 + contextual chunk headers", "chunking": "structure", "headers": True, "config": DENSE_ONLY},
    "E3": {"name": "E2b + hybrid (dense + full-text + RRF)", "chunking": "structure", "headers": True, "config": HYBRID},
    "E7": {
        "name": "E3 + claim verification",
        "chunking": "structure",
        "headers": True,
        "config": HYBRID,
        "verify": True,
    },
}


def run_experiment(
    session: Session,
    exp: dict[str, Any],
    questions: list,
    notebook_id: str,
    user_id: str,
) -> dict[str, Any]:
    config: RetrievalConfig = exp["config"]
    gold, ranked, latencies, by_category = [], [], [], {}
    citation_precisions, abstentions, costs = [], [], []

    for q in questions:
        usage_before = gateway.USAGE["cost_usd"]
        start = time.perf_counter()
        retrieved = hybrid_retrieve(session, q.question, user_id, notebook_id, config)

        answer = None
        if exp.get("verify"):
            answer = verify_grounded_answer(generate_grounded_answer(q.question, retrieved[:ANSWER_TOP_K]))
            costs.append(gateway.USAGE["cost_usd"] - usage_before)
        elapsed_ms = (time.perf_counter() - start) * 1000.0  # end to end for E7, retrieval only otherwise

        if q.answerable and q.gold_passages:
            g, r = gold_ids_for(q.gold_passages), ranked_gold_ids(retrieved, q.gold_passages)
            gold.append(g)
            ranked.append(r)
            latencies.append(elapsed_ms)
            by_category.setdefault(q.category, ([], []))
            by_category[q.category][0].append(g)
            by_category[q.category][1].append(r)

        if answer is not None:
            if not q.answerable:
                abstentions.append(1.0 if answer.insufficient_evidence else 0.0)
            elif answer.claims:
                citation_precisions.append(sum(c.support_status == "verified" for c in answer.claims) / len(answer.claims))

    out: dict[str, Any] = {
        "description": exp["name"],
        "n_questions": len(gold),
        "recall_at_5": round(recall_at_k(gold, ranked, 5), 4),
        "recall_at_10": round(recall_at_k(gold, ranked, 10), 4),
        "mrr_at_10": round(mrr_at_k(gold, ranked, 10), 4),
        "ndcg_at_10": round(ndcg_at_k(gold, ranked, 10), 4),
        "p50_latency_ms": round(percentile(latencies, 50), 2),
        "p95_latency_ms": round(percentile(latencies, 95), 2),
        "recall_at_10_by_category": {c: round(recall_at_k(g, r, 10), 4) for c, (g, r) in by_category.items()},
    }
    if exp.get("verify"):
        out["citation_precision"] = round(sum(citation_precisions) / len(citation_precisions), 4) if citation_precisions else None
        out["abstention_accuracy"] = round(sum(abstentions) / len(abstentions), 4) if abstentions else None
        out["cost_per_query_usd"] = round(sum(costs) / len(costs), 6) if costs else None
    return out


def run_ablation(
    only_experiments: list[str] | None = None,
    golden_path: str = "data/golden/dev.jsonl",
    results_path: str = "results/results.json",
    corpus_dir: str = "data/corpus",
    session: Session | None = None,
    **ingest_options,
) -> dict[str, Any]:
    """Run the selected experiments on the dev split and merge the numbers into results.json."""
    questions = load_golden_questions(golden_path)
    selected = only_experiments or list(EXPERIMENTS)
    unknown = [e for e in selected if e not in EXPERIMENTS]
    if unknown:
        raise ValueError(f"Unknown experiments {unknown}. Available: {list(EXPERIMENTS)}")

    own_session = session is None
    session = session or new_session()
    try:
        notebooks: dict[tuple[str, bool], str] = {}  # one ingested copy per (chunking, headers) variant
        results: dict[str, Any] = {}
        for exp_id in selected:
            exp = EXPERIMENTS[exp_id]
            variant = (exp["chunking"], exp["headers"])
            if variant not in notebooks:
                notebooks[variant] = ingest_corpus(
                    session, corpus_dir, chunking=exp["chunking"], contextual_headers=exp["headers"], **ingest_options
                )
            results[exp_id] = run_experiment(session, exp, questions, notebooks[variant], "eval_user")
    finally:
        if own_session:
            session.close()

    res_path = Path(results_path)
    data = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    data["timestamp"] = datetime.now(UTC).isoformat()
    data.setdefault("ablations", {}).update(results)
    res_path.parent.mkdir(parents=True, exist_ok=True)
    res_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print_table(results)
    return results


def print_table(results: dict[str, Any]) -> None:
    header = f"{'ID':<5} | {'Architecture':<40} | {'R@5':>6} | {'R@10':>6} | {'MRR@10':>6} | {'nDCG@10':>7} | {'p95 ms':>8}"
    print("\n" + header + "\n" + "-" * len(header))
    for exp_id, r in results.items():
        print(
            f"{exp_id:<5} | {r['description']:<40} | {r['recall_at_5']:>6.3f} | {r['recall_at_10']:>6.3f} | "
            f"{r['mrr_at_10']:>6.3f} | {r['ndcg_at_10']:>7.3f} | {r['p95_latency_ms']:>8.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval ablation experiments")
    parser.add_argument("--only", default=",".join(EXPERIMENTS), help="Comma-separated IDs, e.g. E1,E2,E3")
    parser.add_argument("--golden", default="data/golden/dev.jsonl")
    args = parser.parse_args()
    try:
        run_ablation([e.strip() for e in args.only.split(",") if e.strip()], golden_path=args.golden)
    except (NoCorpusError, gateway.LLMNotConfiguredError) as exc:
        raise SystemExit(f"Cannot run the ablations: {exc}") from exc


if __name__ == "__main__":
    main()
