"""SQS worker. One message = one job id. A failed job is left on the queue and retried by SQS;
after maxReceiveCount the message lands in the dead-letter queue (set on the queue by Terraform).

Run:  python -m services.worker.main
"""

import json
import logging
import os
import signal
import time
from collections.abc import Callable

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.orm import Session

from packages.retrieval.db import new_session
from packages.retrieval.models import Job
from services import aws
from services.env import load_env_file
from services.worker.ingestion_worker import process_ingestion_job, process_url_ingestion_job
from services.worker.report_worker import process_report_job

MAX_RETRIES = 3
logger = logging.getLogger(__name__)

_SHUTDOWN_REQUESTED = False


def request_shutdown(signum: int | None = None, frame: object = None) -> None:
    global _SHUTDOWN_REQUESTED
    _SHUTDOWN_REQUESTED = True
    logger.info("Shutdown requested. Worker will exit after in-flight job completes.")


def register_signal_handlers() -> None:
    """Register termination signals for graceful shutdown in containers and processes."""
    try:
        signal.signal(signal.SIGINT, request_shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_shutdown)
    except (ValueError, AttributeError):
        pass  # in non-main threads or restricted environments


def run_job(session: Session, job_id: str, **deps) -> None:
    """Run one job. Raises on failure so the SQS message is not deleted."""
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found.")
    if job.state in ("completed", "failed"):  # duplicate delivery, or SQS redelivering until the DLQ takes it
        return

    job.state = "running"
    job.retries += 1
    session.commit()
    try:
        if job.job_type == "ingestion":
            process_ingestion_job(session, job, **deps)
        elif job.job_type == "url_ingestion":
            process_url_ingestion_job(session, job, **deps)
        elif job.job_type == "report":
            process_report_job(session, job, **deps)
        else:
            raise ValueError(f"Unknown job type {job.job_type}")
        job.state = "completed"
        session.commit()
    except Exception:
        session.rollback()
        job = session.get(Job, job_id)
        if job.state == "completed":  # a redelivered copy finished first; its result stands
            return
        job.state = "failed" if job.retries >= MAX_RETRIES else "queued"
        session.commit()
        raise


def poll_forever(stop_check: Callable[[], bool] | None = None) -> None:
    register_signal_handlers()
    sqs = aws._client("sqs")
    queue_url = os.environ["SQS_QUEUE_URL"]
    while not _SHUTDOWN_REQUESTED and (not stop_check or not stop_check()):
        try:
            resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20, VisibilityTimeout=300)
        except (BotoCoreError, ClientError):  # a network blip must not kill the worker
            logger.exception("SQS receive failed, retrying in 5s")
            time.sleep(5)
            continue
        for msg in resp.get("Messages", []):
            session = new_session()
            try:
                run_job(session, json.loads(msg["Body"])["job_id"])
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
            except Exception:  # leave the message for SQS to redeliver
                logger.exception("job failed, SQS will redeliver: %s", msg["Body"])
            finally:
                session.close()
    logger.info("Worker stopped cleanly.")


if __name__ == "__main__":
    load_env_file()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    poll_forever()
