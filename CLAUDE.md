# CiteGuard

Source-grounded research workspace: every claim is verified against an exact source quote, or the system abstains. Includes one bounded Report Agent.

- Design and scope: `Project.txt` (source of truth for architecture, schema, metrics)
- Task list and prompts: `roadmap.txt` (do tasks in order; one task per session, one commit per task)
- Decisions log: `NOTES.md` (append one line per task: what was decided and why)

## Stack
Python 3.12, FastAPI, PostgreSQL 16 + pgvector, SQS + S3 (LocalStack locally), Bedrock (Groq fallback), React + Vite + TypeScript, Terraform, Docker Compose.

## Commands
- `make up` – start postgres + localstack
- `make test` – `pytest -q`
- `make lint` – `ruff check .`
- `make eval` – run eval scripts, write `results/results.json`

## Layout
`services/api`, `services/worker`, `packages/{ingestion,retrieval,verification,agent,evaluation,llm_gateway}`, `apps/web`, `infra/terraform`, `tests/{unit,integration,security,evaluation}`, `data/{golden,verifier}`.

## Hard rules
- Never hardcode metrics. README/RESULTS.md numbers come only from `results/results.json`, rendered by `scripts/render_results.py`.
- Every SQL query on chunks, sources, messages or reports filters by `user_id` AND `notebook_id`.
- The LLM returns chunk IDs only. Quotes, pages and offsets are resolved by code.
- Numbers, dates and units in claims must match exactly after normalization (tolerance only for "about"/"approximately"/"~").
- The Report Agent is a plain Python state machine with enforced budgets (≤4 sub-questions, 1 retry each, ≤12 LLM calls, token cap). No agent frameworks.
- Do not add dependencies or frameworks (LangChain, LangGraph, CrewAI, Redis, etc.) without asking.
- Never edit `data/golden/` or `data/verifier/` labels. Those are human-labelled; propose changes instead.
- Never tune on the test split. Eval during development uses the dev split.
- Secrets come from env vars locally and SSM in prod. Never commit keys.

## How to work
- Write the failing test first. A task is done only when `make test` and `make lint` pass.
- Plan first for any change touching more than 3 files, and wait for approval.
- Smallest change that fully solves the task. No abstractions or options "for later".
- Unfinished features go under "Planned" in the README, never described as working.
- LLM calls in tests use a fake provider; eval uses the disk cache, so reruns are free.
- Do not run `terraform apply` or any command that creates AWS resources. Only `validate` and `plan`.
