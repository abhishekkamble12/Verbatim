"""Ingestion job: download the uploaded PDF from S3 and run the ingestion pipeline.

Safe to retry: the pipeline is one transaction and skips a file it has already stored (same SHA-256).
"""

import json
import tempfile
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from packages.ingestion.pipeline import EmbedFn, ingest_pdf, ingest_url
from packages.llm_gateway.gateway import generate_embedding
from packages.retrieval.models import Job
from services import aws

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def process_ingestion_job(
    session: Session,
    job: Job,
    download_fn: Callable[[str, str], None] = aws.download_file,
    embed_fn: EmbedFn = generate_embedding,
) -> None:
    payload = json.loads(job.payload or "{}")
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / Path(payload["filename"]).name
        download_fn(payload["s3_key"], str(local))
        if local.stat().st_size > MAX_UPLOAD_BYTES:
            raise ValueError(f"Uploaded file size ({local.stat().st_size} bytes) exceeds limit ({MAX_UPLOAD_BYTES} bytes)")
        ingest_pdf(session, job.user_id, job.notebook_id, local, file_path=payload["s3_key"], embed_fn=embed_fn)


def process_url_ingestion_job(
    session: Session,
    job: Job,
    embed_fn: EmbedFn = generate_embedding,
) -> None:
    payload = json.loads(job.payload or "{}")
    url = payload["url"]
    ingest_url(session, job.user_id, job.notebook_id, url, embed_fn=embed_fn)
