# Design Doc vs. Code

_Updated 2026-11-07 after the full-repo audit and fix pass. "Tested" means a test that fails if it breaks; DB tests run on real Postgres._

| Design claim (Project.txt) | In code? | Where | Notes |
| :--- | :--- | :--- | :--- |
| Redis / arq queue | No, by design | - | SQS only (LocalStack locally). |
| LangGraph / Postgres checkpointer | No, by design | - | Plain state machine, steps stored in `agent_steps`. |
| PDF parse, offset-exact chunker, refuse scanned PDFs | Yes, tested | `packages/ingestion/` | `page_text[start:end] == chunk.text` is tested on real PDFs. |
| Contextual headers (embed header, store plain text) | Yes, tested | `packages/ingestion/pipeline.py` | |
| Postgres schema, Alembic, HNSW + GIN indexes | Yes, tested | `migrations/` | Migrations 001+002 are applied to a fresh Postgres in every test run. `agent_runs` is not a table: the `jobs` row is the run. |
| Tenant isolation (`user_id` AND `notebook_id`) | Yes, tested | `packages/retrieval/repository.py` | Cross-user tests for dense, sparse, get and list, on Postgres. |
| Hybrid retrieval: pgvector + full-text + RRF (k=60) | Yes, tested | `packages/retrieval/hybrid.py` | Needs Bedrock Titan for query embeddings outside tests. |
| Cross-encoder reranker (E4) | **No** | - | Planned. Needs `sentence-transformers`; ask before adding. |
| Query-rewrite ablation (E5), parent-child (E6) | **No** | - | Query rewriting itself exists in chat; the ablations need multi-turn data / unbuilt code. |
| LLM gateway: Bedrock + Groq fallback, disk cache, cost | Yes, tested (fake provider) | `packages/llm_gateway/` | Never fakes a model: raises when unconfigured. Bedrock calls are written but **not run against AWS**. Bedrock model IDs are defaults to confirm. |
| `usage_ledger` writes | **No** | - | Cost is metered in memory (used by evaluation). Table exists, nothing writes to it. |
| Grounded generation, code-resolved quotes, abstention | Yes, tested | `packages/retrieval/generation.py` | |
| Two-stage verification + escalation | Yes, tested | `packages/verification/` | Stage 2 only run with a configured LLM. |
| Rejected claims removed from the answer text | Yes, tested | `pipeline.py` | |
| Bounded Report Agent (budgets include verification calls, report from verified claims only) | Yes, tested | `packages/agent/` | |
| API: notebooks, presigned upload, jobs, chat, reports, trace | Yes, tested | `services/api/main.py` | State in Postgres. S3/SQS calls are faked in tests, not run against LocalStack. |
| Cognito auth | Yes, tested (Cognito faked) | `services/api/auth.py` | Token validated with Cognito `GetUser`; not run against a real user pool. `AUTH_MODE` has no default. |
| SQS worker: retries, duplicate delivery, DLQ | Yes, tested | `services/worker/` | DLQ itself is queue config (Terraform, Planned). |
| URL ingestion endpoint | **No** | `packages/ingestion/url_parser.py` | Parser exists; no endpoint until there is an SSRF guard. |
| Evaluation on real corpus (E1, E2, E2b, E3, E7, E8) | Code yes, **numbers no** | `packages/evaluation/` | Refuses to run without PDFs in `data/corpus/` and an LLM. No retrieval number exists yet. |
| 50+ golden questions, 175 verifier pairs, written by hand | **No** | `data/` | 28 dev + 40 test questions and 15 pairs, all generated, about invented documents. Needs your work (roadmap T1.5). |
| CI quality gate | Yes, tested | `scripts/check_ci_gate.py` | Checks Project.txt targets (FAR <= 0.02 is required in CI). |
| Terraform deployment | **No** | `infra/terraform/` | Empty. |
| React + Vite UI | **No** | `apps/web/` | Empty. |

---

# Hardening pass (2026-11-08, branch `hardening/ultimate-pass`)

Project type: backend API + SQS worker + evaluation pipeline. Domains not audited: frontend (`apps/web` is empty), IaC (`infra/terraform` is empty), performance (nothing measured, no obvious hotspot).

**Assumptions:** `main` had 60 uncommitted changes (the 2026-11-07 fix pass). They were committed unchanged as the branch's first commit (`849cf75`) so that each fix below builds on its own. Typecheck (mypy) and dependency audit (pip-audit) were **not run**: adding them needs a new dev dependency, and the owner declined.

## Baseline (before)
- `ruff check .`: All checks passed.
- `pytest -q` with Postgres: 89 passed, 0 skipped. Without Postgres: 71 passed, 18 skipped.
- `pip install -e ".[dev]"` in a clean venv: **failed** (setuptools flat-layout discovery). Only worked on a machine that already had the dependencies installed.

## Findings
| P | Where | Problem | Impact | Fix (commit) |
|---|---|---|---|---|
| P0 | `pyproject.toml` | No package list; setuptools refuses the flat layout | Documented install and the CI install step fail | `[tool.setuptools.packages.find]` (`141b67b`) |
| P1 | `packages/verification/pipeline.py:106` | Every caller builds `VerificationPipeline()` without a `large_provider`, so escalation (Project.txt line 120) never ran outside tests | Claims the small model rejects are never retried on the large model | No provider now means the gateway's large model (`daf449c`) |
| P1 | `packages/agent/report_agent.py` budget check | Budget checked once before a claim, but verification can make 2 calls | 13 calls against a cap of 12 (hard rule) whenever escalation runs | Reserve a call for escalation (`f3124ad`) |
| P1 | `services/api/main.py` request models | No length/emptiness bounds | 256-char notebook title → DataError → 500; an empty query makes a paid LLM call | Pydantic `Field` bounds matching the DB columns (`4479337`) |
| P1 | `services/worker/main.py`, `reports.job_id` | Concurrent redelivery of a report job inserts two reports | `GET /jobs/{id}` raises MultipleResultsFound → permanent 500 | Migration 003 unique index; `run_job` keeps a job another worker completed (`4a34512`) |
| P2 | `services/api/main.py` | `LLMNotConfiguredError` → bare 500 | Opaque error for a config problem | Exception handler → 503 with the reason (`16cf11b`) |
| P2 | `services/worker/main.py:62`, `migrations/env.py:12` | `print(exc)` dropped the traceback; Alembic `fileConfig` disabled existing loggers when run in-process | Failed jobs undiagnosable | `logger.exception`, `disable_existing_loggers=False` (`f2e5ca2`) |
| P2 | `services/api/main.py` `start_job` | Any job could be started again, including completed ones and report jobs (already queued when created) | Duplicate SQS messages and duplicate work | 409 unless the job is a queued upload (`b9de77d`) |
| P2 | `services/api/main.py` `current_user` | Two concurrent first requests both insert the user row | The slower request gets IntegrityError → 500 | Roll back and load the row (`6784a63`) |
| P2 | `services/worker/main.py` `run_job` | A job already marked `failed` runs again on each SQS redelivery | Retries counted past MAX_RETRIES; a failed job could flip back to running | Skip `failed` like `completed` (`e0a46bd`) |
| P2 | `services/worker/main.py` `poll_forever` | A botocore error from `receive_message` ends the loop | One network blip stops the worker | Log, wait 5s, retry (`43e6c68`) |
| P3 | repo root, README | No `.env.example` or env-var docs | Setup means grepping the code | `.env.example` + README table (`5a328bf`) |

## Verification gates (after)
| Gate | Result |
|---|---|
| Fresh install (clean venv, `pip install -e ".[dev]"`) | Pass (failed before) |
| Lint (`ruff check .`) | 0 errors |
| Typecheck | Not run (mypy declined) |
| Tests (Postgres, fresh venv) | 102 passed, 0 failed, 0 skipped (was 89); 2 consecutive runs, no flakes |
| Coverage (`--cov=packages --cov=services`) | 90% overall; API 94%, worker 92%, verifier pipeline covered on every branch |
| Migrations | `upgrade head → downgrade base → upgrade head → downgrade -1 → upgrade head` on a scratch DB: all OK |
| App start + flow (uvicorn, `AUTH_MODE=local`) | `POST /notebooks` 201, 256-char title 422, chat with no LLM 503, other user 403 |
| End-to-end ingest → chat → report | **Run live**: real uvicorn + worker processes, LocalStack S3/SQS, Postgres; only model calls faked (no Bedrock creds). 18/18 checks: presigned PUT, SQS-driven ingestion, verified chat, report + trace, 403 for another user, 409/422 guards, missing S3 object → logged retry |
| CI eval gate (`runner` + `check_ci_gate.py`) | All checked targets met |
| Secrets in branch / full history | None found (pattern scan for AKIA, gsk_, private keys) |
| Dependency audit | Not run (pip-audit declined) |

Remaining warning: Starlette's TestClient asks for `httpx2` (upstream deprecation; switching adds a dependency).

## Deferred
- Upload size cap: needs a presigned POST with a `content-length-range` condition.
- Dockerfile/Terraform/web UI: already under Planned.

- P3: when two sub-questions produce the same claim, the report lists it twice (seen in the live run). Cosmetic; dedupe in `render_report` if it shows up with a real model.

## Next steps (by impact)
1. Run `make eval` on real PDFs with Bedrock to get the first retrieval numbers. None exist yet.
2. Replace the generated golden set and verifier pairs with human-written ones (roadmap T1.5).
3. Add mypy + pip-audit to CI (dev-only dependencies, needs approval).
4. Job claiming with a lease (`UPDATE ... WHERE state='queued'`, plus takeover of stale `running` jobs) to stop duplicate work.
5. Upload size cap via presigned POST, then the SSRF-guarded URL ingestion endpoint.
