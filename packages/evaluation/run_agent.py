"""E8: single-shot grounded chat (E7) vs the bounded Report Agent, on the real corpus.

Everything reported is measured in the run: latency from the clock, tokens and cost from the gateway's
usage meter, retrieved chunks from the agent's own trace. `answer_keyword_coverage` is a rough proxy
(share of the expected answer's longer words that appear in the output), not a human correctness score.

    python -m packages.evaluation.run_agent
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from packages.agent.report_agent import ReportAgent
from packages.evaluation.corpus import NoCorpusError, gold_ids_for, ingest_corpus, ranked_gold_ids
from packages.evaluation.loaders import load_golden_questions
from packages.evaluation.metrics import mrr_at_k, percentile, recall_at_k
from packages.llm_gateway import gateway
from packages.retrieval.db import new_session
from packages.retrieval.generation import generate_grounded_answer
from packages.retrieval.hybrid import RetrievalConfig, hybrid_retrieve
from packages.verification.pipeline import verify_grounded_answer

EVAL_USER = "eval_user"
SHORT_WORDS = {"with", "that", "from", "were", "been", "have", "this"}


def compute_correctness(predicted_text: str, expected_answer: str) -> float:
    """Share of the expected answer's keywords found in the prediction (proxy, 0-1)."""
    if not predicted_text or not expected_answer:
        return 0.0
    pred = predicted_text.lower()
    keywords = [
        w.strip(".,;:?!'\"()[]$")
        for w in expected_answer.lower().split()
        if len(w) > 3 and w not in SHORT_WORDS
    ]
    if not keywords:
        return 1.0 if expected_answer.lower() in pred else 0.0
    return round(sum(kw in pred for kw in keywords) / len(keywords), 4)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _measure(fn) -> tuple[Any, float, dict[str, float]]:
    """Run fn() and return (result, elapsed_ms, usage delta)."""
    before = dict(gateway.USAGE)
    start = time.perf_counter()
    result = fn()
    elapsed = (time.perf_counter() - start) * 1000.0
    return result, elapsed, {k: gateway.USAGE[k] - before[k] for k in before}


def run_agent_benchmark(
    session: Session,
    notebook_id: str,
    golden_path: str = "data/golden/dev.jsonl",
    results_path: str = "results/results.json",
    categories: tuple[str, ...] = ("multi-hop", "comparative", "multi-document"),
) -> dict[str, Any]:
    questions = load_golden_questions(golden_path)
    target = [q for q in questions if q.category in categories and q.answerable]
    unanswerable = [q for q in questions if not q.answerable]
    config = RetrievalConfig(top_k=5)

    def single_shot(question: str):
        retrieved = hybrid_retrieve(session, question, EVAL_USER, notebook_id, config)
        return retrieved, verify_grounded_answer(generate_grounded_answer(question, retrieved))

    def agent_run(question: str):
        agent = ReportAgent(retrieve_fn=lambda q: hybrid_retrieve(session, q, EVAL_USER, notebook_id, RetrievalConfig(top_k=3)))
        return agent.run(question)

    e7: dict[str, list[float]] = {"coverage": [], "claim_rate": [], "latency": [], "cost": []}
    e8: dict[str, list[float]] = {"coverage": [], "claim_rate": [], "latency": [], "cost": [], "steps": [],
                                  "retries": [], "budget_stop": [], "llm_calls": []}
    gold, e7_ranked, e8_ranked = [], [], []

    for q in target:
        (retrieved, answer), ms, used = _measure(lambda q=q: single_shot(q.question))
        e7["coverage"].append(compute_correctness(answer.answer, q.expected_answer))
        e7["claim_rate"].append(sum(c.support_status == "verified" for c in answer.claims) / len(answer.claims) if answer.claims else 0.0)
        e7["latency"].append(ms)
        e7["cost"].append(used["cost_usd"])

        result, ms, used = _measure(lambda q=q: agent_run(q.question))
        e8["coverage"].append(compute_correctness(result.report_markdown, q.expected_answer))
        e8["claim_rate"].append(len(result.verified_claims) / result.drafted_claim_count if result.drafted_claim_count else 0.0)
        e8["latency"].append(ms)
        e8["cost"].append(used["cost_usd"])
        e8["steps"].append(len(result.trace))
        e8["retries"].append(result.total_retries)
        e8["budget_stop"].append(1.0 if result.is_partial else 0.0)
        e8["llm_calls"].append(result.llm_call_count)

        gold.append(gold_ids_for(q.gold_passages))
        e7_ranked.append(ranked_gold_ids(retrieved, q.gold_passages))
        e8_ranked.append(ranked_gold_ids([{"id": cid, "text": _chunk_text(session, cid)} for cid in result.retrieved_chunk_ids], q.gold_passages))

    # Abstention: on questions the documents cannot answer, did each system say so?
    e7_abstain = [1.0 if single_shot(q.question)[1].insufficient_evidence else 0.0 for q in unanswerable]
    e8_abstain = [1.0 if not agent_run(q.question).verified_claims else 0.0 for q in unanswerable]

    summary = {
        "n_questions": len(target),
        "n_unanswerable": len(unanswerable),
        "single_shot_e7": {
            "system": "E7 Single-Shot Grounded Chat",
            "answer_keyword_coverage": _mean(e7["coverage"]),
            "verified_claim_rate": _mean(e7["claim_rate"]),
            "abstention_accuracy": _mean(e7_abstain),
            "avg_steps": 1.0,
            "p95_latency_ms": round(percentile(e7["latency"], 95), 2),
            "cost_per_answer_usd": round(_mean(e7["cost"]), 6),
            "recall_at_10": round(recall_at_k(gold, e7_ranked, 10), 4),
            "mrr_at_10": round(mrr_at_k(gold, e7_ranked, 10), 4),
        },
        "report_agent_e8": {
            "system": "E8 Report Agent",
            "answer_keyword_coverage": _mean(e8["coverage"]),
            "verified_claim_rate": _mean(e8["claim_rate"]),
            "abstention_accuracy": _mean(e8_abstain),
            "avg_steps": round(_mean(e8["steps"]), 1),
            "avg_llm_calls": round(_mean(e8["llm_calls"]), 1),
            "retries": round(_mean(e8["retries"]), 2),
            "budget_stop_rate": _mean(e8["budget_stop"]),
            "p95_latency_ms": round(percentile(e8["latency"], 95), 2),
            "cost_per_answer_usd": round(_mean(e8["cost"]), 6),
            "recall_at_10": round(recall_at_k(gold, e8_ranked, 10), 4),
            "mrr_at_10": round(mrr_at_k(gold, e8_ranked, 10), 4),
        },
    }

    res_path = Path(results_path)
    data = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    data["timestamp"] = datetime.now(UTC).isoformat()
    data["agent_benchmark"] = summary
    res_path.parent.mkdir(parents=True, exist_ok=True)
    res_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return summary


def _chunk_text(session: Session, chunk_id: str) -> str:
    from packages.retrieval.models import Chunk

    chunk = session.get(Chunk, chunk_id)
    return chunk.text if chunk else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run E7 vs E8 agent benchmark")
    parser.add_argument("--golden", default="data/golden/dev.jsonl")
    args = parser.parse_args()
    session = new_session()
    try:
        notebook_id = ingest_corpus(session)
        summary = run_agent_benchmark(session, notebook_id, golden_path=args.golden)
    except (NoCorpusError, gateway.LLMNotConfiguredError) as exc:
        raise SystemExit(f"Cannot run the agent benchmark: {exc}") from exc
    finally:
        session.close()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
