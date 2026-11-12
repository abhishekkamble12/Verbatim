"""Grounded answer generation with claim-level structured output and chunk resolution."""

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from packages.llm_gateway.gateway import SMALL_MODEL, generate_chat


class CitationRef(BaseModel):
    chunk_id: str
    quote: str | None = None
    page_number: int | None = None
    start_char: int | None = None
    end_char: int | None = None


class ClaimItem(BaseModel):
    text: str
    citations: list[CitationRef] = Field(default_factory=list)
    support_status: str = "pending"  # "pending", "verified", "rejected", "partial"
    rejection_reason: str | None = None


class GroundedAnswerResponse(BaseModel):
    answer: str
    claims: list[ClaimItem] = Field(default_factory=list)
    insufficient_evidence: bool = False


GROUNDED_SYSTEM_PROMPT = """You are CiteGuard, a verified-citation research assistant.
Rules:
1. Answer strictly based on the provided evidence chunks.
2. For every assertion, provide a claim with the exact chunk_id supporting it.
3. The chunk_id must match one of the provided chunks. Do NOT invent chunk IDs or quotes.
4. If the provided chunks do not contain enough information to answer the question, abstain completely:
   set "insufficient_evidence": true and "answer": "The sources do not say."
5. Output MUST be valid JSON adhering to:
{
  "answer": "string",
  "claims": [
    {"text": "string", "citations": [{"chunk_id": "chunk_id"}], "support_status": "pending"}
  ],
  "insufficient_evidence": false
}"""


def parse_llm_json(raw_text: str) -> dict[str, Any]:
    """Extract and parse JSON from raw LLM response text."""
    clean = raw_text.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    if clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    return json.loads(clean.strip())


def generate_grounded_answer(
    query: str,
    retrieved_chunks: list[dict[str, Any]],
    provider_fn: Callable[[str, str], dict[str, Any]] | None = None,
    model: str = SMALL_MODEL,
) -> GroundedAnswerResponse:
    """Generate structured grounded answer and resolve chunk citations in code."""
    # 1. Immediate abstention if no evidence chunks retrieved
    if not retrieved_chunks:
        return GroundedAnswerResponse(
            answer="The sources do not say.",
            claims=[],
            insufficient_evidence=True,
        )

    # 2. Build evidence prompt
    chunk_map = {str(c["id"]): c for c in retrieved_chunks}
    evidence_blocks = []
    for c in retrieved_chunks:
        evidence_blocks.append(f"[Chunk ID: {c['id']}] (Page {c.get('page_number', 1)})\n{c.get('text', '')}")

    user_prompt = (
        f"Question: {query}\n\n"
        f"Evidence Chunks:\n{chr(10).join(evidence_blocks)}\n\n"
        "Return your answer and claims as JSON:"
    )

    # 3. Call LLM with single retry on invalid JSON
    raw_payload = None
    for _attempt in range(2):
        if provider_fn is not None:
            llm_result = provider_fn(user_prompt, model)
        else:
            chat_res = generate_chat(
                prompt=user_prompt,
                system_prompt=GROUNDED_SYSTEM_PROMPT,
                model=model,
            )
            llm_result = {"text": chat_res.text}

        try:
            raw_payload = parse_llm_json(llm_result.get("text", ""))
            break
        except Exception:
            # Append clarification hint for retry
            user_prompt += "\nNote: Your previous response was not valid JSON. You MUST return strictly valid JSON."

    if raw_payload is None:
        # If still failing, return clean abstention
        return GroundedAnswerResponse(
            answer="The sources do not say.",
            claims=[],
            insufficient_evidence=True,
        )

    try:
        parsed = GroundedAnswerResponse.model_validate(raw_payload)
    except ValidationError:
        # Valid JSON in the wrong shape: abstain like the invalid-JSON path instead of returning a 500.
        return GroundedAnswerResponse(answer="The sources do not say.", claims=[], insufficient_evidence=True)

    # 4. Resolve quote, page, and offsets from chunk_id (Code resolves, model cannot invent)
    for claim in parsed.claims:
        for citation in claim.citations:
            target_id = str(citation.chunk_id)
            if target_id in chunk_map:
                matched_chunk = chunk_map[target_id]
                citation.quote = matched_chunk.get("text")
                citation.page_number = matched_chunk.get("page_number", 1)
                citation.start_char = matched_chunk.get("start_char", 0)
                citation.end_char = matched_chunk.get("end_char", len(citation.quote or ""))
            else:
                # Hallucinated chunk_id rejection
                claim.support_status = "rejected"
                claim.rejection_reason = f"Hallucinated chunk ID: {target_id} was not in retrieved evidence."

    return parsed
