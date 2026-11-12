import math

import pytest

from packages.evaluation.metrics import (
    bootstrap_ci,
    calculate_classification_metrics,
    calculate_confusion_matrix,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)


def test_recall_at_k_hand_computed():
    # Query 1: 1 of 2 gold retrieved in top-2 -> 0.5
    # Query 2: 1 of 1 gold retrieved in top-2 -> 1.0
    queries_gold = [["c1", "c2"], ["c2"]]
    queries_retrieved = [["c1", "c3", "c4"], ["c3", "c2"]]

    score = recall_at_k(queries_gold, queries_retrieved, k=2)
    assert score == pytest.approx(0.75, rel=1e-4)


def test_mrr_at_k_hand_computed():
    # Query 1: first gold at rank 2 -> RR = 0.5
    # Query 2: no gold in top-3 -> RR = 0.0
    queries_gold = [["c2"], ["c5"]]
    queries_retrieved = [["c1", "c2", "c3"], ["c1", "c2", "c3"]]

    score = mrr_at_k(queries_gold, queries_retrieved, k=3)
    assert score == pytest.approx(0.25, rel=1e-4)


def test_ndcg_at_k_hand_computed():
    # Gold: c2, c3
    # Retrieved: c1, c2, c3 -> rel: [0, 1, 1]
    # DCG@3 = 0/log2(2) + 1/log2(3) + 1/log2(4) = 1/1.5849625 + 0.5 = 1.13092975
    # IDCG@3 = 1/log2(2) + 1/log2(3) = 1.63092975
    # NDCG@3 = 1.13092975 / 1.63092975 ≈ 0.693426
    expected_dcg = (1.0 / math.log2(3)) + (1.0 / math.log2(4))
    expected_idcg = 1.0 + (1.0 / math.log2(3))
    expected_ndcg = expected_dcg / expected_idcg

    queries_gold = [["c2", "c3"]]
    queries_retrieved = [["c1", "c2", "c3"]]

    score = ndcg_at_k(queries_gold, queries_retrieved, k=3)
    assert score == pytest.approx(expected_ndcg, rel=1e-4)


def test_classification_metrics_hand_computed():
    # TP=1, FN=1, FP=1, TN=1
    y_true = ["supports", "supports", "unsupported", "unsupported"]
    y_pred = ["supports", "unsupported", "supports", "unsupported"]

    metrics = calculate_classification_metrics(y_true, y_pred, positive_label="supports")
    assert metrics["precision"] == pytest.approx(0.5)
    assert metrics["recall"] == pytest.approx(0.5)
    assert metrics["f1"] == pytest.approx(0.5)
    assert metrics["false_acceptance_rate"] == pytest.approx(0.5)
    assert metrics["false_rejection_rate"] == pytest.approx(0.5)


def test_confusion_matrix_hand_computed():
    y_true = ["supports", "partial", "unsupported"]
    y_pred = ["supports", "unsupported", "unsupported"]
    labels = ["supports", "partial", "unsupported"]

    cm = calculate_confusion_matrix(y_true, y_pred, labels=labels)
    assert cm["supports"]["supports"] == 1
    assert cm["partial"]["unsupported"] == 1
    assert cm["unsupported"]["unsupported"] == 1
    assert cm["supports"]["unsupported"] == 0


def test_bootstrap_ci_constant():
    data = [0.8, 0.8, 0.8, 0.8, 0.8]
    point_est, (ci_lower, ci_upper) = bootstrap_ci(data, metric_fn=lambda x: sum(x) / len(x), n_bootstraps=100)
    assert point_est == pytest.approx(0.8)
    assert ci_lower == pytest.approx(0.8)
    assert ci_upper == pytest.approx(0.8)
