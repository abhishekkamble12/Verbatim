import json

from packages.agent.report_agent import ReportAgent, ReportAgentResult


def test_report_agent_normal_run():
    """Verify normal 4-state flow: PLAN -> RESEARCH -> COMPOSE -> DONE."""
    candidate_chunks = [
        {"id": "chk_rev", "text": "Revenues grew by 14.2% year-over-year in Q3.", "section": "Finance", "doc_title": "10-Q"},
        {"id": "chk_margin", "text": "Operating margin reached 18.5% due to cloud efficiencies.", "section": "Operations", "doc_title": "10-Q"},
    ]

    def fake_llm(prompt: str, model: str):
        if "PLAN:" in prompt:
            return {
                "text": json.dumps({"sub_questions": ["What was revenue growth in Q3?", "What was operating margin?"]}),
                "prompt_tokens": 50,
                "completion_tokens": 30,
            }
        elif "RESEARCH:" in prompt:
            if "revenue" in prompt.lower():
                return {
                    "text": json.dumps({
                        "claims": [{"text": "Revenues grew by 14.2% year-over-year in Q3.", "citations": [{"chunk_id": "chk_rev"}]}]
                    }),
                    "prompt_tokens": 60,
                    "completion_tokens": 25,
                }
            else:
                return {
                    "text": json.dumps({
                        "claims": [{"text": "Operating margin reached 18.5% due to cloud efficiencies.", "citations": [{"chunk_id": "chk_margin"}]}]
                    }),
                    "prompt_tokens": 60,
                    "completion_tokens": 25,
                }
        elif "COMPOSE:" in prompt:
            return {
                "text": "# Financial Report\n\nQ3 showed revenue growth of 14.2% and operating margin of 18.5%.",
                "prompt_tokens": 80,
                "completion_tokens": 40,
            }
        return {"text": "{}", "prompt_tokens": 10, "completion_tokens": 10}

    agent = ReportAgent(
        retrieve_fn=lambda q: candidate_chunks,
        provider_fn=fake_llm,
    )

    result = agent.run(question="Provide a comprehensive breakdown of Q3 performance.")

    assert isinstance(result, ReportAgentResult)
    assert result.is_partial is False
    assert len(result.verified_claims) == 2
    assert "Revenues grew by 14.2% year-over-year in Q3." in result.report_markdown
    assert "[chk_rev" in result.report_markdown  # every line carries its source
    assert len(result.trace) >= 4  # PLAN, RESEARCH (sub-1), RESEARCH (sub-2), COMPOSE
    states = [step.state for step in result.trace]
    assert "PLAN" in states
    assert "RESEARCH" in states
    assert "COMPOSE" in states
    assert "DONE" in states


def test_report_agent_retry_path():
    """Verify that an unsupported claim triggers a query rewrite and exactly 1 retry."""
    candidate_chunks = [
        {"id": "chk_retry", "text": "Capital expenditure was $120M in 2023.", "section": "Capex", "doc_title": "Report"},
    ]

    attempt = 0

    def fake_llm_with_retry(prompt: str, model: str):
        nonlocal attempt
        if "PLAN:" in prompt:
            return {"text": json.dumps({"sub_questions": ["What was capex?"]}), "prompt_tokens": 20, "completion_tokens": 15}
        elif "RESEARCH:" in prompt:
            attempt += 1
            if attempt == 1:
                # First attempt: unsupported altered number (fails verification)
                return {
                    "text": json.dumps({
                        "claims": [{"text": "Capital expenditure was $500M in 2023.", "citations": [{"chunk_id": "chk_retry"}]}]
                    }),
                    "prompt_tokens": 30,
                    "completion_tokens": 20,
                }
            else:
                # Second attempt (after retry): correct claim
                return {
                    "text": json.dumps({
                        "claims": [{"text": "Capital expenditure was $120M in 2023.", "citations": [{"chunk_id": "chk_retry"}]}]
                    }),
                    "prompt_tokens": 30,
                    "completion_tokens": 20,
                }
        elif "COMPOSE:" in prompt:
            return {"text": "Capex was $120M.", "prompt_tokens": 20, "completion_tokens": 10}
        return {"text": "{}", "prompt_tokens": 10, "completion_tokens": 10}

    agent = ReportAgent(
        retrieve_fn=lambda q: candidate_chunks,
        provider_fn=fake_llm_with_retry,
    )

    result = agent.run(question="Analyze capex.")

    assert result.total_retries == 1
    assert len(result.verified_claims) == 1
    assert result.verified_claims[0].text == "Capital expenditure was $120M in 2023."


def test_report_agent_budget_stop():
    """Verify that hitting the max LLM calls budget halts agent and returns partial report."""
    candidate_chunks = [{"id": "c1", "text": "Evidence 1", "section": "S1", "doc_title": "D1"}]

    def fake_llm_slow(prompt: str, model: str):
        if "PLAN:" in prompt:
            return {
                "text": json.dumps({"sub_questions": ["Sub 1", "Sub 2", "Sub 3", "Sub 4"]}),
                "prompt_tokens": 20,
                "completion_tokens": 20,
            }
        return {"text": json.dumps({"claims": []}), "prompt_tokens": 10, "completion_tokens": 10}

    # Set hard budget of max 2 LLM calls
    agent = ReportAgent(
        retrieve_fn=lambda q: candidate_chunks,
        provider_fn=fake_llm_slow,
        max_llm_calls=2,
    )

    result = agent.run(question="Broad multi-faceted question.")

    assert result.is_partial is True
    assert result.llm_call_count <= 2
    assert "budget exceeded" in result.report_markdown.lower() or "partial" in result.report_markdown.lower()


def test_report_agent_all_unsupported():
    """Verify that if all claims fail verification, report states insufficient evidence."""
    candidate_chunks = [{"id": "c1", "text": "Trial did not succeed.", "section": "Medical", "doc_title": "D1"}]

    def fake_llm_unsupported(prompt: str, model: str):
        if "PLAN:" in prompt:
            return {"text": json.dumps({"sub_questions": ["Did trial succeed?"]}), "prompt_tokens": 20, "completion_tokens": 15}
        elif "RESEARCH:" in prompt:
            # Asserts opposite polarity
            return {
                "text": json.dumps({
                    "claims": [{"text": "Trial succeeded completely.", "citations": [{"chunk_id": "c1"}]}]
                }),
                "prompt_tokens": 20,
                "completion_tokens": 15,
            }
        return {"text": "Insufficient evidence.", "prompt_tokens": 10, "completion_tokens": 10}

    agent = ReportAgent(
        retrieve_fn=lambda q: candidate_chunks,
        provider_fn=fake_llm_unsupported,
    )

    result = agent.run(question="Did trial succeed?")

    assert len(result.verified_claims) == 0
    assert "insufficient evidence" in result.report_markdown.lower()


def test_compose_never_calls_llm_and_report_has_only_verified_claims():
    """The LLM must not write the final text, or it could add facts that were never verified."""
    chunks = [{"id": "c1", "text": "Capex was $120M in 2023.", "section": "S", "doc_title": "D"}]
    prompts = []

    def fake_llm(prompt: str, model: str):
        prompts.append(prompt)
        if "PLAN:" in prompt:
            return {"text": json.dumps({"sub_questions": ["capex?"]}), "prompt_tokens": 5, "completion_tokens": 5}
        return {
            "text": json.dumps({"claims": [
                {"text": "Capex was $120M in 2023.", "citations": [{"chunk_id": "c1"}]},
                {"text": "Capex was $999M in 2023.", "citations": [{"chunk_id": "c1"}]},
            ]}),
            "prompt_tokens": 5,
            "completion_tokens": 5,
        }

    agent = ReportAgent(retrieve_fn=lambda q: chunks, provider_fn=fake_llm)
    result = agent.run("capex?")

    assert not any(p.startswith("COMPOSE:") for p in prompts)
    assert "$120M" in result.report_markdown
    assert "$999M" not in result.report_markdown
    assert result.drafted_claim_count == 2


def test_entailment_calls_count_toward_llm_budget():
    """Verification LLM calls are part of the 12-call budget, not free."""
    from packages.verification.pipeline import VerificationPipeline

    chunks = [{"id": "c1", "text": "Capex was $120M in 2023.", "section": "S", "doc_title": "D"}]

    def fake_llm(prompt: str, model: str):
        if "PLAN:" in prompt:
            return {"text": json.dumps({"sub_questions": ["a", "b", "c", "d"]}), "prompt_tokens": 1, "completion_tokens": 1}
        return {
            "text": json.dumps({"claims": [{"text": "Capex was $120M in 2023.", "citations": [{"chunk_id": "c1"}]}]}),
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }

    verifier = VerificationPipeline(small_provider=lambda p, m: {"text": '{"verdict": "supports", "reason": "ok"}'})
    agent = ReportAgent(retrieve_fn=lambda q: chunks, provider_fn=fake_llm, verification_pipeline=verifier, max_llm_calls=5)
    result = agent.run("capex?")

    # 1 plan + 2 x (1 draft + 1 entailment) = 5 -> the third sub-question must be refused.
    assert result.llm_call_count <= 5
    assert result.is_partial is True


def test_llm_budget_holds_when_verification_escalates():
    """One claim can cost 2 verification calls (small + large); the 12-call cap must still hold."""
    from packages.verification.pipeline import VerificationPipeline

    chunks = [{"id": "c1", "text": "Capex was $120M in 2023.", "section": "S", "doc_title": "D"}]

    def fake_llm(prompt: str, model: str):
        if "PLAN:" in prompt:
            return {"text": json.dumps({"sub_questions": ["a", "b", "c", "d"]}), "prompt_tokens": 1, "completion_tokens": 1}
        claims = [{"text": "Capex was $120M in 2023.", "citations": [{"chunk_id": "c1"}]}]
        return {"text": json.dumps({"claims": claims}), "prompt_tokens": 1, "completion_tokens": 1}

    verifier = VerificationPipeline(
        small_provider=lambda p, m: {"text": '{"verdict": "unsupported", "reason": "small"}'},
        large_provider=lambda p, m: {"text": '{"verdict": "supports", "reason": "large"}'},
    )
    result = ReportAgent(retrieve_fn=lambda q: chunks, provider_fn=fake_llm, verification_pipeline=verifier).run("capex?")

    # 1 plan + 3 x (1 draft + 2 verify) = 10; the 4th draft makes 11 and leaves no room for 2 more.
    assert result.llm_call_count <= 12
    assert result.is_partial is True
