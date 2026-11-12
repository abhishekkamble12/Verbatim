from services import aws


def test_s3_and_sqs_clients_use_aws_region(monkeypatch):
    """boto3 only reads AWS_DEFAULT_REGION; the app is configured with AWS_REGION."""
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    assert aws._client("sqs").meta.region_name == "us-west-2"
    assert aws._client("s3").meta.region_name == "us-west-2"
