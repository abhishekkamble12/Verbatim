from pathlib import Path

from packages.evaluation.loaders import load_golden_questions, load_verifier_pairs
from packages.evaluation.runner import run_evaluation


def test_load_golden_questions(tmp_path: Path):
    file = tmp_path / "test_golden.jsonl"
    file.write_text(
        '{"id": "q1", "question": "test q?", "category": "factual", "expected_answer": "ans", "gold_passages": ["p1"]}\n',
        encoding="utf-8",
    )
    loaded = load_golden_questions(file)
    assert len(loaded) == 1
    assert loaded[0].id == "q1"
    assert loaded[0].category == "factual"


def test_load_verifier_pairs(tmp_path: Path):
    file = tmp_path / "test_verifier.jsonl"
    file.write_text(
        '{"id": "v1", "claim": "revenue rose 10%", "quote": "revenue rose 10%", "gold_label": "supports"}\n',
        encoding="utf-8",
    )
    loaded = load_verifier_pairs(file)
    assert len(loaded) == 1
    assert loaded[0].id == "v1"
    assert loaded[0].gold_label == "supports"


def test_run_evaluation(tmp_path: Path):
    golden_file = tmp_path / "golden.jsonl"
    verifier_file = tmp_path / "verifier.jsonl"
    results_file = tmp_path / "results.json"

    golden_file.write_text(
        '{"id": "q1", "question": "q?", "category": "numerical", "expected_answer": "10%", "gold_chunk_ids": ["c1"]}\n',
        encoding="utf-8",
    )
    verifier_file.write_text(
        '{"id": "v1", "claim": "profit grew 5%", "quote": "profit grew 5%", "gold_label": "supports"}\n',
        encoding="utf-8",
    )

    results = run_evaluation(
        golden_path=str(golden_file),
        verifier_path=str(verifier_file),
        output_path=str(results_file),
    )
    assert results_file.exists()
    assert results["verifier"]["precision"] == 1.0
    assert results["summary"]["total_golden_questions"] == 1
