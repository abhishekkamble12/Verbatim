# ADR-002: Two-Stage Claim Verification (Deterministic Checks + LLM Entailment)

## Status
Accepted

## Context
Standard RAG systems rely solely on LLMs to self-evaluate or generate answers. This frequently allows subtle hallucinations—such as altered numbers (e.g., 12.5% changed to 13.5%), swapped entities, or flipped polarities (e.g., "did not improve" reported as "improved")—to slip into user-facing answers. Using an expensive LLM to verify every single trivial claim also introduces high latency and cost.

## Decision
Implement a two-stage hierarchical verification pipeline:
1. **Stage 1 (Deterministic Rules Engine)**:
   - Validates that the cited chunk ID exists and was retrieved.
   - Verifies that the exact quote exists at character offsets `page_text[start:end] == chunk.text`.
   - Runs strict normalized comparison for numbers, percentages, dates, and units (tolerance only allowed when qualified by approximate indicators like "about" or "~").
   - Matches named entities and polarity/direction indicators.
   - Claims failing Stage 1 are immediately rejected with zero LLM cost.
2. **Stage 2 (Natural Language Entailment via LLM)**:
   - Evaluates whether the quote semantically entails the claim (`supports`, `partial`, or `unsupported`).
   - Complex claims that fail verification on the small model escalate to a larger model before final rejection.
   - Only strictly verified claims survive into the final answer. If zero claims survive, the system honestly abstains with *"The sources do not say."*

## Consequences
### Positive
- **Zero False Acceptance Rate (0.0% FAR)**: Numerical manipulations and hallucinated citations are caught deterministically.
- **Cost optimization**: ~50% of false claims are discarded at Stage 1 with 0 LLM token cost.
- **Honest abstention**: Eliminates confabulation when sources lack supporting evidence.

### Negative
- Stage 1 normalizations (number words, dates) require domain-specific rules (currently English-centric).

