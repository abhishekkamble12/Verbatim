from packages.retrieval.generation import CitationRef, ClaimItem, GroundedAnswerResponse
from packages.verification.pipeline import VerificationPipeline


def test_pipeline_pass_path():
    """Verify that a claim passing Stage 1 and Stage 2 entailment is marked verified."""
    claim = ClaimItem(
        text="Operating revenues expanded by 14.2% year-over-year.",
        citations=[
            CitationRef(
                chunk_id="chk_1",
                quote="In Q3, operating revenues expanded by 14.2% year-over-year.",
                page_number=1,
                start_char=0,
                end_char=59,
            )
        ],
    )
    answer = GroundedAnswerResponse(answer="Revenues expanded by 14.2%.", claims=[claim])

    def fake_small_llm(prompt: str, model: str):
        return {"text": '{"verdict": "supports", "reason": "Exact metric and trajectory confirmed."}'}

    pipeline = VerificationPipeline(small_provider=fake_small_llm)
    verified_answer = pipeline.verify_answer(answer)

    assert verified_answer.insufficient_evidence is False
    assert len(verified_answer.claims) == 1
    assert verified_answer.claims[0].support_status == "verified"


def test_pipeline_fail_path_stage_1():
    """Verify that a claim with altered numbers fails Stage 1 without needing LLM entailment."""
    claim = ClaimItem(
        text="Operating revenues expanded by 24.2% year-over-year.",  # Altered number: 24.2% vs 14.2%
        citations=[
            CitationRef(
                chunk_id="chk_1",
                quote="In Q3, operating revenues expanded by 14.2% year-over-year.",
                page_number=1,
                start_char=0,
                end_char=59,
            )
        ],
    )
    answer = GroundedAnswerResponse(answer="Revenues expanded by 24.2%.", claims=[claim])

    stage2_called = False

    def fake_small_llm(prompt: str, model: str):
        nonlocal stage2_called
        stage2_called = True
        return {"text": '{"verdict": "supports", "reason": "fake"}'}

    pipeline = VerificationPipeline(small_provider=fake_small_llm)
    verified_answer = pipeline.verify_answer(answer)

    # Must fail deterministically at Stage 1, Stage 2 must NOT be called
    assert stage2_called is False
    assert verified_answer.insufficient_evidence is True
    assert "sources do not say" in verified_answer.answer.lower()
    assert verified_answer.claims[0].support_status == "rejected"


def test_pipeline_partial_path():
    """Verify partial support handling."""
    claim = ClaimItem(
        text="Worldwide revenue grew by 15%.",
        citations=[
            CitationRef(
                chunk_id="chk_1",
                quote="Revenue grew by 15% across our Asian markets.",
                page_number=1,
                start_char=0,
                end_char=46,
            )
        ],
    )
    answer = GroundedAnswerResponse(answer="Worldwide revenue grew by 15%.", claims=[claim])

    pipeline = VerificationPipeline()
    verified_answer = pipeline.verify_answer(answer)

    assert verified_answer.claims[0].support_status == "partial"
    assert "partial" in verified_answer.claims[0].rejection_reason.lower()


def test_pipeline_abstain_when_none_survive():
    """Verify that if all claims fail verification, answer becomes 'The sources do not say.'"""
    claim = ClaimItem(
        text="The clinical trial improved patient recovery times.",
        citations=[
            CitationRef(
                chunk_id="chk_1",
                quote="The clinical trial did not improve patient recovery times.",  # Negation
                page_number=1,
                start_char=0,
                end_char=58,
            )
        ],
    )
    answer = GroundedAnswerResponse(answer="Trial improved recovery.", claims=[claim])

    pipeline = VerificationPipeline()
    verified_answer = pipeline.verify_answer(answer)

    assert verified_answer.insufficient_evidence is True
    assert verified_answer.answer == "The sources do not say."
    assert verified_answer.claims[0].support_status == "rejected"


def test_pipeline_escalation_path():
    """Verify that when small LLM rejects a complex claim, pipeline escalates to large model."""
    claim = ClaimItem(
        text="Enzyme inhibition triggered cell apoptosis downstream.",
        citations=[
            CitationRef(
                chunk_id="chk_1",
                quote="Enzyme inhibition initiated a signaling cascade culminating in programmed cell death.",
                page_number=2,
                start_char=0,
                end_char=86,
            )
        ],
    )
    answer = GroundedAnswerResponse(answer="Inhibition triggered apoptosis.", claims=[claim])

    large_called = False

    def fake_small_llm(prompt: str, model: str):
        # Small model erroneously fails entailment
        return {"text": '{"verdict": "unsupported", "reason": "Different words used."}'}

    def fake_large_llm(prompt: str, model: str):
        nonlocal large_called
        large_called = True
        return {"text": '{"verdict": "supports", "reason": "Programmed cell death is synonymous with apoptosis."}'}

    pipeline = VerificationPipeline(
        small_provider=fake_small_llm,
        large_provider=fake_large_llm,
    )
    verified_answer = pipeline.verify_answer(answer)

    assert large_called is True
    assert verified_answer.claims[0].support_status == "verified"
    assert "escalated" in verified_answer.claims[0].rejection_reason.lower() or "large" in verified_answer.claims[0].rejection_reason.lower()


def test_rejected_claims_are_not_in_final_answer():
    """One verified + one rejected claim: the free-text answer must contain only the verified one."""
    quote = "Revenue grew 14.2%."
    good = ClaimItem(text="Revenue grew 14.2%.", citations=[CitationRef(chunk_id="c1", quote=quote)])
    bad = ClaimItem(text="The CEO resigned in 2019.", citations=[CitationRef(chunk_id="c1", quote=quote)])
    answer = GroundedAnswerResponse(answer="Revenue grew 14.2%. The CEO resigned in 2019.", claims=[good, bad])

    pipeline = VerificationPipeline(small_provider=lambda p, m: {"text": '{"verdict": "supports", "reason": "ok"}'})
    result = pipeline.verify_answer(answer)

    assert [c.support_status for c in result.claims] == ["verified", "rejected"]
    assert "CEO" not in result.answer
    assert result.answer == "Revenue grew 14.2%."


def _claim(text="Revenues grew 14.2%.", quote="Revenues grew 14.2% in Q3."):
    cits = [] if quote is None else [CitationRef(chunk_id="c1", quote=quote)]
    return ClaimItem(text=text, citations=cits)


def _says(verdict):
    return lambda prompt, model: {"text": f'{{"verdict": "{verdict}", "reason": "r"}}'}


def test_default_pipeline_escalates_to_large_model(monkeypatch):
    """Production builds VerificationPipeline() with no providers: escalation must still reach the large model."""
    from packages.llm_gateway import gateway
    from packages.verification import pipeline as vp

    models = []

    def fake_chat(prompt, system_prompt, model):
        models.append(model)
        verdict = "unsupported" if model == gateway.SMALL_MODEL else "supports"
        return gateway.ChatResponse(text=f'{{"verdict": "{verdict}", "reason": "r"}}', prompt_tokens=1,
                                    completion_tokens=1, total_tokens=2, cost_usd=0.0, latency_ms=0.0)

    monkeypatch.setattr(vp, "generate_chat", fake_chat)
    claim = VerificationPipeline().verify_single_claim(_claim())
    assert models == [gateway.SMALL_MODEL, gateway.LARGE_MODEL]
    assert claim.support_status == "verified"


def test_claim_without_citation_or_quote_is_rejected():
    p = VerificationPipeline(small_provider=_says("supports"))
    assert p.verify_single_claim(_claim(quote=None)).support_status == "rejected"
    assert p.verify_single_claim(_claim(quote="   ")).support_status == "rejected"
    assert p.llm_calls == 0  # rejected before any paid call


def test_stage2_verdicts_and_escalation_outcomes():
    def run(small, large):
        return VerificationPipeline(small_provider=_says(small), large_provider=_says(large)).verify_single_claim(_claim())

    assert run("partial", "supports").support_status == "partial"  # no escalation on partial
    assert run("unsupported", "partial").support_status == "partial"
    assert run("unsupported", "unsupported").support_status == "rejected"
    bad_json = VerificationPipeline(small_provider=lambda p, m: {"text": "not json"}, large_provider=_says("unsupported"))
    assert bad_json.verify_single_claim(_claim()).support_status == "rejected"  # unparseable verdict never verifies
