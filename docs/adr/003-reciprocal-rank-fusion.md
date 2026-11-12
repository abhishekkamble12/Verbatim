# ADR-003: Reciprocal Rank Fusion (RRF) for Hybrid Dense-Sparse Retrieval

## Status
Accepted

## Context
Dense vector search (semantic similarity) excels at conceptual questions but fails on exact identifier lookups, acronyms, or specific numbers (e.g., "arXiv:2611.00166", "Doverall = 0.5973"). Conversely, sparse keyword search (BM25 / PostgreSQL `tsvector`) excels at exact tokens but fails on paraphrased natural language. Combining both is essential, but score distributions between cosine distances and BM25 scores have different scales and cannot be directly summed without calibration.

## Decision
Use Reciprocal Rank Fusion (RRF) with constant $k = 60$ to fuse top-20 dense candidates (pgvector HNSW cosine distance) and top-20 sparse candidates (PostgreSQL `tsvector` with `websearch_to_tsquery`):
$$RRF\_score(d) = \sum_{m \in \{dense, sparse\}} \frac{1}{k + rank_m(d)}$$

## Consequences
### Positive
- **Scale-invariant**: RRF operates purely on ordinal ranks, eliminating score normalization or tuning calibration parameters.
- **Superior Recall**: Empirical ablations demonstrate hybrid RRF captures both conceptual and exact-token matches reliably.
- **Single Datastore**: Both dense vectors (via `pgvector`) and sparse full-text indices reside in the same PostgreSQL instance, ensuring single-transaction consistency and tenant isolation (`user_id` and `notebook_id`).

### Negative
- Pure rank fusion ignores the relative margin between rank 1 and rank 2; cross-encoder reranking is planned to refine the fused top-20 to top-5.

