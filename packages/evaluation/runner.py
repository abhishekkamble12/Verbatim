"""`make eval` part 1: dataset statistics and the claim verifier on data/verifier/.

This needs no database and no LLM. It runs only the deterministic stage 1 verifier (the part that
gates false acceptance in CI). Retrieval numbers come from run_ablation, agent numbers from run_agent;
nothing here pretends to measure them.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from packages.evaluation.loaders import load_golden_questions, load_verifier_pairs
from packages.evaluation.metrics import (
    bootstrap_ci,
    calculate_classification_metrics,
    calculate_confusion_matrix,
)
from packages.verification.fuzzy import verify_claim_against_quote

LABELS = ["supports", "partial", "unsupported"]


def run_evaluation(
    golden_path: str = "data/golden/dev.jsonl",
    verifier_path: str = "data/verifier/dev.jsonl",
    output_path: str = "results/results.json",
) -> dict:
    golden_questions = load_golden_questions(golden_path)
    verifier_pairs = load_verifier_pairs(verifier_path)

    y_true = [p.gold_label.lower() for p in verifier_pairs]
    y_pred = [verify_claim_against_quote(p.claim, p.quote).verdict.value.lower() for p in verifier_pairs]

    metrics = calculate_classification_metrics(y_true, y_pred, positive_label="supports")
    hits = [1.0 if t == p else 0.0 for t, p in zip(y_true, y_pred, strict=True)]
    _, (ci_low, ci_high) = bootstrap_ci(hits, metric_fn=lambda x: sum(x) / len(x), n_bootstraps=500)

    categories: dict[str, int] = {}
    for q in golden_questions:
        categories[q.category] = categories.get(q.category, 0) + 1

    out_file = Path(output_path)
    results = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    # Replace what this runner owns, keep what the ablation and agent runners wrote.
    results.pop("retrieval", None)
    results.update(
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": {"total_golden_questions": len(golden_questions), "total_verifier_pairs": len(verifier_pairs)},
            "verifier": {
                "scope": "stage 1 deterministic check only",
                "precision": round(metrics["precision"], 4),
                "recall": round(metrics["recall"], 4),
                "f1": round(metrics["f1"], 4),
                "false_acceptance_rate": round(metrics["false_acceptance_rate"], 4),
                "false_rejection_rate": round(metrics["false_rejection_rate"], 4),
                "accuracy_ci_95": [round(ci_low, 4), round(ci_high, 4)],
                "confusion_matrix": calculate_confusion_matrix(y_true, y_pred, labels=LABELS),
            },
            "categories": categories,
        }
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Evaluation complete. Results written to {output_path}")
    return results


if __name__ == "__main__":
    run_evaluation()
