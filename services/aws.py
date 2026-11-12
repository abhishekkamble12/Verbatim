"""The only code that talks to S3 and SQS. Tests replace these functions.

LocalStack: set AWS_ENDPOINT_URL_S3 and AWS_ENDPOINT_URL_SQS to http://localhost:4566 (boto3 reads them). Names come from the environment.
"""

import json
import os
from typing import Any

import boto3


def _client(service: str):
    # boto3 reads AWS_DEFAULT_REGION only; the app is configured with AWS_REGION.
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client(service, region_name=region)


def _bucket() -> str:
    return os.environ["S3_BUCKET"]


def presign_upload(key: str, expires: int = 900) -> str:
    """URL the browser PUTs the file to directly, so uploads never pass through the API."""
    return _client("s3").generate_presigned_url(
        "put_object", Params={"Bucket": _bucket(), "Key": key}, ExpiresIn=expires
    )


def presign_download(key: str, expires: int = 900) -> str:
    return _client("s3").generate_presigned_url(
        "get_object", Params={"Bucket": _bucket(), "Key": key}, ExpiresIn=expires
    )


def download_file(key: str, dest: str) -> None:
    _client("s3").download_file(_bucket(), key, dest)


def enqueue(message: dict[str, Any]) -> None:
    _client("sqs").send_message(QueueUrl=os.environ["SQS_QUEUE_URL"], MessageBody=json.dumps(message))
