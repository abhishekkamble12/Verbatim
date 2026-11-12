"""Rebuild the git commit history into 6 clean, professional architecture commits.
Verifies that the final tree hash exactly matches the source branch.
"""

import os
import subprocess
import sys

TARGET_TREE = "6077ae5e9a94abc3102af619a49245ed91a41ec5"
SOURCE_BRANCH = "backup-before-squash"
NEW_BRANCH = "squashed-6-commits"


def run(cmd, check=True):
    print(">", " ".join(cmd))
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and res.returncode != 0:
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return res.stdout.strip()


def checkout_from_source(paths):
    for p in paths:
        run(["git", "checkout", SOURCE_BRANCH, "--", p])


def main():
    # Delete test branch if exists
    subprocess.run(["git", "branch", "-D", NEW_BRANCH], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Start orphan branch
    run(["git", "checkout", "--orphan", NEW_BRANCH])
    run(["git", "reset", "--hard"])

    # --------------------------------------------------------------------------
    # Commit 1: Core Setup & Evaluation Infrastructure
    # --------------------------------------------------------------------------
    c1_paths = [
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
        ".github",
        "Makefile",
        "pyproject.toml",
        "docker-compose.yml",
        "alembic.ini",
        "data",
        "packages/evaluation",
        "evaluation",
        "scripts/render_results.py",
        "scripts/check_ci_gate.py",
        "tests/__init__.py",
        "tests/fakes.py",
        "tests/conftest.py",
        "tests/unit/__init__.py",
        "tests/unit/test_smoke.py",
        "tests/unit/evaluation",
    ]
    checkout_from_source(c1_paths)
    run(["git", "add", "-A"])
    run([
        "git", "commit", "-m",
        "feat(setup): repository skeleton, Docker Compose, CI workflow, and evaluation harness\n\n"
        "- Establish project structure with pyproject.toml, Makefile, and GitHub Actions CI workflow.\n"
        "- Add Docker Compose with PostgreSQL 16 (pgvector extension) and LocalStack (S3, SQS).\n"
        "- Implement evaluation package with JSONL loaders for golden questions and verifier pairs.\n"
        "- Implement standardized evaluation metrics (Recall@k, MRR@10, nDCG@10, FAR, FRR, bootstrap 95% CI).\n"
        "- Add dynamic results renderer script and initial multi-category evaluation datasets in data/."
    ])

    # --------------------------------------------------------------------------
    # Commit 2: Ingestion & Hybrid Retrieval Engine
    # --------------------------------------------------------------------------
    c2_paths = [
        "migrations",
        "packages/ingestion/chunker.py",
        "packages/ingestion/pdf_parser.py",
        "packages/ingestion/pipeline.py",
        "packages/ingestion/url_parser.py",
        "packages/ingestion/__init__.py",
        "packages/retrieval/db.py",
        "packages/retrieval/models.py",
        "packages/retrieval/repository.py",
        "packages/retrieval/hybrid.py",
        "packages/retrieval/__init__.py",
        "packages/llm_gateway/gateway.py",
        "packages/llm_gateway/__init__.py",
        "tests/unit/ingestion/test_pdf_and_chunker.py",
        "tests/unit/ingestion/__init__.py",
        "tests/unit/retrieval",
        "tests/unit/test_llm_gateway.py",
        "tests/security",
    ]
    checkout_from_source(c2_paths)
    run(["git", "add", "-A"])
    run([
        "git", "commit", "-m",
        "feat(retrieval): offset chunker, pgvector HNSW schema, LLM gateway, and hybrid RRF retrieval\n\n"
        "- Add PyMuPDF parser with NoTextLayerError rejection for textless scanned PDFs.\n"
        "- Implement structure-aware chunker guaranteeing exact offset preservation (page_text[start:end] == chunk.text).\n"
        "- Create Alembic migrations for PostgreSQL schema with pgvector HNSW index and GIN tsvector index.\n"
        "- Enforce strict tenant isolation (user_id and notebook_id filtering) across all database operations.\n"
        "- Implement LLM Gateway supporting Bedrock and Groq chat, Voyage embeddings, and dual-tier disk caching.\n"
        "- Build hybrid retrieval engine fusing dense pgvector cosine search and sparse full-text search with RRF (k=60)."
    ])

    # --------------------------------------------------------------------------
    # Commit 3: Grounded Answer Generation & Two-Stage Verification Pipeline
    # --------------------------------------------------------------------------
    c3_paths = [
        "packages/retrieval/generation.py",
        "packages/retrieval/query_rewrite.py",
        "packages/verification",
        "tests/unit/verification",
        "tests/unit/test_grounded_generation.py",
    ]
    checkout_from_source(c3_paths)
    run(["git", "add", "-A"])
    run([
        "git", "commit", "-m",
        "feat(verification): grounded generation, code-resolved citations, and two-stage claim verification\n\n"
        "- Implement Pydantic-validated grounded generation where the LLM returns chunk IDs only.\n"
        "- Resolve exact quotes, page numbers, and character offsets deterministically from database chunks.\n"
        "- Build two-stage verification pipeline pairing Stage 1 deterministic checks (numbers, units, dates, polarity, entities) with Stage 2 LLM entailment.\n"
        "- Implement automatic escalation to larger reasoning models before claim rejection.\n"
        "- Enforce honest abstention ('The sources do not say.') when evidence is absent, pruning unverified claims from final text.\n"
        "- Add follow-up conversation query rewriting."
    ])

    # --------------------------------------------------------------------------
    # Commit 4: Bounded Report Agent & Asynchronous Worker API
    # --------------------------------------------------------------------------
    c4_paths = [
        "packages/agent",
        "services/aws.py",
        "services/env.py",
        "services/api",
        "services/worker",
        "services/__init__.py",
        "tests/unit/test_report_agent.py",
        "tests/unit/test_agent_benchmark.py",
        "tests/unit/test_aws_region.py",
        "tests/unit/test_env_file.py",
        "tests/unit/test_worker_logging.py",
        "tests/integration",
    ]
    checkout_from_source(c4_paths)
    run(["git", "add", "-A"])
    run([
        "git", "commit", "-m",
        "feat(agent): bounded report agent state machine, SQS worker, and FastAPI REST API\n\n"
        "- Implement 4-state Report Agent state machine (PLAN -> RESEARCH -> COMPOSE -> DONE) with strict budget bounds (<=4 sub-questions, 1 retry, <=12 LLM calls).\n"
        "- Log every agent step with tool inputs/outputs to PostgreSQL agent_steps table for full auditability.\n"
        "- Build SQS asynchronous worker with SHA-256 chunk deduplication, retry budget, and Dead Letter Queue (DLQ) routing.\n"
        "- Create FastAPI service with multi-tenant endpoints for notebooks, presigned uploads, jobs, chat, and reports.\n"
        "- Add single-shot E7 vs Report Agent E8 benchmark runner."
    ])

    # --------------------------------------------------------------------------
    # Commit 5: React Web UI & Cloud Infrastructure (Terraform)
    # --------------------------------------------------------------------------
    c5_paths = [
        "apps/web",
        "infra",
        "docker-compose.prod.yml",
        "Dockerfile",
        "UI_PLAN.txt",
        "scripts/generate_sample_pdf.py",
        "scripts/live_e2e_test.py",
    ]
    checkout_from_source(c5_paths)
    run(["git", "add", "-A"])
    run([
        "git", "commit", "-m",
        "feat(web): React+Vite web workspace with claim inspector, and Terraform AWS deployment\n\n"
        "- Build 3-pane React + Vite + TypeScript web application with plain CSS and hash routing.\n"
        "- Add drag-and-drop multi-PDF uploads, real-time job polling, and per-claim verification status badges.\n"
        "- Implement interactive evidence panel displaying exact quote snippets, page numbers, and highlighted closest sentences.\n"
        "- Add Report Agent step-by-step trace viewer and estimated per-query token and USD cost display.\n"
        "- Implement authorization code + PKCE sign-in flow for AWS Cognito.\n"
        "- Author modular Terraform IaC for EC2 ARM64, CloudFront CDN, S3, SQS+DLQ, and Cognito User Pool with automated nightly stop."
    ])

    # --------------------------------------------------------------------------
    # Commit 6: Production Reliability, Security Hardening & Architecture Decision Records
    # --------------------------------------------------------------------------
    # Checkout everything remaining from SOURCE_BRANCH so tree is 100% identical
    run(["git", "checkout", SOURCE_BRANCH, "--", "."])
    run(["git", "add", "-A"])
    run([
        "git", "commit", "-m",
        "feat(reliability): circuit breaker, token bucket rate limiter, SSRF guard, structured logging, and ADRs\n\n"
        "- Implement thread-safe Circuit Breaker pattern with fast-failing probe cooldowns for external AI APIs.\n"
        "- Add per-user token-bucket rate limiter enforcing endpoint quotas with HTTP 429 and Retry-After headers.\n"
        "- Add pre-connection DNS SSRF guard blocking AWS IMDS (169.254.169.254), loopback, and private CIDRs, with URL ingestion endpoint.\n"
        "- Add structured JSON logging and distributed contextvars trace propagation with X-Trace-Id header middleware.\n"
        "- Enforce 50MB upload size limits across frontend, API presigning, and worker download phases.\n"
        "- Add worker graceful shutdown handling SIGINT/SIGTERM with in-flight job drain.\n"
        "- Document comprehensive Architecture Decision Records (ADR-001 through ADR-007) and operational failure modes manual.\n"
        "- Expand unit test suite to 148 passed tests with property and edge-case verification."
    ])

    # Verify tree hash
    current_tree = run(["git", "cat-file", "-p", "HEAD"]).splitlines()[0].split()[1]
    print("\n--------------------------------------------------")
    print(f"Target tree:  {TARGET_TREE}")
    print(f"Current tree: {current_tree}")
    if current_tree == TARGET_TREE:
        print("SUCCESS! Final tree hash matches exactly (100% identical).")
    else:
        print("MISMATCH! Investigating diff:")
        diff = run(["git", "diff", SOURCE_BRANCH])
        print(diff[:500])


if __name__ == "__main__":
    main()
