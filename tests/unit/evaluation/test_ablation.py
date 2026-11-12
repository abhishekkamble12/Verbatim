"""Ablation runner on real Postgres with a tiny real corpus (PDFs generated in tmp)."""

import json

import pymupdf
import pytest

from packages.evaluation.corpus import NoCorpusError, ranked_gold_ids
from packages.evaluation.metrics import percentile
from packages.evaluation.run_ablation import run_ablation

REVENUE = "Consolidated revenues grew by 14.2% in the third quarter."
MARGIN = "Operating margin reached 18.5% because of cloud efficiencies."


def write_pdf(path, text):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text, fontsize=10)
    doc.save(str(path))
    doc.close()


@pytest.fixture
def corpus(tmp_path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    write_pdf(folder / "finance.pdf", f"{REVENUE} {MARGIN}")
    write_pdf(folder / "canteen.pdf", "The cafeteria serves soup every Tuesday and fruit on Fridays.")
    return folder


@pytest.fixture
def golden(tmp_path):
    rows = [
        {
            "id": "q1",
            "question": "How much did consolidated revenues grow?",
            "category": "numerical",
            "expected_answer": "14.2%",
            "gold_passages": [REVENUE],
            "answerable": True,
        },
        {
            "id": "q2",
            "question": "What was the operating margin?",
            "category": "numerical",
            "expected_answer": "18.5%",
            "gold_passages": [MARGIN],
            "answerable": True,
        },
        {
            "id": "q3",
            "question": "Who won the football world cup?",
            "category": "unanswerable",
            "expected_answer": "The sources do not say.",
            "gold_passages": [],
            "answerable": False,
        },
    ]
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def test_ablation_measures_real_retrieval(db_session, corpus, golden, tmp_path):
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({"verifier": {"false_acceptance_rate": 0.0}}), encoding="utf-8")

    results = run_ablation(["E1", "E3", "E7"], str(golden), str(results_file), str(corpus), session=db_session)

    e3 = results["E3"]
    assert e3["n_questions"] == 2
    assert e3["recall_at_10"] == 1.0  # full-text finds both exact sentences
    assert e3["recall_at_10_by_category"] == {"numerical": 1.0}
    assert results["E7"]["abstention_accuracy"] is not None
    assert results["E7"]["cost_per_query_usd"] is not None
    assert "cost_per_query_usd" not in results["E3"]  # retrieval-only runs report no invented cost

    saved = json.loads(results_file.read_text(encoding="utf-8"))
    assert saved["verifier"] == {"false_acceptance_rate": 0.0}  # other runners' numbers survive
    assert set(saved["ablations"]) == {"E1", "E3", "E7"}


def test_ablation_refuses_to_run_without_corpus(db_session, golden, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(NoCorpusError):
        run_ablation(["E3"], str(golden), str(tmp_path / "r.json"), str(empty), session=db_session)
    assert not (tmp_path / "r.json").exists()


def test_relevance_is_judged_by_gold_passage_not_by_id():
    chunks = [{"id": "c9", "text": "x"}, {"id": "c2", "text": "The  Revenue   grew 5%."}]
    assert ranked_gold_ids(chunks, ["revenue grew 5%"]) == ["c9", "gold-0"]


def test_percentile_nearest_rank():
    assert percentile([10, 20, 30, 40], 50) == 20
    assert percentile([10, 20, 30, 40], 95) == 40
    assert percentile([], 95) == 0.0


def test_e7_retrieves_ten_for_recall_and_answers_from_five_like_the_api(monkeypatch):
    from packages.evaluation import run_ablation as mod
    from packages.evaluation.loaders import GoldenQuestion
    from packages.retrieval.generation import GroundedAnswerResponse

    seen = {}

    def fake_retrieve(session, question, user_id, notebook_id, config):
        seen["top_k"] = config.top_k
        return [{"id": f"c{i}", "text": f"chunk {i}"} for i in range(config.top_k)]

    def fake_generate(question, chunks):
        seen["answered_from"] = len(chunks)
        return GroundedAnswerResponse(answer="The sources do not say.", claims=[], insufficient_evidence=True)

    monkeypatch.setattr(mod, "hybrid_retrieve", fake_retrieve)
    monkeypatch.setattr(mod, "generate_grounded_answer", fake_generate)
    q = GoldenQuestion(id="q", question="?", category="unanswerable", expected_answer="", gold_passages=[], answerable=False)
    mod.run_experiment(None, mod.EXPERIMENTS["E7"], [q], "nb", "u")
    assert seen == {"top_k": 10, "answered_from": 5}
