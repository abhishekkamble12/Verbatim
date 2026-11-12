"""Report job: run the bounded Report Agent for one notebook and store the report and its trace."""

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from packages.agent.report_agent import ReportAgent
from packages.llm_gateway.gateway import generate_embedding, track_usage
from packages.retrieval.hybrid import RetrievalConfig, hybrid_retrieve
from packages.retrieval.models import AgentStep, Job, Report, UsageLedger


def process_report_job(
    session: Session,
    job: Job,
    provider_fn: Callable[[str, str], dict[str, Any]] | None = None,
    embed_fn: Callable[[str], tuple[list[float], bool]] = generate_embedding,
) -> str:
    """Returns the new report id."""
    question = json.loads(job.payload or "{}").get("question", "")

    def search_notebook(query: str) -> list[dict[str, Any]]:
        # Bound to this job's user and notebook: the agent cannot ask for anyone else's data.
        return hybrid_retrieve(session, query, job.user_id, job.notebook_id, RetrievalConfig(top_k=3), embed_fn=embed_fn)

    started = time.perf_counter()
    with track_usage() as usage:
        result = ReportAgent(retrieve_fn=search_notebook, provider_fn=provider_fn).run(question)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    report_id = f"rep_{uuid.uuid4().hex[:12]}"
    session.add(
        Report(
            id=report_id,
            user_id=job.user_id,
            notebook_id=job.notebook_id,
            job_id=job.id,
            question=question,
            markdown=result.report_markdown,
            claims_json=json.dumps([c.model_dump() for c in result.verified_claims]),
            is_partial=result.is_partial,
        )
    )
    session.add(
        UsageLedger(
            id=f"use_{uuid.uuid4().hex[:12]}",
            user_id=job.user_id,
            job_type="report",
            ref_id=report_id,
            prompt_tokens=int(usage["prompt_tokens"]),
            completion_tokens=int(usage["completion_tokens"]),
            cost_usd=usage["cost_usd"],
            latency_ms=latency_ms,
        )
    )
    for step in result.trace:  # ids start with the step number so they sort in run order
        session.add(
            AgentStep(
                id=f"stp_{step.step_num:03d}_{uuid.uuid4().hex[:8]}",
                job_id=job.id,
                state=step.state,
                tool=step.tool,
                tool_input=step.tool_input,
                tool_output=step.tool_output,
                tokens=step.tokens,
                latency_ms=step.latency_ms,
            )
        )
    return report_id
