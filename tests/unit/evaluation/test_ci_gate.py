import json
from pathlib import Path

from packages.evaluation.run_verifier import evaluate_verifier_dataset, save_two_stage
from scripts.check_ci_gate import check_ci_gate


def gate(tmp_path: Path, data: dict) -> bool:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return check_ci_gate(str(path))


def test_passes_when_every_present_metric_meets_target(tmp_path):
    assert gate(tmp_path, {"verifier_two_stage": {"false_acceptance_rate": 0.01}}) is True


def test_fails_when_false_acceptance_misses_the_target(tmp_path):
    # The old gate compared against a baseline of 0.10 and let this through.
    assert gate(tmp_path, {"verifier_two_stage": {"false_acceptance_rate": 0.10}}) is False


def test_fails_when_false_acceptance_is_missing(tmp_path):
    assert gate(tmp_path, {"ablations": {"E3": {"recall_at_10": 0.99}}}) is False


def test_fails_when_recall_is_measured_and_too_low(tmp_path):
    data = {"verifier_two_stage": {"false_acceptance_rate": 0.0}, "ablations": {"E3": {"recall_at_10": 0.60}}}
    assert gate(tmp_path, data) is False


def test_fails_when_results_file_is_missing(tmp_path):
    assert check_ci_gate(str(tmp_path / "nope.json")) is False


def test_evaluate_verifier_dataset_on_real_data():
    results = evaluate_verifier_dataset("data/verifier/dev.jsonl")
    assert "precision" in results
    assert "false_acceptance_rate" in results
    assert results["total_pairs"] > 0


def test_stage_one_alone_does_not_satisfy_the_gate(tmp_path):
    # Stage 1 passes hard negatives on to the LLM stage by design; the target is for the full verifier.
    assert gate(tmp_path, {"verifier": {"false_acceptance_rate": 0.0}}) is False


def test_two_stage_results_are_merged_into_results_json(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"verifier": {"precision": 0.5}}), encoding="utf-8")
    save_two_stage({"false_acceptance_rate": 0.0}, str(path))
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"verifier": {"precision": 0.5}, "verifier_two_stage": {"false_acceptance_rate": 0.0}}
