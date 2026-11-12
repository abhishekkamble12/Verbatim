import json

import pymupdf
import pytest

from packages.evaluation.corpus import ingest_corpus
from packages.evaluation.run_agent import compute_correctness, run_agent_benchmark


def test_compute_correctness():
    pred = "The operating margin contracted from 18% to 15.5% after the Company B acquisition."
    gold = "Following the 2021 acquisition of Company B, operating margin contracted from 18% to 15.5% by 2023."
    assert compute_correctness(pred, gold) > 0.5


@pytest.mark.parametrize("pred,gold,expected", [("", "x", 0.0), ("something", "", 0.0)])
def test_correctness_empty_inputs(pred, gold, expected):
    assert compute_correctness(pred, gold) == expected


def test_agent_benchmark_reports_measured_numbers(db_session, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    sentence = "Voyager 1 launched on September 5, 1977 and crossed the heliopause in 2012."
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 750), sentence, fontsize=10)
    doc.save(str(corpus / "voyager.pdf"))
    doc.close()

    rows = [
        {
            "id": "q1",
            "question": "When did Voyager 1 launch and cross the heliopause?",
            "category": "multi-hop",
            "expected_answer": "Launched 1977, heliopause 2012.",
            "gold_passages": [sentence],
            "answerable": True,
        },
        {
            "id": "q2",
            "question": "What is the capital of Atlantis?",
            "category": "unanswerable",
            "expected_answer": "The sources do not say.",
            "gold_passages": [],
            "answerable": False,
        },
    ]
    golden = tmp_path / "golden.jsonl"
    golden.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    notebook = ingest_corpus(db_session, str(corpus))
    out = tmp_path / "results.json"

    summary = run_agent_benchmark(db_session, notebook, str(golden), str(out))

    e7, e8 = summary["single_shot_e7"], summary["report_agent_e8"]
    assert summary["n_questions"] == 1 and summary["n_unanswerable"] == 1
    assert e7["avg_steps"] == 1.0
    assert e8["avg_steps"] >= 4  # PLAN, at least one RESEARCH, COMPOSE, DONE
    assert e8["avg_llm_calls"] >= 3  # plan + draft + entailment: verification calls are counted
    assert e8["cost_per_answer_usd"] > 0 and e7["cost_per_answer_usd"] > 0
    assert e8["recall_at_10"] == 1.0
    assert json.loads(out.read_text(encoding="utf-8"))["agent_benchmark"] == summary
