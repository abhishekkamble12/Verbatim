# CiteGuard Architecture Decision Records (ADRs)

This directory documents the key architectural decisions made in CiteGuard, their rationale, trade-offs, and consequences.

## Index

- [ADR-001: Plain Python State Machine over Agent Frameworks (LangGraph/CrewAI)](001-plain-python-state-machine.md)
- [ADR-002: Two-Stage Claim Verification (Deterministic Checks + LLM Entailment)](002-two-stage-verification.md)
- [ADR-003: Reciprocal Rank Fusion (RRF) for Hybrid Dense-Sparse Retrieval](003-reciprocal-rank-fusion.md)
- [ADR-004: AWS SQS with Dead Letter Queue (DLQ) over Redis/arq](004-sqs-dlq-over-redis.md)
- [ADR-005: Direct Presigned S3 Uploads over API Multipart Streaming](005-presigned-s3-uploads.md)
- [ADR-006: AWS Cognito with PKCE over In-House JWT Auth](006-cognito-pkce-auth.md)
- [ADR-007: Single-Host Docker Compose Deployment with Automated Nightly Backup](007-single-ec2-deployment.md)

