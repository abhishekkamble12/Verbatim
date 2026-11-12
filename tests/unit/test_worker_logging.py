import logging
from types import SimpleNamespace

import pytest

from services.worker import main as worker_main


class StopPolling(Exception):
    pass


def test_failed_job_is_logged_with_job_id_and_traceback(monkeypatch, caplog):
    replies = iter([{"Messages": [{"Body": '{"job_id": "job_x"}', "ReceiptHandle": "r"}]}])

    def receive_message(**_):
        try:
            return next(replies)
        except StopIteration:
            raise StopPolling from None

    sqs = SimpleNamespace(receive_message=receive_message, delete_message=lambda **_: pytest.fail("must not delete"))
    monkeypatch.setenv("SQS_QUEUE_URL", "q")
    monkeypatch.setattr(worker_main.aws, "_client", lambda name: sqs)
    monkeypatch.setattr(worker_main, "new_session", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(worker_main, "run_job", lambda s, job_id: (_ for _ in ()).throw(ConnectionError("s3 down")))

    with caplog.at_level(logging.ERROR, logger=worker_main.__name__), pytest.raises(StopPolling):
        worker_main.poll_forever()

    [record] = caplog.records
    assert "job_x" in record.getMessage()
    assert record.exc_info and record.exc_info[0] is ConnectionError


def test_sqs_network_error_does_not_stop_polling(monkeypatch, caplog):
    from botocore.exceptions import EndpointConnectionError

    calls = []

    def receive_message(**_):
        calls.append(1)
        if len(calls) == 1:
            raise EndpointConnectionError(endpoint_url="http://sqs")
        raise StopPolling

    monkeypatch.setenv("SQS_QUEUE_URL", "q")
    monkeypatch.setattr(worker_main.aws, "_client", lambda name: SimpleNamespace(receive_message=receive_message))
    monkeypatch.setattr(worker_main.time, "sleep", lambda s: None)
    with caplog.at_level(logging.ERROR, logger=worker_main.__name__), pytest.raises(StopPolling):
        worker_main.poll_forever()
    assert len(calls) == 2 and "receive" in caplog.records[0].getMessage()


def test_worker_graceful_shutdown(monkeypatch, caplog):
    monkeypatch.setenv("SQS_QUEUE_URL", "q")
    calls = []

    def receive_message(**_):
        calls.append(1)
        worker_main.request_shutdown()
        return {"Messages": []}

    monkeypatch.setattr(worker_main.aws, "_client", lambda name: SimpleNamespace(receive_message=receive_message))

    # Reset shutdown state before test
    monkeypatch.setattr(worker_main, "_SHUTDOWN_REQUESTED", False)

    with caplog.at_level(logging.INFO, logger=worker_main.__name__):
        worker_main.poll_forever()

    # Loop terminated gracefully after 1 call
    assert len(calls) == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any("Worker stopped cleanly" in m for m in messages)

