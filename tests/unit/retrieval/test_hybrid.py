import pytest

from packages.retrieval.hybrid import apply_rrf_fusion, build_contextual_header


def test_rrf_fusion_hand_computed():
    """Verify RRF fusion on a hand-computed example with k=60.

    Doc A: rank 1 (dense), rank 2 (sparse) -> 1/61 + 1/62 = 0.01639344 + 0.01612903 = 0.03252247
    Doc B: rank 2 (dense), not in sparse   -> 1/62 = 0.01612903
    Doc C: not in dense, rank 1 (sparse)   -> 1/61 = 0.01639344
    Ranking order should be: Doc A > Doc C > Doc B
    """
    dense_ranking = ["doc_A", "doc_B"]
    sparse_ranking = ["doc_C", "doc_A"]

    scores = apply_rrf_fusion(rankings=[dense_ranking, sparse_ranking], k=60)

    expected_score_a = (1.0 / 61) + (1.0 / 62)
    expected_score_c = 1.0 / 61
    expected_score_b = 1.0 / 62

    assert scores["doc_A"] == pytest.approx(expected_score_a, rel=1e-5)
    assert scores["doc_C"] == pytest.approx(expected_score_c, rel=1e-5)
    assert scores["doc_B"] == pytest.approx(expected_score_b, rel=1e-5)

    sorted_docs = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)
    assert sorted_docs == ["doc_A", "doc_C", "doc_B"]


def test_build_contextual_header():
    """Verify contextual header formatting: 'doc title > section > chunk text'."""
    header = build_contextual_header(
        doc_title="Q3 2024 Shareholder Report",
        section="Capital Allocation",
        chunk_text="Capex increased by $120M in North America.",
    )
    assert header == "Q3 2024 Shareholder Report > Capital Allocation > Capex increased by $120M in North America."


