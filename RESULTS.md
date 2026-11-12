# CiteGuard Evaluation Benchmark

This document tracks empirical evaluation runs across retrieval, verification, and agent ablations.
All numbers are generated directly by `packages/evaluation/runner.py` and updated via `scripts/render_results.py`.

---

## Current Dev Benchmark

<!-- RESULTS:START -->
_Last updated: 2026-11-11T06:15:05.769841+00:00 (golden questions: 25, verifier pairs: 91)_

> **Small sample.** 25 golden questions (target 50+) and 91 verifier pairs (target 175+). Treat these numbers as a smoke test, not as evidence.

### 1. Claim verifier (stage 1 deterministic checks, then LLM entailment)
| Metric | Value | Release target | Status |
| :--- | :--- | :--- | :--- |
| Precision | 1.0000 | >= 0.9500 | PASS |
| Recall | 0.9697 | >= 0.8500 | PASS |
| F1 | 0.9846 | - | - |
| False acceptance rate | 0.0000 | <= 0.0200 | PASS |
| False rejection rate | 0.0303 | - | - |
| Accuracy 95% CI (bootstrap) | [0.8352, 0.9560] | - | - |

Stage 1 alone (numbers, units, dates, polarity, entities; no LLM):

| Precision | Recall | False acceptance rate | False rejection rate |
| :--- | :--- | :--- | :--- |
| 0.5410 | 1.0000 | 0.4828 | 0.0000 |

### 2. Golden set category distribution
| Category | Count |
| :--- | :--- |
| factual | 5 |
| numerical | 6 |
| comparative | 3 |
| temporal | 2 |
| multi-hop | 2 |
| multi-document | 3 |
| conflicting | 1 |
| unanswerable | 3 |

### 3. Retrieval and grounding ablations
_Not measured yet. Put your PDFs in `data/corpus/`, configure an LLM provider, and run `make eval`._

### 4. Single-shot (E7) vs Report Agent (E8)
_Not measured yet. Put your PDFs in `data/corpus/`, configure an LLM provider, and run `make eval`._
<!-- RESULTS:END -->

---

## Evaluation Methodology
- **Golden Dataset**: Multi-category golden question set (factual, numerical, multi-hop, unanswerable).
- **Verifier Dataset**: Human-labeled claim-quote pairs (supports, partial, unsupported).
- **False Acceptance Rate (FAR)**: Proportion of unsupported claims falsely marked as supported (primary release gate metric).
