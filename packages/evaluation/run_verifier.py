"""Verifier benchmark runner on verifier dataset and scientific claim subsets."""

import argparse
import json
from pathlib import Path
from typing import Any

from packages.evaluation.loaders import load_verifier_pairs
from packages.evaluation.metrics import (
    bootstrap_ci,
    calculate_classification_metrics,
    calculate_confusion_matrix,
)
from packages.retrieval.generation import CitationRef, ClaimItem
from packages.verification.pipeline import VerificationPipeline


def evaluate_verifier_dataset(
    dataset_path: str = "data/verifier/dev.jsonl",
    pipeline: VerificationPipeline | None = None,
) -> dict[str, Any]:
    """Run full verification evaluation over labeled pairs."""
    if pipeline is None:
        pipeline = VerificationPipeline()

    pairs = load_verifier_pairs(dataset_path)
    if not pairs:
        print(f"Warning: No verifier pairs found in {dataset_path}")
        return {}

    y_true = []
    y_pred = []

    for pair in pairs:
        y_true.append(pair.gold_label.lower())
        claim = ClaimItem(
            text=pair.claim,
            citations=[
                CitationRef(
                    chunk_id=pair.source_id or "src_1",
                    quote=pair.quote,
                    page_number=1,
                    start_char=0,
                    end_char=len(pair.quote),
                )
            ],
        )
        verified_claim = pipeline.verify_single_claim(claim)
        pred_label = "supports" if verified_claim.support_status == "verified" else (
            "partial" if verified_claim.support_status == "partial" else "unsupported"
        )
        y_pred.append(pred_label)

    metrics = calculate_classification_metrics(y_true, y_pred, positive_label="supports")
    conf_matrix = calculate_confusion_matrix(y_true, y_pred, labels=["supports", "partial", "unsupported"])

    # 95% Bootstrap CI on correct classification
    hits = [1.0 if yt == yp else 0.0 for yt, yp in zip(y_true, y_pred, strict=False)]
    _, (ci_lower, ci_upper) = bootstrap_ci(hits, metric_fn=lambda x: sum(x) / len(x) if x else 0.0)

    results = {
        "total_pairs": len(pairs),
        "precision": round(metrics["precision"], 4),
        "recall": round(metrics["recall"], 4),
        "f1": round(metrics["f1"], 4),
        "false_acceptance_rate": round(metrics["false_acceptance_rate"], 4),
        "false_rejection_rate": round(metrics["false_rejection_rate"], 4),
        "bootstrap_95_ci": [round(ci_lower, 4), round(ci_upper, 4)],
        "confusion_matrix": conf_matrix,
    }

    return results


def save_two_stage(results: dict[str, Any], output_path: str = "results/results.json") -> None:
    """Store the two-stage numbers next to what the other eval runners wrote."""
    out_file = Path(output_path)
    data = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    data["verifier_two_stage"] = results
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run verifier benchmark")
    parser.add_argument("--data", default="data/verifier/dev.jsonl", help="Path to verifier JSONL")
    parser.add_argument("--out", default="results/results.json", help="results.json to merge the numbers into")
    args = parser.parse_args()

    results = evaluate_verifier_dataset(args.data)
    print("\n" + "=" * 65)
    print("VERIFIER PERFORMANCE BENCHMARK")
    print("=" * 65)
    for k, v in results.items():
        if k != "confusion_matrix":
            print(f"{k:<25}: {v}")
    print("\nConfusion Matrix (Actual Rows x Predicted Cols):")
    print(json.dumps(results.get("confusion_matrix", {}), indent=2))
    print("=" * 65 + "\n")

    if results:
        save_two_stage(results, args.out)


if __name__ == "__main__":
    main()
