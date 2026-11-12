# ADR-005: Direct Presigned S3 Uploads over API Multipart Streaming

## Status
Accepted

## Context
When users upload large PDF files (up to 50MB), routing file payloads through the FastAPI application server ties up HTTP worker connections, consumes server memory and bandwidth, and limits API horizontal scaling.

## Decision
Adopt direct client-to-storage presigned uploads:
1. Client requests upload authorization: `POST /notebooks/{id}/uploads` with filename and optional size.
2. API validates notebook ownership and filename, generates a unique, isolated S3 key (`uploads/{user_id}/{notebook_id}/{uuid}_{filename}`), creates a queued job row, and returns a presigned S3 upload URL.
3. Client uploads the PDF binary directly to S3 via HTTP PUT to the presigned URL.
4. Client notifies the API upon upload completion: `POST /jobs/{id}/start`, which validates state and enqueues the `job_id` to SQS.

## Consequences
### Positive
- **API Offloading**: The FastAPI server never receives or buffers large PDF streams, reducing CPU and memory footprint to near zero.
- **Strict Isolation**: S3 keys strictly partition uploads by `user_id` and `notebook_id`.
- **Size Bounds**: Maximum upload sizes (50MB) are enforced at the client, API presign request, and worker download phases.

### Negative
- Requires a two-step handshake (`create_upload` -> S3 upload -> `start_job`) rather than a single form submission.

