# ADR-007: Single-Host Docker Compose Deployment with Automated Nightly Backup

## Status
Accepted

## Context
Deploying CiteGuard to AWS for demonstrations and benchmarking requires balancing cloud costs against operational simplicity. A multi-node ECS/EKS architecture with managed RDS and ALB costs upwards of $100–$250/month even when idle, which is cost-prohibitive for a solo demonstration workspace.

## Decision
Deploy via Terraform on a single ARM64 EC2 instance (`t4g.micro` or `t4g.small`) running Docker Compose:
- **CloudFront CDN** terminates HTTPS, serves the static SPA frontend from S3, and routes `/api/*` to the EC2 instance.
- **Docker Compose** co-locates the FastAPI server, the background SQS worker, and PostgreSQL with `pgvector`.
- **Nightly automated backup**: Scheduled `pg_dump` uploads timestamped archives to S3.
- **Cost containment**: EventBridge Scheduler automatically stops the instance during inactive night hours; AWS Budgets alerts trigger at $5, $15, and $25.

## Consequences
### Positive
- **Predictable low cost**: Idle cost is ~\$3–\$5/month (mostly EBS storage and CloudFront requests).
- **Simplicity**: Exactly mirrors local development with Docker Compose.
- **Honest documentation**: Limitations (single point of failure) are explicitly documented in README rather than masked behind faux enterprise claims.

### Negative
- Single point of failure: EC2 hardware failure causes downtime until restarted or recovered.
- CloudFront origin IP changes across start/stop cycles when deployed without an Elastic IP.

