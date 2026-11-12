# CiteGuard Failure Modes & Mitigation Analysis

This document catalogs known failure modes across CiteGuard's RAG, verification, ingestion, and agent systems, detailing detection mechanisms, operational blast radiuses, and mitigation strategies.

---

## 1. Downstream AI & External Provider Failures

### 1.1 Provider Rate Limiting (HTTP 429 Too Many Requests)
- **Symptom**: External model APIs (Groq, Voyage AI, Bedrock) reject requests with HTTP 429.
- **Root Cause**: High concurrency, batch evaluation runs, or exceeding free-tier tokens/minute.
- **Detection**: Caught by provider clients checking status code 429 and `Retry-After` headers.
- **Mitigation**:
  1. Exponential backoff and retry loop (up to 5 attempts) reading the `Retry-After` header.
  2. In-memory and disk cache prevents redundant LLM and embedding calls during eval and testing.
  3. Per-user token bucket rate limiter (`services/api/rate_limit.py`) throttles incoming traffic before reaching paid APIs.

### 1.2 Downstream Provider Outage or Cascading Failure
- **Symptom**: External API hangs, returns 502/503/504, or drops connections repeatedly.
- **Blast Radius**: Chat and Report endpoints block and tie up API worker threads.
- **Detection**: `CircuitBreaker` tracks consecutive failures.
- **Mitigation**:
  1. `CircuitBreaker` (`packages/llm_gateway/circuit_breaker.py`) trips from `CLOSED` to `OPEN` after 5 consecutive failures.
  2. Fast-fails subsequent requests immediately with `CircuitOpenError` (HTTP 503 + `Retry-After: 30`) without invoking downstream network calls.
  3. Probes the service during `HALF_OPEN` state after a 30-second cooldown.

---

## 2. Ingestion & Storage Vulnerabilities

### 2.1 Server-Side Request Forgery (SSRF) via URL Ingestion
- **Symptom**: Attacker submits internal URLs (`http://169.254.169.254/latest/meta-data`, `http://10.0.0.1/admin`, `http://localhost:5432`) to exfiltrate cloud credentials or port-scan internal networks.
- **Detection**: Pre-fetch URL validation in `packages/ingestion/ssrf_guard.py`.
- **Mitigation**:
  1. Whitelists only `http` and `https` schemes.
  2. Resolves DNS *before* connection to detect DNS rebinding.
  3. Rejects any IP address falling in RFC 1918 private subnets, loopback (`127.0.0.0/8`, `::1`), link-local/IMDS (`169.254.0.0/16`), or ULA IPv6 (`fc00::/7`).
  4. Returns HTTP 400 with a detailed security rejection message.

### 2.2 Upload Denial of Service (Decompression / Memory Bomb)
- **Symptom**: User uploads a 5 GB multi-layer PDF designed to exhaust server disk or RAM.
- **Mitigation**:
  1. Client-side rejection for files > 50MB.
  2. API `CreateUploadRequest` validates `file_size_bytes <= 50MB` via Pydantic bounds (HTTP 422).
  3. Worker checks disk size of downloaded file (`stat().st_size <= 50MB`) before invoking PyMuPDF.

### 2.3 Scanned PDFs Without Text Layer
- **Symptom**: Uploaded PDF contains scanned bitmap images with zero extractable text.
- **Mitigation**:
  1. `packages/ingestion/pdf_parser.py` validates text character count per page.
  2. Raises `NoTextLayerError` and refuses the document with a clear user-facing error rather than generating empty chunks.

---

## 3. Worker & Asynchronous Job Failures

### 3.1 Worker Process Termination Mid-Job (SIGKILL / OOM / Host Reboot)
- **Symptom**: Worker crashes while embedding chunks or composing a report.
- **Blast Radius**: In-flight job row remains marked `running`.
- **Mitigation**:
  1. **SQS Visibility Timeout**: SQS message is not deleted until `run_job` succeeds. After 300 seconds, SQS makes the message visible to another worker.
  2. **Single Transaction Ingestion**: `packages/ingestion/pipeline.py` executes source insertion, page records, and chunk vectors within one database transaction. An uncommitted crash rolls back completely, preventing orphaned chunks.
  3. **Content-Hash Deduplication**: Chunks and sources store SHA-256 hashes. Redelivered jobs skip previously processed sources without duplicating vectors.
  4. **Graceful Shutdown**: Worker registers `SIGINT`/`SIGTERM` handlers to finish active tasks before exiting during deployments.

### 3.2 Persistent Job Failure / Poison Pill Message
- **Symptom**: A corrupt PDF repeatedly crashes the worker parser.
- **Mitigation**:
  1. `Job.retries` counter increments on each attempt.
  2. After 3 failed attempts (`MAX_RETRIES`), job state transitions to `failed` and SQS routes the message to the Dead Letter Queue (DLQ).
  3. Prevents infinite retry loops and alerts operators via DLQ CloudWatch alarms.

---

## 4. Verification & Grounding Hallucination Modes

### 4.1 Numerical Perturbation & Scope Drift
- **Symptom**: LLM generates plausible text but alters numbers ("14.2%" -> "15.0%"), changes units, or inverts dates.
- **Mitigation**:
  1. Stage 1 deterministic verification extracts and normalizes numbers, units, and dates from both the claim and the source quote.
  2. Requires exact equality unless the claim contains explicit approximation qualifiers ("about", "~").
  3. Altered claims are immediately rejected at Stage 1 with zero LLM cost.

### 4.2 Hallucinated Citations & Out-of-Bounds Offsets
- **Symptom**: LLM invents quotes that do not exist or cites non-existent chunk IDs.
- **Mitigation**:
  1. The LLM is constrained to output *chunk IDs only*; the backend code resolves the quote text, page number, and offsets directly from the retrieved database records.
  2. Stage 1 checks verify `page_text[start:end] == chunk.text`. Hallucinated IDs are discarded immediately.
  3. If zero claims survive verification, the system honestly abstains with *"The sources do not say."*

---

## 5. Multi-Tenant Data Isolation

### 5.1 Cross-User Data Leaks
- **Symptom**: User A retrieves or modifies User B's sources, conversations, or chunks.
- **Mitigation**:
  1. Every database query in `packages/retrieval/repository.py` strictly filters by both `user_id` AND `notebook_id`.
  2. Verified via automated security regression tests (`tests/security/test_cross_user.py`).
  3. API endpoints enforce `owned_notebook()` checks, returning HTTP 403 on tenant boundary mismatches.

