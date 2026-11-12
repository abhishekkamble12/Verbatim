import json

from packages.retrieval.generation import (
    GroundedAnswerResponse,
    generate_grounded_answer,
)


def test_grounded_answer_quote_and_page_resolution():
    """Verify system resolves quote and page from chunk_id and populates them into citation."""
    chunks = [
        {
            "id": "chunk_42",
            "text": "The study demonstrated a 14.2% increase in throughput.",
            "page_number": 3,
            "start_char": 120,
            "end_char": 174,
        }
    ]

    def fake_llm(prompt: str, model: str):
        payload = {
            "answer": "Throughput increased by 14.2% in the study.",
            "claims": [
                {
                    "text": "Throughput increased by 14.2% in the study.",
                    "citations": [{"chunk_id": "chunk_42"}],
                    "support_status": "pending",
                }
            ],
            "insufficient_evidence": False,
        }
        return {"text": json.dumps(payload), "prompt_tokens": 100, "completion_tokens": 40}

    response = generate_grounded_answer(
        query="What happened to throughput?",
        retrieved_chunks=chunks,
        provider_fn=fake_llm,
    )

    assert isinstance(response, GroundedAnswerResponse)
    assert response.insufficient_evidence is False
    assert len(response.claims) == 1
    citation = response.claims[0].citations[0]
    assert citation.chunk_id == "chunk_42"
    assert citation.quote == "The study demonstrated a 14.2% increase in throughput."
    assert citation.page_number == 3
    assert citation.start_char == 120
    assert citation.end_char == 174


def test_hallucinated_chunk_id_rejected():
    """Verify that a hallucinated chunk_id not present in retrieved evidence is rejected."""
    chunks = [
        {
            "id": "chunk_10",
            "text": "Valid text from source.",
            "page_number": 1,
            "start_char": 0,
            "end_char": 23,
        }
    ]

    def fake_llm_hallucinating(prompt: str, model: str):
        payload = {
            "answer": "Fabricated claim citing non-existent chunk.",
            "claims": [
                {
                    "text": "Fabricated claim citing non-existent chunk.",
                    "citations": [{"chunk_id": "chunk_hallucinated_999"}],
                    "support_status": "pending",
                }
            ],
            "insufficient_evidence": False,
        }
        return {"text": json.dumps(payload), "prompt_tokens": 50, "completion_tokens": 30}

    response = generate_grounded_answer(
        query="Explain something not in chunks",
        retrieved_chunks=chunks,
        provider_fn=fake_llm_hallucinating,
    )

    # Hallucinated citation must be rejected
    assert len(response.claims) == 1
    claim = response.claims[0]
    assert claim.support_status == "rejected"
    assert "hallucinated" in claim.rejection_reason.lower()


def test_abstention_on_insufficient_evidence():
    """Verify that when evidence is missing or insufficient, system abstains with 'The sources do not say.'"""
    def fake_llm_abstain(prompt: str, model: str):
        payload = {
            "answer": "The sources do not say.",
            "claims": [],
            "insufficient_evidence": True,
        }
        return {"text": json.dumps(payload), "prompt_tokens": 50, "completion_tokens": 15}

    response = generate_grounded_answer(
        query="What is the CEO's favorite sport?",
        retrieved_chunks=[{"id": "c1", "text": "Operating revenue grew 5%.", "page_number": 1, "start_char": 0, "end_char": 25}],
        provider_fn=fake_llm_abstain,
    )

    assert response.insufficient_evidence is True
    assert "sources do not say" in response.answer.lower()
    assert len(response.claims) == 0


def test_invalid_json_retry_and_clean_failure():
    """Verify retry logic on malformed JSON from LLM."""
    call_count = 0

    def fake_llm_malformed(prompt: str, model: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"text": "NOT A JSON STRING", "prompt_tokens": 20, "completion_tokens": 10}
        # On retry, return valid JSON
        payload = {
            "answer": "The sources do not say.",
            "claims": [],
            "insufficient_evidence": True,
        }
        return {"text": json.dumps(payload), "prompt_tokens": 30, "completion_tokens": 15}

    response = generate_grounded_answer(
        query="What happened?",
        retrieved_chunks=[{"id": "c1", "text": "Some text", "page_number": 1, "start_char": 0, "end_char": 9}],
        provider_fn=fake_llm_malformed,
    )

    assert call_count == 2
    assert response.insufficient_evidence is True


def test_wrong_shape_json_abstains_instead_of_raising():
    """Valid JSON missing required fields must abstain, not crash the API with a 500."""
    chunks = [{"id": "c1", "text": "Some evidence."}]
    result = generate_grounded_answer(
        query="q",
        retrieved_chunks=chunks,
        provider_fn=lambda prompt, model: {"text": '{"claims": [{"citations": []}]}'},
    )
    assert result.insufficient_evidence is True
