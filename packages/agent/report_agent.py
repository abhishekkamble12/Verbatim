"""Bounded Report Agent: a plain state machine (PLAN -> RESEARCH -> COMPOSE -> DONE) with hard budgets.

Every LLM call counts against `max_llm_calls` and `token_cap`, including the entailment calls made
inside the verification pipeline. The final report is built from verified claims only: the LLM is
never asked to write free text that could add unchecked facts.
"""

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from packages.llm_gateway.gateway import SMALL_MODEL
from packages.retrieval.generation import CitationRef, ClaimItem
from packages.verification.pipeline import VerificationPipeline

RetrieveFn = Callable[[str], list[dict[str, Any]]]


class AgentStepTrace(BaseModel):
    step_num: int
    state: str  # "PLAN", "RESEARCH", "COMPOSE", "DONE"
    tool: str | None = None
    tool_input: str | None = None
    tool_output: str | None = None
    tokens: int = 0
    latency_ms: float = 0.0


class ReportAgentResult(BaseModel):
    question: str
    report_markdown: str
    verified_claims: list[ClaimItem] = Field(default_factory=list)
    trace: list[AgentStepTrace] = Field(default_factory=list)
    llm_call_count: int = 0
    total_retries: int = 0
    total_tokens: int = 0
    is_partial: bool = False
    drafted_claim_count: int = 0
    retrieved_chunk_ids: list[str] = Field(default_factory=list)


PARTIAL_WARNING = "> [!WARNING] Report is partial: the agent budget was reached (budget exceeded)."


def render_report(question: str, claims: list[ClaimItem], is_partial: bool) -> str:
    """Deterministic report: only verified claims, each with its source."""
    if not claims:
        body = "# Research Report\n\nInsufficient evidence found in the sources to answer the query."
    else:
        lines = [f"# Research Report\n\n**Question:** {question}\n\n## Verified findings\n"]
        for c in claims:
            cit = c.citations[0]
            flag = " (partial support)" if c.support_status == "partial" else ""
            lines.append(f"- {c.text}{flag} [{cit.chunk_id}, p. {cit.page_number}]")
        body = "\n".join(lines)
    return f"{body}\n\n{PARTIAL_WARNING}" if is_partial else body


class ReportAgent:
    """Bounded Research Agent operating as a plain Python state machine."""

    def __init__(
        self,
        retrieve_fn: RetrieveFn,
        provider_fn: Callable[[str, str], dict[str, Any]] | None = None,
        verification_pipeline: VerificationPipeline | None = None,
        max_sub_questions: int = 4,
        max_retries_per_sub: int = 1,
        max_llm_calls: int = 12,
        token_cap: int = 10000,
        model: str = SMALL_MODEL,
    ):
        # retrieve_fn is bound to one user and notebook by the caller, so the agent cannot cross tenants.
        self.retrieve_fn = retrieve_fn
        self.provider_fn = provider_fn
        self.verification_pipeline = verification_pipeline or VerificationPipeline()
        self.max_sub_questions = max_sub_questions
        self.max_retries_per_sub = max_retries_per_sub
        self.max_llm_calls = max_llm_calls
        self.token_cap = token_cap
        self.model = model

    def _call_llm(self, prompt: str) -> dict[str, Any]:
        if self.provider_fn is not None:
            return self.provider_fn(prompt, self.model)
        from packages.llm_gateway.gateway import generate_chat

        res = generate_chat(prompt=prompt, model=self.model)
        return {"text": res.text, "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens}

    def run(self, question: str) -> ReportAgentResult:
        trace: list[AgentStepTrace] = []
        pipeline = self.verification_pipeline
        # Entailment calls inside the pipeline are charged to this run, so measure from here.
        base_calls, base_tokens = pipeline.llm_calls, pipeline.llm_tokens
        own_calls = 0
        own_tokens = 0

        def calls() -> int:
            return own_calls + pipeline.llm_calls - base_calls

        def tokens() -> int:
            return own_tokens + pipeline.llm_tokens - base_tokens

        def over_budget(extra_calls: int = 0) -> bool:
            return calls() + extra_calls >= self.max_llm_calls or tokens() >= self.token_cap

        is_partial = False
        total_retries = 0
        drafted = 0
        retrieved_ids: list[str] = []
        verified_claims: list[ClaimItem] = []

        # 1. PLAN
        t0 = time.perf_counter()
        plan_res = self._call_llm(
            f"PLAN: Split the following complex question into at most {self.max_sub_questions} "
            f"atomic, verifiable sub-questions as JSON.\nQuestion: {question}\n\n"
            'Return format: {"sub_questions": ["sub_q_1", "sub_q_2"]}'
        )
        own_calls += 1
        plan_tokens = plan_res.get("prompt_tokens", 0) + plan_res.get("completion_tokens", 0)
        own_tokens += plan_tokens
        try:
            sub_questions = json.loads(plan_res.get("text", "{}")).get("sub_questions", [question])
            sub_questions = [str(q) for q in sub_questions][: self.max_sub_questions] or [question]
        except (ValueError, AttributeError):
            sub_questions = [question]
        trace.append(
            AgentStepTrace(
                step_num=len(trace) + 1,
                state="PLAN",
                tool_input=question,
                tool_output=json.dumps(sub_questions),
                tokens=plan_tokens,
                latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )
        )

        # 2. RESEARCH
        for sub_q in sub_questions:
            if over_budget():
                is_partial = True
                break

            retries_used = 0
            sub_q_verified = False
            while retries_used <= self.max_retries_per_sub and not sub_q_verified:
                if over_budget():
                    is_partial = True
                    break

                t_res = time.perf_counter()
                tokens_before = tokens()
                retrieved = self.retrieve_fn(sub_q)  # tool: search_notebook
                retrieved_ids.extend(c["id"] for c in retrieved)
                chunk_map = {c["id"]: c for c in retrieved}
                evidence = "\n".join(f"[{c['id']}]: {c['text']}" for c in retrieved)

                draft_res = self._call_llm(
                    "RESEARCH: Based on the following evidence chunks, draft claims answering the sub-question as JSON.\n"
                    f"Sub-question: {sub_q}\nEvidence:\n{evidence}\n\n"
                    'Return format: {"claims": [{"text": "...", "citations": [{"chunk_id": "id"}]}]}'
                )
                own_calls += 1
                own_tokens += draft_res.get("prompt_tokens", 0) + draft_res.get("completion_tokens", 0)
                try:
                    claims_data = json.loads(draft_res.get("text", "{}")).get("claims", [])
                except (ValueError, AttributeError):
                    claims_data = []

                n_verified = 0
                for cd in claims_data:
                    if not isinstance(cd, dict):
                        continue
                    citations = []
                    for cit in cd.get("citations", []):
                        matched = chunk_map.get(cit.get("chunk_id")) if isinstance(cit, dict) else None
                        if matched:  # the model only names an id; quote, page and offsets come from the chunk
                            citations.append(
                                CitationRef(
                                    chunk_id=matched["id"],
                                    quote=matched.get("text"),
                                    page_number=matched.get("page_number", 1),
                                    start_char=matched.get("start_char", 0),
                                    end_char=matched.get("end_char", len(matched.get("text", ""))),
                                )
                            )
                    drafted += 1
                    if over_budget(extra_calls=1):  # verifying may take 2 calls (small model, then escalation)
                        is_partial = True
                        break
                    claim = pipeline.verify_single_claim(ClaimItem(text=cd.get("text", ""), citations=citations))
                    if claim.support_status in {"verified", "partial"}:
                        verified_claims.append(claim)
                        n_verified += 1
                        sub_q_verified = True

                trace.append(
                    AgentStepTrace(
                        step_num=len(trace) + 1,
                        state="RESEARCH",
                        tool="search_notebook & verify_claim",
                        tool_input=sub_q,
                        tool_output=f"Retrieved {len(retrieved)} chunks, verified {n_verified} claims.",
                        tokens=tokens() - tokens_before,
                        latency_ms=round((time.perf_counter() - t_res) * 1000.0, 2),
                    )
                )

                if not sub_q_verified and retries_used < self.max_retries_per_sub and not is_partial:
                    retries_used += 1
                    total_retries += 1
                    sub_q = f"{sub_q} exact details"
                else:
                    break

        # 3. COMPOSE (no LLM: the report is exactly the verified claims)
        t_comp = time.perf_counter()
        report_md = render_report(question, verified_claims, is_partial)
        trace.append(
            AgentStepTrace(
                step_num=len(trace) + 1,
                state="COMPOSE",
                tool_input=f"{len(verified_claims)} verified claims",
                tool_output=report_md[:100] + "...",
                latency_ms=round((time.perf_counter() - t_comp) * 1000.0, 2),
            )
        )

        # 4. DONE
        trace.append(
            AgentStepTrace(
                step_num=len(trace) + 1,
                state="DONE",
                tool_output="Partial report: budget reached." if is_partial else "Agent execution completed.",
            )
        )

        return ReportAgentResult(
            question=question,
            report_markdown=report_md,
            verified_claims=verified_claims,
            trace=trace,
            llm_call_count=calls(),
            total_retries=total_retries,
            total_tokens=tokens(),
            is_partial=is_partial,
            drafted_claim_count=drafted,
            retrieved_chunk_ids=list(dict.fromkeys(retrieved_ids)),
        )
