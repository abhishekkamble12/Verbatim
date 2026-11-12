"""Two-stage verification pipeline: deterministic factual check followed by LLM entailment with model escalation."""

from collections.abc import Callable
from typing import Any

from packages.llm_gateway.gateway import LARGE_MODEL, SMALL_MODEL, generate_chat
from packages.retrieval.generation import ClaimItem, GroundedAnswerResponse, parse_llm_json
from packages.verification.fuzzy import VerificationVerdict, verify_claim_against_quote

ENTAILMENT_SYSTEM_PROMPT = """You are a rigorous factual entailment verifier.
Determine whether the provided Quote strictly entails the Claim.
Options:
- "supports": The quote provides sufficient evidence for all statements in the claim.
- "partial": The quote supports part of the claim or has narrower scope.
- "unsupported": The quote does not support the claim or contradicts it.

Return valid JSON adhering to:
{"verdict": "supports" | "partial" | "unsupported", "reason": "brief explanation"}"""


class VerificationPipeline:
    """Orchestrates Stage 1 (deterministic) and Stage 2 (LLM entailment) verification with escalation."""

    def __init__(
        self,
        small_provider: Callable[[str, str], dict[str, Any]] | None = None,
        large_provider: Callable[[str, str], dict[str, Any]] | None = None,
        small_model: str = SMALL_MODEL,
        large_model: str = LARGE_MODEL,
    ):
        self.small_provider = small_provider
        self.large_provider = large_provider
        self.small_model = small_model
        self.large_model = large_model
        # Running totals so callers (the Report Agent) can charge entailment calls to their budget.
        self.llm_calls = 0
        self.llm_tokens = 0

    def _call_entailment_llm(self, provider_fn: Callable | None, model: str, claim: str, quote: str) -> dict[str, str]:
        prompt = f"Claim: {claim}\nQuote: {quote}\n\nEvaluate entailment as JSON:"
        self.llm_calls += 1
        if provider_fn is not None:
            res = provider_fn(prompt, model)
            text = res.get("text", "")
            self.llm_tokens += res.get("prompt_tokens", 0) + res.get("completion_tokens", 0)
        else:
            chat_res = generate_chat(prompt=prompt, system_prompt=ENTAILMENT_SYSTEM_PROMPT, model=model)
            text = chat_res.text
            self.llm_tokens += chat_res.total_tokens

        try:
            parsed = parse_llm_json(text)
            return {
                "verdict": parsed.get("verdict", "unsupported").lower(),
                "reason": parsed.get("reason", "Parsed LLM verdict."),
            }
        except Exception as e:
            return {"verdict": "unsupported", "reason": f"Failed to parse LLM entailment response: {e}"}

    def verify_single_claim(self, claim: ClaimItem) -> ClaimItem:
        if not claim.citations:
            claim.support_status = "rejected"
            claim.rejection_reason = "No citations provided for claim."
            return claim

        citation = claim.citations[0]
        quote = citation.quote
        if not quote or not quote.strip():
            claim.support_status = "rejected"
            claim.rejection_reason = "Citation quote is empty or missing."
            return claim

        # -------------------------------------------------------------
        # STAGE 1: Deterministic check (numbers, dates, units, polarity)
        # -------------------------------------------------------------
        det_result = verify_claim_against_quote(claim.text, quote)
        if det_result.verdict == VerificationVerdict.UNSUPPORTED:
            claim.support_status = "rejected"
            claim.rejection_reason = f"Stage 1 deterministic failure: {det_result.reason}"
            return claim

        if det_result.verdict == VerificationVerdict.PARTIAL:
            claim.support_status = "partial"
            claim.rejection_reason = f"Stage 1 partial match: {det_result.reason}"
            return claim

        # -------------------------------------------------------------
        # STAGE 2: LLM Entailment check (Small model default)
        # -------------------------------------------------------------
        entailment = self._call_entailment_llm(self.small_provider, self.small_model, claim.text, quote)
        verdict = entailment["verdict"]

        if verdict == "supports":
            claim.support_status = "verified"
            claim.rejection_reason = None
            return claim

        if verdict == "partial":
            claim.support_status = "partial"
            claim.rejection_reason = f"Stage 2 partial entailment: {entailment['reason']}"
            return claim

        # -------------------------------------------------------------
        # ESCALATION: If small model fails, escalate to large model
        # -------------------------------------------------------------
        # No large_provider means the gateway's large model, as the small stage does (Project.txt: escalate on failure).
        escalated_entailment = self._call_entailment_llm(self.large_provider, self.large_model, claim.text, quote)
        if escalated_entailment["verdict"] == "supports":
            claim.support_status = "verified"
            claim.rejection_reason = f"Verified after escalation to large model: {escalated_entailment['reason']}"
            return claim
        if escalated_entailment["verdict"] == "partial":
            claim.support_status = "partial"
            claim.rejection_reason = f"Stage 2 partial entailment (escalated): {escalated_entailment['reason']}"
            return claim

        claim.support_status = "rejected"
        claim.rejection_reason = f"Stage 2 entailment failed: {entailment['reason']}"
        return claim

    def verify_answer(self, answer: GroundedAnswerResponse) -> GroundedAnswerResponse:
        """Verify all claims in answer. If none survive, abstain cleanly."""
        if answer.insufficient_evidence or not answer.claims:
            answer.insufficient_evidence = True
            answer.answer = "The sources do not say."
            return answer

        verified_claims = []
        for claim in answer.claims:
            v_claim = self.verify_single_claim(claim)
            verified_claims.append(v_claim)

        answer.claims = verified_claims
        surviving = [c for c in verified_claims if c.support_status in {"verified", "partial"}]

        if not surviving:
            answer.insufficient_evidence = True
            answer.answer = "The sources do not say."
        elif len(surviving) < len(verified_claims):
            # Rejected claims must never reach the user through the free-text answer.
            answer.answer = " ".join(c.text for c in surviving)

        return answer


def verify_grounded_answer(
    answer: GroundedAnswerResponse,
    pipeline: VerificationPipeline | None = None,
) -> GroundedAnswerResponse:
    if pipeline is None:
        pipeline = VerificationPipeline()
    return pipeline.verify_answer(answer)

