# CiteGuard — Advanced Implementation Plan

> What to build next so this project stands out on a 2026 big-tech resume.
> Each item explains **what**, **why it matters in interviews**, **how to build it**, **effort**, and **which interview question it answers**.

---

## Current Strengths (already done)

| Area | What you have |
|:---|:---|
| Testing | 128 tests, 92% coverage, 0 lint errors, 0 type errors |
| Verification | Two-stage (deterministic + LLM entailment), 0% FAR on 91 pairs |
| Agent | Bounded 4-state plain Python state machine, no frameworks |
| Retrieval | pgvector HNSW + tsvector GIN + RRF fusion |
| Web UI | React + Vite + TS, 3-pane layout, claim badges, evidence inspector, trace viewer |
| IaC | Terraform validated (EC2, CloudFront, Cognito, SQS, S3) |
| Security | Tenant isolation tested, CORS, presigned uploads, request bounds |
| Evaluation | Ablation framework (E1–E8), CI quality gate, golden set |

---

## Priority Tiers

| Tier | Theme | Interview signal |
|:---|:---|:---|
| **P0** | Things that are broken or missing and will be noticed | Table stakes |
| **P1** | Production-grade engineering that separates senior from junior | System design depth |
| **P2** | ML engineering and advanced RAG that show domain mastery | ML/AI expertise |
| **P3** | Scale, resiltic, and operational excellence | Staff-level thinking |

---

## P0 — Fix Before Any Interview (1–2 days)

### P0.1 Human-Review the Golden Labels

**What**: The 25 golden questions and 91 verifier pairs in `data/` were drafted by an LLM. CLAUDE.md says labels must be human-written. Review every label, correct mistakes, and mark the set as human-verified in NOTES.md.

**Why it matters**: Any interviewer who reads your repo will see the disclaimer in README.md ("labels are LLM-drafted"). If you claim "hand-labelled evaluation data" on your resume without actually reviewing them, it is a credibility risk. Conversely, if you _have_ reviewed them, you can speak to specific labelling disagreements (which is a strong signal).

**How**:
1. Open `data/golden/dev.jsonl` and `data/golden/test.jsonl`. For each question, read the source passage and confirm the expected answer / gold passage.
2. Open `data/verifier/dev.jsonl`. For each (claim, quote) pair, confirm the label (supports / partial / unsupported).
3. Record any corrections and the count of changes in NOTES.md.
4. Remove the "LLM-drafted" disclaimer from README.md and NOTES.md.

**Effort**: 3–4 hours (91 pairs + 36 questions).

**Interview question it answers**: _"How did you build your evaluation dataset? How do you know your labels are correct?"_

---

### P0.2 Grow the Golden Set to 50+ Questions

**What**: You have 25 dev + 11 test = 36 questions. Project.txt targets 50+. Add 15–20 more questions across all 8 categories, focusing on categories with only 1–2 questions (conflicting: 1, temporal: 2, multi-hop: 2).

**Why it matters**: Small-sample metrics are not credible. An interviewer will notice "25 questions" and mentally discount everything. At 50+ you can compute meaningful confidence intervals.

**How**:
1. Read each of the 4 arXiv papers in `data/corpus/`.
2. Write 4–5 questions per paper, covering under-represented categories.
3. Include at least 3 more unanswerable questions (tests abstention).
4. Run `make eval` and update results.

**Effort**: 4–5 hours.

**Interview question it answers**: _"Is your sample size large enough to draw conclusions? What is your confidence interval?"_

---

### P0.3 Run Retrieval Ablations on Real Data (E1–E4)

**What**: The retrieval ablation table in README says "Not measured yet." You have the PDFs in `data/corpus/` and the evaluation code. Run the ablations and publish the numbers.

**Why it matters**: The entire README is structured around an ablation ladder. If those rows are empty, the most impressive part of the project looks unfinished.

**How**:
```bash
# With Voyage + Groq configured in .env
python -m evaluation.run_ablation --only E1,E2,E2b,E3
python -m evaluation.run_retrieval
python scripts/render_results.py
```
Write a paragraph in NOTES.md analysing which step helped, which did not, and why (look at 3 failed questions per experiment).

**Effort**: 2–3 hours (mostly waiting for embeddings + writing the analysis).

**Interview question it answers**: _"Walk me through your ablation results. Which retrieval technique had the biggest impact and why?"_

---

### P0.4 Add `mypy --strict` to CI

**What**: The codebase has 0 type errors from `tsc --noEmit` on the frontend but mypy has never been run on the backend. Add mypy as a dev dependency and fix all errors.

**Why it matters**: Type safety is a baseline expectation at Google, Meta, and any company using Python at scale. Not having it signals "hobby project."

**How**:
1. Add `mypy` and `types-*` stubs to `[project.optional-dependencies] dev` in pyproject.toml.
2. Add a `[tool.mypy]` section: `strict = true`, `plugins = ["pydantic.mypy"]`.
3. Run `mypy packages/ services/` and fix errors (expect ~50–100, mostly missing return types and untyped dicts).
4. Add `mypy packages/ services/` to the GitHub Actions workflow and the Makefile (`make typecheck`).

**Effort**: 4–6 hours.

**Interview question it answers**: _"How do you ensure type safety in a Python codebase?"_

---

## P1 — Production-Grade Engineering (1–2 weeks)

### P1.1 Structured Logging + OpenTelemetry Traces

**What**: Replace `print`/`logger.info` with structured JSON logs (one JSON object per line, with `trace_id`, `user_id`, `notebook_id`, `duration_ms`). Add OpenTelemetry spans to the critical path: `ingest → chunk → embed → store` and `query → retrieve → generate → verify → respond`.

**Why it matters**: Every big-tech system design interview asks about observability. "I added structured logging and distributed tracing" with a concrete trace waterfall diagram is a strong differentiator.

**Implementation sketch**:
```python
# packages/observability/logging.py
import structlog
import logging

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

# packages/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("citeguard")
```

Add `@tracer.start_as_current_span("hybrid_retrieve")` to key functions. Log the trace_id in every structured log line so logs and traces correlate.

**New dependencies**: `structlog`, `opentelemetry-api`, `opentelemetry-sdk` (ask before adding per CLAUDE.md).

**Effort**: 1–2 days.

**Interview question it answers**: _"How would you debug a slow query in production? How do you correlate logs across services?"_

---

### P1.2 Streaming SSE Answers

**What**: The current `/chat` endpoint waits for the full pipeline (retrieve → generate → verify) before returning. Add a `POST /notebooks/{id}/chat/stream` endpoint that uses Server-Sent Events to stream incremental updates:

```
event: status
data: {"phase": "retrieving", "chunks_found": 0}

event: status
data: {"phase": "generating"}

event: chunk
data: {"text": "The study found that"}

event: claim_verified
data: {"claim_index": 0, "status": "supported", "quote": "..."}

event: done
data: {"message_id": "...", "verified": 3, "rejected": 1}
```

**Why it matters**: Every modern AI product streams. Not streaming in 2026 looks outdated. It also demonstrates understanding of async generators, backpressure, and HTTP streaming.

**Implementation sketch**:
```python
from fastapi.responses import StreamingResponse
from starlette.responses import EventSourceResponse  # or sse_starlette

@app.post("/notebooks/{id}/chat/stream")
async def chat_stream(id: str, body: ChatRequest, user=Depends(current_user)):
    async def event_generator():
        yield {"event": "status", "data": json.dumps({"phase": "retrieving"})}
        chunks = await hybrid_retrieve(...)
        yield {"event": "status", "data": json.dumps({"phase": "generating", "chunks": len(chunks)})}
        # Stream tokens from LLM
        async for token in llm_stream(...):
            yield {"event": "chunk", "data": json.dumps({"text": token})}
        # Verify claims
        for i, claim in enumerate(claims):
            result = verify(claim)
            yield {"event": "claim_verified", "data": json.dumps({...})}
        yield {"event": "done", "data": json.dumps({...})}
    return EventSourceResponse(event_generator())
```

Frontend: use `EventSource` or `fetch` with `ReadableStream` in `apps/web/src/api.ts`.

**Effort**: 2–3 days (backend + frontend + tests).

**Interview question it answers**: _"How does your system handle long-running requests? What happens if the client disconnects mid-stream?"_

---

### P1.3 Job Claiming with Lease (SELECT FOR UPDATE SKIP LOCKED)

**What**: The current worker picks up SQS messages but doesn't prevent duplicate work if two workers poll the same message before the visibility timeout expires. Implement database-level job claiming:

```sql
UPDATE jobs
SET state = 'running', worker_id = $1, claimed_at = now()
WHERE id = (
    SELECT id FROM jobs
    WHERE state = 'queued'
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING *;
```

Add a lease timeout: if `claimed_at` is older than 10 minutes and state is still `running`, another worker can reclaim it.

**Why it matters**: This is a classic system design interview question (exactly-once processing, distributed locking, lease-based ownership). Having it implemented with real SQL is much stronger than describing it theoretically.

**Implementation sketch**:
1. Add `worker_id` (UUID) and `claimed_at` (timestamp) columns to `jobs` (migration 005).
2. Worker generates a UUID at startup and uses it for all claims.
3. Stale lease reclaim: `WHERE state = 'running' AND claimed_at < now() - interval '10 minutes'`.
4. Test: start two workers, enqueue 10 jobs, assert no job is processed twice.

**Effort**: 1 day.

**Interview question it answers**: _"How do you prevent duplicate processing in a distributed worker system? What happens when a worker crashes mid-job?"_

---

### P1.4 Circuit Breaker for External APIs

**What**: Groq and Voyage are external APIs that can fail. Implement a circuit breaker that:
- **Closed** (normal): requests go through.
- **Open** (after N consecutive failures): requests fail immediately for a cooldown period.
- **Half-open** (after cooldown): one probe request; if it succeeds, close the circuit.

```python
# packages/llm_gateway/circuit_breaker.py
import time
from dataclasses import dataclass, field

@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    _failures: int = 0
    _state: str = "closed"  # closed, open, half_open
    _opened_at: float = 0.0

    def call(self, fn, *args, **kwargs):
        if self._state == "open":
            if time.monotonic() - self._opened_at > self.cooldown_seconds:
                self._state = "half_open"
            else:
                raise CircuitOpenError(f"Circuit open, retry after {self.cooldown_seconds}s")
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        self._failures = 0
        self._state = "closed"

    def _on_failure(self):
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()
```

**Why it matters**: Circuit breakers are a top-3 distributed systems pattern. Implementing one from scratch (not importing a library) shows deep understanding.

**Effort**: 0.5 days.

**Interview question it answers**: _"How do you handle cascading failures when a downstream service goes down?"_

---

### P1.5 Rate Limiting per User

**What**: Add token-bucket rate limiting to the API. Store buckets in-process (or Redis if deployed with multiple API instances). Limits:
- Chat: 10 requests/minute per user
- Upload: 5 requests/minute per user
- Report: 2 requests/minute per user

Return `429 Too Many Requests` with a `Retry-After` header.

**Implementation sketch**:
```python
# services/api/rate_limit.py
from collections import defaultdict
import time

class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

# FastAPI middleware or dependency
_buckets: dict[tuple[str, str], TokenBucket] = defaultdict(lambda: TokenBucket(rate=10/60, capacity=10))
```

**Effort**: 0.5 days.

**Interview question it answers**: _"How would you protect your API from abuse? Design a rate limiter."_

---

### P1.6 Upload Size Cap via Presigned POST

**What**: The current presigned PUT URL has no size restriction. Switch to a presigned POST with a `content-length-range` condition (e.g., max 50 MB):

```python
presigned = s3.generate_presigned_post(
    Bucket=bucket,
    Key=key,
    Conditions=[["content-length-range", 1, 50 * 1024 * 1024]],
    ExpiresIn=300,
)
```

**Why it matters**: Without a size cap, anyone can upload a 5 GB file and crash your worker or exhaust disk. This is a security basic that interviewers expect.

**Effort**: 2–3 hours.

**Interview question it answers**: _"How do you handle file uploads securely? What prevents a user from uploading a 10 GB file?"_

---

### P1.7 Graceful Shutdown

**What**: The worker currently polls SQS in an infinite loop. On SIGTERM (container stop, deploy), it should:
1. Stop accepting new messages.
2. Finish the current job (up to a deadline).
3. Exit cleanly.

```python
import signal, asyncio

class GracefulWorker:
    def __init__(self):
        self._shutdown = asyncio.Event()
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown.set())
        signal.signal(signal.SIGINT, lambda *_: self._shutdown.set())

    async def poll_forever(self):
        while not self._shutdown.is_set():
            messages = await receive_messages(...)
            for msg in messages:
                await self.process(msg)
        logger.info("shutdown_complete", jobs_in_flight=0)
```

**Why it matters**: Demonstrates understanding of container lifecycle, zero-downtime deploys, and data integrity during restarts.

**Effort**: 3–4 hours.

**Interview question it answers**: _"What happens to in-flight requests when you deploy a new version?"_

---

## P2 — Advanced RAG & ML Engineering (2–3 weeks)

### P2.1 Cross-Encoder Reranker (E4 Ablation)

**What**: After RRF fusion returns top-20, run a cross-encoder (e.g., `BAAI/bge-reranker-v2-m3` or Cohere Rerank API) to rescore and keep top-5.

**Why it matters**: Cross-encoder reranking is the single highest-impact retrieval improvement in the RAG literature. Having an ablation showing its effect (E4 vs E3) with real numbers is a strong talking point.

**Implementation sketch**:
```python
# packages/retrieval/reranker.py
from sentence_transformers import CrossEncoder

_model = None

def get_reranker():
    global _model
    if _model is None:
        _model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
    return _model

def rerank(query: str, chunks: list[Chunk], top_k: int = 5) -> list[Chunk]:
    model = get_reranker()
    pairs = [(query, c.text) for c in chunks]
    scores = model.predict(pairs)
    ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
    return [c for c, _ in ranked[:top_k]]
```

Add a toggle in the retrieval config (`"reranker": True/False`) so the ablation runner can compare E3 (no reranker) vs E4 (with reranker).

**New dependency**: `sentence-transformers` (ask before adding per CLAUDE.md).

**Effort**: 1–2 days.

**Interview question it answers**: _"Why not just use the embedding model for ranking? What is the difference between a bi-encoder and a cross-encoder?"_

---

### P2.2 Parent-Child Chunking (E6 Ablation)

**What**: Store two chunk sizes: small (200 tokens, used for embedding/retrieval) and large "parent" chunks (800 tokens, sent to the LLM for context). When a small chunk is retrieved, the LLM sees its parent.

**Why it matters**: This is the most-discussed advanced RAG pattern in 2025–2026. Having an ablation showing whether it helps _your_ data is impressive.

**Implementation sketch**:
1. Add a `parent_id` column to the `chunks` table (migration 006, self-referential FK).
2. During ingestion, first create parent chunks (800 tokens), then split each into 2–3 children (200 tokens). Children share the parent's embedding header.
3. At retrieval time, retrieve children, then fetch their parents. Deduplicate parents.
4. Send parent text (not child text) to the LLM for generation.
5. Ablation: compare E3 (flat chunks) vs E6 (parent-child) on Recall@5 and answer quality.

**Effort**: 2–3 days.

**Interview question it answers**: _"How do you balance retrieval precision (small chunks) with generation context (large chunks)?"_

---

### P2.3 Query Decomposition Ablation (E5)

**What**: For complex queries, decompose into sub-queries before retrieval. Compare:
- E3: single query → retrieve
- E5: decompose into 2–3 sub-queries → retrieve for each → merge results → generate

```python
DECOMPOSE_PROMPT = """Break this question into 2-3 simpler sub-questions that can be answered independently.
Question: {query}
Return a JSON array of strings."""
```

**Why it matters**: Query decomposition is a standard technique in multi-hop QA. Having an ablation showing when it helps vs when it just adds latency is exactly the kind of nuanced analysis interviewers love.

**Effort**: 1–2 days.

**Interview question it answers**: _"How do you handle multi-hop questions where the answer spans multiple documents?"_

---

### P2.4 HyDE (Hypothetical Document Embeddings)

**What**: Instead of embedding the raw query, ask the LLM to generate a hypothetical answer, then embed _that_ for retrieval. Compare retrieval quality with and without HyDE.

```python
HYDE_PROMPT = """Write a short passage that would answer this question.
Do not make up facts; write in the style of an academic paper.
Question: {query}"""

hypothetical = llm_chat(HYDE_PROMPT)
query_embedding = embed(hypothetical)  # instead of embed(query)
```

**Why it matters**: HyDE bridges the vocabulary gap between questions and documents. It's a well-known technique from the Gao et al. 2022 paper that shows you follow the literature.

**Effort**: 0.5 days (simple to implement, the ablation is the valuable part).

**Interview question it answers**: _"How do you handle the vocabulary mismatch between a user's question and the document's language?"_

---

### P2.5 Experiment Tracking & Model Versioning

**What**: Add lightweight experiment tracking so every ablation run records:
- Config (which retrieval stages enabled, model names, chunk sizes)
- Metrics (Recall@k, MRR, FAR, latency, cost)
- Git commit hash
- Timestamp

Store in `results/experiments/` as timestamped JSON files. Add a script to compare any two experiments.

**Implementation sketch**:
```python
# packages/evaluation/experiment.py
import json, subprocess, datetime
from pathlib import Path

def log_experiment(name: str, config: dict, metrics: dict):
    record = {
        "name": name,
        "config": config,
        "metrics": metrics,
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    path = Path("results/experiments") / f"{name}_{record['timestamp'][:19].replace(':', '-')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    return path
```

**Why it matters**: Shows ML engineering maturity. "I version my experiments and can compare any two runs" is a strong signal at ML-focused companies.

**Effort**: 0.5 days.

**Interview question it answers**: _"How do you track experiments and ensure reproducibility?"_

---

### P2.6 Embedding Migration Tooling

**What**: When you switch embedding models (e.g., from Voyage 3.5 to a future Voyage 4.0), all chunks need re-embedding. Build a migration script that:
1. Reads all chunks for a notebook.
2. Re-embeds them with the new model.
3. Updates the embeddings in-place (or creates a new column).
4. Records the model version in the `sources` table.

```python
# scripts/migrate_embeddings.py
def migrate_embeddings(notebook_id: str, new_model: str, batch_size: int = 50):
    chunks = get_all_chunks(notebook_id)
    for batch in batched(chunks, batch_size):
        texts = [c.header_text for c in batch]
        embeddings = embed_batch(texts, model=new_model)
        update_embeddings(batch, embeddings)
    update_source_model_version(notebook_id, new_model)
```

**Why it matters**: Model migration is a real production concern. Having a script that handles it (with batching, progress, and rollback) shows you think about operational concerns.

**Effort**: 0.5 days.

**Interview question it answers**: _"What happens when you want to upgrade your embedding model? How do you handle the migration?"_

---

## P3 — Scale, Resilience & Operational Excellence (2–3 weeks)

### P3.1 Prometheus Metrics + Grafana Dashboard

**What**: Expose application metrics via a `/metrics` endpoint:

| Metric | Type | Labels |
|:---|:---|:---|
| `citeguard_requests_total` | Counter | `method`, `endpoint`, `status` |
| `citeguard_request_duration_seconds` | Histogram | `endpoint` |
| `citeguard_retrieval_chunks_returned` | Histogram | `method` (dense/sparse/hybrid) |
| `citeguard_verification_result` | Counter | `stage`, `verdict` |
| `citeguard_llm_tokens_total` | Counter | `provider`, `model`, `direction` (input/output) |
| `citeguard_llm_latency_seconds` | Histogram | `provider`, `model` |
| `citeguard_job_duration_seconds` | Histogram | `job_type` |
| `citeguard_active_jobs` | Gauge | `state` |

Add a `docker-compose.monitoring.yml` with Prometheus + Grafana and a pre-built dashboard JSON.

**Why it matters**: Metrics are the foundation of production operations. A screenshot of a Grafana dashboard in your demo video is an instant credibility booster.

**Effort**: 1–2 days.

**Interview question it answers**: _"How do you monitor your system? What alerts would you set up? How do you know if retrieval quality is degrading?"_

---

### P3.2 Redis Caching Layer

**What**: Add Redis as an optional caching layer:
1. **Query cache**: Cache (query_hash, notebook_id) → answer for identical repeated queries (TTL 1 hour).
2. **Embedding cache**: Cache chunk embeddings by content hash (supplements the disk cache).
3. **Session cache**: Store user sessions for faster auth validation.

```python
# packages/cache/redis_cache.py
import redis, hashlib, json

class QueryCache:
    def __init__(self, url: str, ttl: int = 3600):
        self.r = redis.from_url(url)
        self.ttl = ttl

    def get(self, query: str, notebook_id: str) -> dict | None:
        key = f"chat:{notebook_id}:{hashlib.sha256(query.encode()).hexdigest()}"
        val = self.r.get(key)
        return json.loads(val) if val else None

    def set(self, query: str, notebook_id: str, response: dict):
        key = f"chat:{notebook_id}:{hashlib.sha256(query.encode()).hexdigest()}"
        self.r.setex(key, self.ttl, json.dumps(response))
```

Invalidate notebook cache entries on new document upload.

**Why it matters**: Caching strategy is a system design interview staple. Having Redis in your architecture with invalidation logic shows practical experience.

**New dependency**: `redis` (ask before adding per CLAUDE.md).

**Effort**: 1 day.

**Interview question it answers**: _"Where would you add caching? How do you handle cache invalidation?"_

---

### P3.3 Load Testing with Locust

**What**: Write Locust load test scenarios that simulate realistic traffic:

```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class CiteGuardUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # Create a notebook and upload a PDF
        r = self.client.post("/notebooks", json={"title": "Load Test"},
                             headers={"X-User-Id": f"user-{self.environment.runner.user_count}"})
        self.notebook_id = r.json()["id"]

    @task(5)
    def chat(self):
        self.client.post(f"/notebooks/{self.notebook_id}/chat",
                         json={"query": "What is early stopping?"})

    @task(1)
    def generate_report(self):
        self.client.post(f"/notebooks/{self.notebook_id}/reports",
                         json={"query": "Compare approaches to early stopping"})
```

Run at 10, 50, 100 concurrent users. Record p50/p95/p99 latencies, error rates, and throughput. Publish results in RESULTS.md.

**Why it matters**: Load testing transforms "it works on my laptop" into "it handles N concurrent users with p99 < Xms." These are exactly the numbers interviewers want to hear.

**Effort**: 1 day.

**Interview question it answers**: _"What is your system's throughput? Where is the bottleneck under load?"_

---

### P3.4 Connection Pooling with PgBouncer

**What**: Add PgBouncer in front of Postgres in docker-compose. Configure transaction-mode pooling with a pool size of 20.

```yaml
# docker-compose.yml addition
pgbouncer:
  image: edoburu/pgbouncer
  environment:
    DATABASE_URL: postgres://citeguard:citeguard_dev_password@postgres:5432/citeguard
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 100
    DEFAULT_POOL_SIZE: 20
  ports:
    - "6432:6432"
```

Point the API and worker at PgBouncer (port 6432) instead of Postgres directly.

**Why it matters**: Connection management is a common production issue with PostgreSQL. Knowing about PgBouncer and configuring it correctly is a strong backend signal.

**Effort**: 3–4 hours.

**Interview question it answers**: _"How do you manage database connections at scale? What is the difference between session and transaction pooling?"_

---

### P3.5 SSRF Guard for URL Ingestion

**What**: The URL parser (`packages/ingestion/url_parser.py`) exists but no endpoint exposes it because of SSRF risk. Implement the guard:

```python
# packages/ingestion/ssrf_guard.py
import ipaddress, socket
from urllib.parse import urlparse

BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / IMDS
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fd00::/8"),
]

def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Scheme {parsed.scheme} not allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("No hostname")
    # Resolve DNS BEFORE connecting
    addrs = socket.getaddrinfo(host, parsed.port or 443)
    for _, _, _, _, sockaddr in addrs:
        ip = ipaddress.ip_address(sockaddr[0])
        for blocked in BLOCKED_RANGES:
            if ip in blocked:
                raise ValueError(f"Address {ip} is blocked (private/metadata)")
    return url
```

Then add `POST /notebooks/{id}/urls` endpoint.

**Why it matters**: SSRF is in the OWASP Top 10. Having a guard that blocks metadata endpoints (169.254.169.254) shows security awareness that most junior engineers lack.

**Effort**: 0.5 days.

**Interview question it answers**: _"What is SSRF? How do you prevent it when your application fetches user-provided URLs?"_

---

### P3.6 Dependency Scanning (pip-audit) in CI

**What**: Add `pip-audit` to the CI pipeline to check for known vulnerabilities in dependencies.

```yaml
# .github/workflows/ci.yml addition
- name: Dependency audit
  run: pip-audit --strict --desc
```

**Why it matters**: Supply chain security is a hot topic. Running `pip-audit` in CI is table stakes at any security-conscious company.

**Effort**: 1–2 hours.

**Interview question it answers**: _"How do you manage dependency security?"_

---

### P3.7 Blue-Green Deployment Script

**What**: Write a `scripts/deploy.sh` that implements blue-green deployment on EC2:
1. Pull the new image.
2. Start the new container on a different port.
3. Health-check the new container.
4. Swap the nginx/caddy upstream to the new port.
5. Drain and stop the old container.

**Why it matters**: Zero-downtime deployments are a fundamental DevOps concept. Having a working script (not just Terraform) shows you understand the mechanics.

**Effort**: 0.5 days.

**Interview question it answers**: _"How do you deploy without downtime? What is blue-green deployment?"_

---

### P3.8 Backup & Restore Automation

**What**: Add a `scripts/backup.sh` that:
1. Runs `pg_dump` with `--format=custom`.
2. Uploads to S3 with a timestamped key.
3. Rotates backups (keep last 7 daily, 4 weekly).
4. Add a `scripts/restore.sh` that downloads and restores.
5. Test: backup → drop database → restore → run `make test`.

**Why it matters**: Disaster recovery is a production essential. "I have automated backups with tested restores" is a very strong signal.

**Effort**: 0.5 days.

**Interview question it answers**: _"What is your disaster recovery plan? How do you handle data loss?"_

---

## P4 — Testing & Quality (1 week)

### P4.1 Property-Based Testing with Hypothesis

**What**: Add Hypothesis tests for the components with complex input spaces:

```python
# tests/property/test_chunker.py
from hypothesis import given, strategies as st

@given(text=st.text(min_size=100, max_size=10000))
def test_chunks_cover_entire_text(text):
    """Every character in the input appears in exactly one chunk."""
    chunks = structure_aware_chunk(text, min_tokens=50, max_tokens=100, overlap=0)
    reconstructed = "".join(c.text for c in chunks)
    # Allow slight differences due to overlap handling
    assert len(reconstructed) >= len(text) * 0.95

@given(text=st.text(min_size=50, max_size=5000))
def test_chunk_offsets_are_valid(text):
    """Every chunk's offsets round-trip correctly."""
    chunks = structure_aware_chunk(text, min_tokens=50, max_tokens=100, overlap=20)
    for chunk in chunks:
        assert text[chunk.start:chunk.end] == chunk.text
```

Also add property tests for the verifier (random number perturbations should always be caught) and RRF (output is a valid permutation of inputs).

**Why it matters**: Property-based testing shows sophisticated testing thinking. "My chunker is correct for _any_ input, not just my three test cases" is powerful.

**New dependency**: `hypothesis` (ask before adding per CLAUDE.md).

**Effort**: 1 day.

**Interview question it answers**: _"How do you test components with large or infinite input spaces?"_

---

### P4.2 Contract Tests for the API

**What**: Write contract tests that validate the API response schemas match what the frontend expects. Use `schemathesis` or manual Pydantic validation:

```python
# tests/contract/test_api_contracts.py
from pydantic import BaseModel

class ChatResponseContract(BaseModel):
    message_id: str
    answer: str
    claims: list[dict]
    tokens_used: int
    cost_usd: float

def test_chat_response_matches_contract(client, notebook_with_source):
    r = client.post(f"/notebooks/{notebook_with_source}/chat", json={"query": "test"})
    assert r.status_code == 200
    ChatResponseContract(**r.json())  # Pydantic validates the shape
```

**Why it matters**: Contract testing prevents the classic problem of backend changes breaking the frontend. It shows awareness of API evolution and backward compatibility.

**Effort**: 0.5 days.

**Interview question it answers**: _"How do you ensure API changes don't break clients?"_

---

### P4.3 Chaos Testing (Kill Worker Mid-Job)

**What**: Write a test that:
1. Starts an ingestion job.
2. Kills the worker process after the first chunk is stored.
3. Restarts the worker.
4. Asserts: the job completes, no chunks are duplicated (SHA-256 dedup), the job state is correct.

```python
# tests/chaos/test_worker_crash.py
def test_worker_crash_and_recovery(worker_process, s3, sqs, db):
    # Upload and enqueue
    job_id = create_ingestion_job(db, s3, sqs, "test.pdf")
    # Wait for partial processing
    wait_until(lambda: count_chunks(db, job_id) > 0, timeout=30)
    # Kill worker
    worker_process.terminate()
    worker_process.wait()
    # Restart
    new_worker = start_worker()
    # Wait for completion
    wait_until(lambda: get_job_state(db, job_id) == "completed", timeout=60)
    # Assert no duplicates
    chunks = get_chunks(db, job_id)
    hashes = [c.content_hash for c in chunks]
    assert len(hashes) == len(set(hashes))
```

**Why it matters**: Chaos engineering shows you think about failure modes, not just happy paths. This is a strong senior/staff-level signal.

**Effort**: 1 day.

**Interview question it answers**: _"What happens when a worker crashes mid-job? How do you ensure data consistency?"_

---

### P4.4 End-to-End Browser Tests with Playwright

**What**: Write Playwright tests that drive the full UI flow:

```typescript
// tests/e2e/full-flow.spec.ts
test('upload PDF, ask question, see verified claims', async ({ page }) => {
  await page.goto('http://localhost:5173');
  await page.fill('[data-testid="username"]', 'test-user');
  await page.click('[data-testid="sign-in"]');

  // Create notebook
  await page.click('[data-testid="new-notebook"]');
  await page.fill('[data-testid="notebook-title"]', 'E2E Test');

  // Upload PDF
  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.click('[data-testid="upload-area"]');
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles('tests/fixtures/sample.pdf');
  await page.waitForSelector('[data-testid="upload-done"]');

  // Chat
  await page.fill('[data-testid="chat-input"]', 'What is early stopping?');
  await page.click('[data-testid="send"]');
  await page.waitForSelector('[data-testid="claim-badge"]');

  // Verify claim badge
  const badge = page.locator('[data-testid="claim-badge"]').first();
  await expect(badge).toHaveText(/verified/i);
});
```

**Why it matters**: E2E browser tests are the final verification layer. Having them run in CI (with screenshots on failure) shows production-level QA.

**Effort**: 1–2 days.

**Interview question it answers**: _"How do you test the full user flow? What does your testing pyramid look like?"_

---

## P5 — Documentation & Presentation (3–5 days)

### P5.1 Architecture Decision Records (ADRs)

**What**: Create `docs/adr/` with lightweight ADR documents for key decisions:

| ADR | Title |
|:---|:---|
| 001 | Use plain Python state machine instead of LangGraph |
| 002 | Two-stage verification (deterministic + LLM) |
| 003 | RRF fusion instead of learned fusion |
| 004 | SQS + DLQ instead of Redis/arq |
| 005 | Presigned uploads instead of multipart through the API |
| 006 | Cognito for auth instead of custom JWT |
| 007 | Single EC2 instance instead of ECS/Fargate |

Format per ADR:
```markdown
# ADR-001: Plain Python State Machine

## Status: Accepted
## Context: We need a report agent that plans sub-questions, retrieves, verifies, and composes.
## Decision: Use a plain Python state machine with explicit state transitions, not LangGraph or CrewAI.
## Consequences:
- (+) No framework dependency, full control over budget enforcement
- (+) Every state transition is testable in isolation
- (+) Easy to explain in interviews
- (-) More boilerplate for adding new agent capabilities
```

**Why it matters**: ADRs show you make decisions deliberately, not by default. Google interviewers specifically look for "why did you choose X over Y?" ADRs are the prepared answer.

**Effort**: 3–4 hours.

**Interview question it answers**: _"Why did you build your own agent instead of using LangGraph? Why SQS instead of Redis?"_

---

### P5.2 System Design Diagrams (C4 Model)

**What**: Create C4-level diagrams in Mermaid:

1. **Context**: CiteGuard, User, External APIs (Groq, Voyage, AWS)
2. **Container**: API, Worker, Postgres, SQS, S3, CloudFront, Cognito
3. **Component**: Inside the API — retrieval, generation, verification, agent modules
4. **Code**: Class diagram of the verification pipeline

Store in `docs/diagrams/` and embed in README.

**Why it matters**: System design diagrams at multiple zoom levels show you can communicate architecture clearly — a critical skill for senior roles.

**Effort**: 3–4 hours.

**Interview question it answers**: _"Draw the architecture of your system. Now zoom into the retrieval layer."_

---

### P5.3 Latency Breakdown Waterfall

**What**: Measure and document the end-to-end latency breakdown for a single chat query:

```
┌─────────────────────────────────────────────────────────────────┐
│ Total: ~3200ms                                                   │
├──────────┬──────────┬───────────┬──────────┬──────────┬─────────┤
│ Query    │ Embed    │ Retrieve  │ Generate │ Verify   │ Store   │
│ rewrite  │ query    │ hybrid    │ answer   │ claims   │ result  │
│ ~400ms   │ ~200ms   │ ~50ms     │ ~1800ms  │ ~700ms   │ ~50ms   │
└──────────┴──────────┴───────────┴──────────┴──────────┴─────────┘
```

Instrument each stage with `time.perf_counter()` and log the breakdown. Add a `/debug/latency` endpoint (dev only) that returns the last N query breakdowns.

**Why it matters**: "LLM generation is 56% of our latency; retrieval is only 1.5%" — this kind of analysis shows you profile before optimizing.

**Effort**: 3–4 hours.

**Interview question it answers**: _"Where is the bottleneck in your pipeline? How would you reduce latency?"_

---

### P5.4 Cost Analysis per Query

**What**: Complete the `usage_ledger` integration. Track and display:

| Operation | Cost |
|:---|:---|
| Embed query (Voyage) | ~\$0.00001 |
| LLM generate (Groq) | ~\$0.0003 |
| LLM verify (Groq, per claim) | ~\$0.0001 |
| LLM rewrite (Groq, follow-up only) | ~\$0.0002 |
| **Total per chat query** | **~\$0.0006** |
| **Total per report (4 sub-questions)** | **~\$0.003** |

Write actual costs to `usage_ledger` (the table exists but nothing writes to it). Show accumulated cost per notebook in the UI.

**Why it matters**: Cost awareness separates production ML from demos. "Each query costs \$0.0006" is a powerful number in interviews.

**Effort**: 0.5 days.

**Interview question it answers**: _"What does it cost to run your system? How would you reduce costs?"_

---

### P5.5 Failure Mode Analysis Document

**What**: Create `docs/failure-modes.md` documenting every known failure mode and its mitigation:

| Failure | Impact | Detection | Mitigation |
|:---|:---|:---|:---|
| Groq API down | No answers | Circuit breaker opens | Return 503 with reason; queue and retry |
| Voyage API down | No embeddings | Circuit breaker | Reject uploads with retry-after |
| Postgres full disk | All writes fail | Disk usage alert | Auto-vacuum, PgBouncer limits |
| Worker OOM on large PDF | Job stuck | Health check timeout | Limit PDF size, stream pages |
| SQS message lost | Job never processed | Job age monitoring | DLQ + alerting |
| Stale embedding model | Retrieval quality degrades | A/B metric comparison | Embedding migration script |
| Concurrent report jobs | Duplicate work | Unique index violation | SELECT FOR UPDATE SKIP LOCKED |

**Why it matters**: Thinking about failure modes proactively is a staff-level habit. This document is excellent interview preparation material.

**Effort**: 2–3 hours.

**Interview question it answers**: _"What can go wrong? How do you handle X failure?"_

---

## Implementation Roadmap

Prioritized by interview impact per hour of effort:

### Week 1: Credibility Foundations
| Day | Task | Effort |
|:---|:---|:---|
| 1 | P0.1 Human-review golden labels | 4h |
| 1 | P0.2 Grow golden set to 50+ | 4h |
| 2 | P0.3 Run retrieval ablations (E1–E4) | 3h |
| 2 | P0.4 Add mypy --strict | 5h |

### Week 2: Production Engineering
| Day | Task | Effort |
|:---|:---|:---|
| 1 | P1.3 Job claiming with lease | 8h |
| 2 | P1.1 Structured logging + OTel traces | 8h |
| 3 | P1.4 Circuit breaker | 4h |
| 3 | P1.5 Rate limiting | 4h |
| 4 | P1.6 Upload size cap | 3h |
| 4 | P1.7 Graceful shutdown | 4h |
| 5 | P3.5 SSRF guard + URL endpoint | 4h |
| 5 | P3.6 pip-audit in CI | 1h |

### Week 3: Advanced RAG
| Day | Task | Effort |
|:---|:---|:---|
| 1–2 | P2.1 Cross-encoder reranker (E4) | 12h |
| 3 | P2.2 Parent-child chunking (E6) | 8h |
| 4 | P2.3 Query decomposition (E5) | 8h |
| 5 | P2.4 HyDE | 4h |
| 5 | P2.5 Experiment tracking | 4h |

### Week 4: Testing & Ops
| Day | Task | Effort |
|:---|:---|:---|
| 1 | P1.2 Streaming SSE answers | 12h |
| 2 | P4.1 Property-based tests | 8h |
| 3 | P3.1 Prometheus metrics | 8h |
| 4 | P3.3 Load testing with Locust | 8h |
| 5 | P4.3 Chaos testing | 8h |

### Week 5: Documentation & Polish
| Day | Task | Effort |
|:---|:---|:---|
| 1 | P5.1 ADRs | 4h |
| 1 | P5.2 C4 diagrams | 4h |
| 2 | P5.3 Latency waterfall | 4h |
| 2 | P5.4 Cost analysis + usage_ledger | 4h |
| 3 | P5.5 Failure mode analysis | 3h |
| 3 | P4.4 Playwright E2E tests | 8h |
| 4–5 | P3.7 Blue-green deploy | 4h |
| 4–5 | P3.8 Backup & restore | 4h |
| 4–5 | P3.2 Redis caching layer | 8h |

---

## Interview Questions This Project Answers

After implementing the items above, you can confidently answer:

### System Design
1. _"Design a document Q&A system with verified citations"_ — the entire project
2. _"How do you prevent duplicate processing?"_ — P1.3 job claiming
3. _"How do you handle cascading failures?"_ — P1.4 circuit breaker
4. _"Design a rate limiter"_ — P1.5 token bucket
5. _"How do you deploy without downtime?"_ — P3.7 blue-green
6. _"Where would you add caching?"_ — P3.2 Redis layer
7. _"How do you monitor production systems?"_ — P3.1 Prometheus + P1.1 OTel

### ML / AI
8. _"How do you evaluate RAG quality?"_ — ablation ladder E1–E8
9. _"What is the difference between bi-encoder and cross-encoder?"_ — P2.1
10. _"How do you handle hallucinations?"_ — two-stage verification
11. _"When is an agent better than single-shot?"_ — E8 analysis (NOTES.md)
12. _"How do you handle vocabulary mismatch?"_ — P2.4 HyDE
13. _"How do you track ML experiments?"_ — P2.5 experiment tracking

### Backend / Security
14. _"How do you handle file uploads securely?"_ — P1.6 presigned POST
15. _"What is SSRF?"_ — P3.5 guard
16. _"How do you manage database connections?"_ — P3.4 PgBouncer
17. _"How do you test?"_ — P4.1 property tests, P4.3 chaos tests, P4.4 Playwright

### Behavioral
18. _"Tell me about a technical decision you made and why"_ — ADRs (P5.1)
19. _"What was a failure you encountered?"_ — T3.6 verifier failure analysis
20. _"How do you handle trade-offs?"_ — agent wins vs costs analysis (NOTES.md)

---

## What NOT to Build

These are common traps that waste time without interview value:

| Trap | Why to skip |
|:---|:---|
| Fine-tuning an LLM | You have no training data and no GPU budget. Use prompting. |
| Knowledge graph | Adds complexity without clear retrieval benefit for your corpus size |
| Multi-agent orchestration | Your bounded single agent is _more_ impressive than a LangGraph chain |
| DOCX/PPTX parsing | Low interview value; PDF is sufficient |
| Real-time collaboration | Way out of scope; adds WebSocket complexity for no signal |
| Mobile app | Web UI is sufficient for a backend/ML project |
| Audio overview | Cannot beat NotebookLM; compete on trust instead |
| Kubernetes | Overkill for single-instance; Terraform + Docker Compose is honest |

