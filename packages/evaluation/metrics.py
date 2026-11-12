"""Evaluation metrics for retrieval, claim verification, and statistical confidence intervals."""

import math
import random
from collections.abc import Callable
from typing import Any


def recall_at_k(queries_gold: list[list[str]], queries_retrieved: list[list[str]], k: int) -> float:
    """Mean Recall@k across queries.

    Fraction of gold passages retrieved in top-k for each query.
    """
    if not queries_gold:
        return 0.0

    recalls = []
    for gold, retrieved in zip(queries_gold, queries_retrieved, strict=False):
        gold_set = set(gold)
        if not gold_set:
            continue
        retrieved_k = set(retrieved[:k])
        hits = len(gold_set.intersection(retrieved_k))
        recalls.append(hits / len(gold_set))

    return sum(recalls) / len(recalls) if recalls else 0.0


def mrr_at_k(queries_gold: list[list[str]], queries_retrieved: list[list[str]], k: int) -> float:
    """Mean Reciprocal Rank @ k.

    1 / rank of the first relevant document if within top-k, else 0.
    """
    if not queries_gold:
        return 0.0

    reciprocal_ranks = []
    for gold, retrieved in zip(queries_gold, queries_retrieved, strict=False):
        gold_set = set(gold)
        rr = 0.0
        for rank, item in enumerate(retrieved[:k], start=1):
            if item in gold_set:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0


def ndcg_at_k(queries_gold: list[list[str]], queries_retrieved: list[list[str]], k: int) -> float:
    """Normalized Discounted Cumulative Gain @ k for binary relevance."""
    if not queries_gold:
        return 0.0

    ndcg_scores = []
    for gold, retrieved in zip(queries_gold, queries_retrieved, strict=False):
        gold_set = set(gold)
        if not gold_set:
            continue

        # Calculate DCG@k
        dcg = 0.0
        for rank, item in enumerate(retrieved[:k], start=1):
            if item in gold_set:
                dcg += 1.0 / math.log2(rank + 1)

        # Calculate IDCG@k (ideal DCG if all relevant items were ranked first)
        ideal_hits = min(len(gold_set), k)
        idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))

        if idcg == 0.0:
            ndcg_scores.append(0.0)
        else:
            ndcg_scores.append(dcg / idcg)

    return sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0


def calculate_classification_metrics(
    y_true: list[str],
    y_pred: list[str],
    positive_label: str = "supports",
) -> dict[str, float]:
    """Compute precision, recall, F1, false acceptance rate, and false rejection rate."""
    tp = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == positive_label and yp == positive_label)
    fp = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt != positive_label and yp == positive_label)
    fn = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == positive_label and yp != positive_label)
    tn = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt != positive_label and yp != positive_label)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    # False Acceptance Rate: proportion of negative samples falsely accepted as positive
    false_acceptance_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    # False Rejection Rate: proportion of positive samples falsely rejected
    false_rejection_rate = fn / (tp + fn) if (tp + fn) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_acceptance_rate": false_acceptance_rate,
        "false_rejection_rate": false_rejection_rate,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def calculate_confusion_matrix(
    y_true: list[str],
    y_pred: list[str],
    labels: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Compute multi-class confusion matrix as nested dict: matrix[actual][predicted]."""
    if labels is None:
        labels = sorted(set(y_true).union(set(y_pred)))

    matrix = {actual: dict.fromkeys(labels, 0) for actual in labels}
    for yt, yp in zip(y_true, y_pred, strict=False):
        if yt in matrix and yp in matrix[yt]:
            matrix[yt][yp] += 1

    return matrix


def bootstrap_ci(
    data: list[Any],
    metric_fn: Callable[[list[Any]], float],
    n_bootstraps: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, tuple[float, float]]:
    """Calculate point estimate and bootstrap confidence interval (lower, upper)."""
    if not data:
        return 0.0, (0.0, 0.0)

    point_estimate = metric_fn(data)
    rng = random.Random(seed)
    n = len(data)

    bootstrap_scores = []
    for _ in range(n_bootstraps):
        sample = [rng.choice(data) for _ in range(n)]
        bootstrap_scores.append(metric_fn(sample))

    bootstrap_scores.sort()
    alpha = (1.0 - ci) / 2.0
    lower_idx = int(alpha * n_bootstraps)
    upper_idx = int((1.0 - alpha) * n_bootstraps) - 1

    ci_lower = bootstrap_scores[max(0, lower_idx)]
    ci_upper = bootstrap_scores[min(n_bootstraps - 1, upper_idx)]

    return point_estimate, (ci_lower, ci_upper)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (pct in 0-100). Returns 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]
