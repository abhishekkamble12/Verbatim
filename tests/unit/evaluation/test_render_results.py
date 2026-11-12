from pathlib import Path

from scripts.render_results import END_MARKER, START_MARKER, format_results_markdown, render_to_file


def test_format_results_markdown():
    data = {
        "timestamp": "2026-11-07T12:00:00Z",
        "summary": {"total_golden_questions": 10, "total_verifier_pairs": 20},
        "verifier": {"precision": 0.5, "recall": 1.0, "false_acceptance_rate": 0.4},
        "verifier_two_stage": {
            "precision": 0.96,
            "recall": 0.80,
            "f1": 0.87,
            "false_acceptance_rate": 0.015,
            "false_rejection_rate": 0.2,
            "bootstrap_95_ci": [0.90, 0.98],
        },
        "categories": {"factual": 6, "numerical": 4},
    }
    markdown = format_results_markdown(data)
    assert START_MARKER in markdown and END_MARKER in markdown
    assert "| Precision | 0.9600 | >= 0.9500 | PASS |" in markdown
    assert "| False acceptance rate | 0.0150 | <= 0.0200 | PASS |" in markdown
    assert "| Recall | 0.8000 | >= 0.8500 | FAIL |" in markdown  # used to print PASS whatever the value
    assert "| Accuracy 95% CI (bootstrap) | [0.9000, 0.9800] |" in markdown
    assert "| 0.5000 | 1.0000 | 0.4000 |" in markdown and "0.5000 | >=" not in markdown  # stage 1 alone has no target
    assert markdown.count("Not measured yet") == 2  # ablations and agent: no data, no numbers


def test_ablation_and_agent_numbers_come_from_results():
    data = {
        "ablations": {
            "E3": {
                "description": "hybrid",
                "recall_at_5": 0.5,
                "recall_at_10": 0.7,
                "mrr_at_10": 0.4,
                "ndcg_at_10": 0.45,
                "p95_latency_ms": 12.3,
            }
        },
        "agent_benchmark": {
            "n_questions": 3,
            "single_shot_e7": {"system": "E7", "avg_steps": 1.0},
            "report_agent_e8": {"system": "E8", "avg_steps": 6.0, "cost_per_answer_usd": 0.0012},
        },
    }
    markdown = format_results_markdown(data)
    assert "| E3 | hybrid | 0.5000 | 0.7000 |" in markdown
    assert "0.001200" in markdown and "Not measured yet" not in markdown


def test_render_to_file(tmp_path: Path):
    doc = tmp_path / "TEST_DOC.md"
    doc.write_text(f"Header\n{START_MARKER}\nOld Table\n{END_MARKER}\nFooter\n", encoding="utf-8")
    block = START_MARKER + "\nNew \\1 Table\n" + END_MARKER  # a backslash in the block must survive
    assert render_to_file(doc, block) is True
    updated = doc.read_text(encoding="utf-8")
    assert "New \\1 Table" in updated and "Old Table" not in updated and "Footer" in updated


def test_small_samples_are_flagged():
    small = format_results_markdown({"summary": {"total_golden_questions": 12, "total_verifier_pairs": 15}})
    assert "Small sample" in small
    big = format_results_markdown({"summary": {"total_golden_questions": 60, "total_verifier_pairs": 200}})
    assert "Small sample" not in big
