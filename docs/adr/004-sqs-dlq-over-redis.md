# ADR-004: AWS SQS with Dead Letter Queue (DLQ) over Redis/arq

## Status
Accepted

## Context
Background tasks (PDF parsing, chunk embedding, multi-hop report generation) require an asynchronous job queue. Redis-based task queues (such as Celery, BullMQ, or arq) are popular in developer tutorials but require self-hosting or paying for managed Redis clusters, adding operational complexity, memory scaling costs, and persistence management.

## Decision
Use AWS SQS (Simple Queue Service) paired with a Dead Letter Queue (DLQ):
- Messages carry only the `job_id`.
- Full job state and payload reside in PostgreSQL (`jobs` table).
- Workers poll SQS using long polling (`WaitTimeSeconds = 20`).
- SQS message visibility timeout is set to 300 seconds.
- Failed processing leaves the message on the queue for automatic redelivery up to 3 times before routing to the DLQ.
- Local development uses LocalStack S3 and SQS.

## Consequences
### Positive
- **Serverless and zero-maintenance**: Zero operational overhead; bills only per request ($0.40 per 1M requests).
- **Crash resilience**: A killed worker mid-job automatically triggers message redelivery after visibility timeout expires.
- **Idempotency**: Ingestion uses document SHA-256 deduplication and job-state guarding, ensuring redelivered messages never duplicate chunks.

### Negative
- Local testing requires LocalStack running or faking SQS at the boundary (`services/aws.py`).

