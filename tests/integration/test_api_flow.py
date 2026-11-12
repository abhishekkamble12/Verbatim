"""Whole product flow on real Postgres, with S3/SQS and the LLM faked at their edges."""

import shutil

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.retrieval.models import AgentStep, Job, Report, UsageLedger, User
from services import aws
from services.api.auth import AuthUser
from services.api.main import app, current_user, get_session
from services.worker import main as worker_main
from services.worker.main import MAX_RETRIES, run_job
from tests.fakes import hash_embedding

ALICE = {"X-User-Id": "user_alice"}
BOB = {"X-User-Id": "user_bob"}


def embed(text):
    return hash_embedding(text, "t"), False


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "q3_report.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), "Consolidated revenues grew by 14.2% in Q3.", fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def queue(monkeypatch):
    sent = []
    monkeypatch.setattr(aws, "enqueue", sent.append)
    monkeypatch.setattr(aws, "presign_upload", lambda key, expires=900: f"https://s3.test/{key}?sig=1")
    monkeypatch.setattr(aws, "presign_download", lambda key, expires=900: f"https://s3.test/get/{key}?sig=1")
    return sent


@pytest.fixture
def client(db_session, queue):
    app.dependency_overrides[get_session] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def ingest_via_api(client, db_session, pdf, headers=ALICE):
    nb = client.post("/notebooks", json={"title": "Q3"}, headers=headers).json()["id"]
    up = client.post(f"/notebooks/{nb}/uploads", json={"filename": "../../etc/q3_report.pdf"}, headers=headers)
    assert up.status_code == 202
    job_id = up.json()["job_id"]
    assert client.post(f"/jobs/{job_id}/start", headers=headers).status_code == 202
    run_job(db_session, job_id, download_fn=lambda key, dest: shutil.copy(pdf, dest), embed_fn=embed)
    return nb, job_id


def test_upload_to_chat_flow(client, db_session, pdf, queue):
    nb, job_id = ingest_via_api(client, db_session, pdf)

    assert queue == [{"job_id": job_id}]
    job = client.get(f"/jobs/{job_id}", headers=ALICE).json()
    assert job["state"] == "completed"
    assert ".." not in job["payload"]["s3_key"]  # the filename's path tricks were stripped

    chat = client.post(f"/notebooks/{nb}/chat", json={"query": "How much did revenues grow?"}, headers=ALICE).json()
    assert chat["insufficient_evidence"] is False
    assert chat["claims"][0]["support_status"] == "verified"
    assert chat["claims"][0]["citations"][0]["quote"].startswith("Consolidated revenues")
    assert chat["query_rewritten"] is False

    follow = client.post(
        f"/notebooks/{nb}/chat",
        json={"query": "And the year before?", "conversation_id": chat["conversation_id"]},
        headers=ALICE,
    ).json()
    assert follow["query_rewritten"] is True


def test_chat_abstains_when_notebook_is_empty(client):
    nb = client.post("/notebooks", json={"title": "empty"}, headers=ALICE).json()["id"]
    chat = client.post(f"/notebooks/{nb}/chat", json={"query": "anything?"}, headers=ALICE).json()
    assert chat["insufficient_evidence"] is True and chat["answer"] == "The sources do not say."


def test_other_users_get_403_everywhere(client, db_session, pdf):
    nb, job_id = ingest_via_api(client, db_session, pdf)
    assert client.post(f"/notebooks/{nb}/chat", json={"query": "revenues"}, headers=BOB).status_code == 403
    assert client.post(f"/notebooks/{nb}/uploads", json={"filename": "x.pdf"}, headers=BOB).status_code == 403
    assert client.post(f"/notebooks/{nb}/reports", json={"question": "q"}, headers=BOB).status_code == 403
    assert client.get(f"/jobs/{job_id}", headers=BOB).status_code == 403
    assert client.post(f"/jobs/{job_id}/start", headers=BOB).status_code == 403


def test_non_pdf_upload_is_rejected(client):
    nb = client.post("/notebooks", json={"title": "n"}, headers=ALICE).json()["id"]
    assert client.post(f"/notebooks/{nb}/uploads", json={"filename": "evil.exe"}, headers=ALICE).status_code == 422


def test_report_job_end_to_end(client, db_session, pdf, queue, monkeypatch):
    nb, _ = ingest_via_api(client, db_session, pdf)
    monkeypatch.setattr("services.worker.report_worker.generate_embedding", embed)

    job_id = client.post(f"/notebooks/{nb}/reports", json={"question": "Summarise revenue growth."}, headers=ALICE).json()["job_id"]
    run_job(db_session, job_id, embed_fn=embed)

    job = client.get(f"/jobs/{job_id}", headers=ALICE).json()
    assert job["state"] == "completed" and job["report_id"]
    report = client.get(f"/reports/{job['report_id']}", headers=ALICE).json()
    assert "Consolidated revenues grew by 14.2%" in report["markdown"]
    assert report["claims"][0]["support_status"] == "verified"

    trace = client.get(f"/reports/{job['report_id']}/trace", headers=ALICE).json()
    assert [s["state"] for s in trace["agent_steps"]][0] == "PLAN"
    assert trace["agent_steps"][-1]["state"] == "DONE"

    assert client.get(f"/reports/{job['report_id']}", headers=BOB).status_code == 403
    assert client.get(f"/reports/{job['report_id']}/trace", headers=BOB).status_code == 403


def test_failed_job_is_retried_then_marked_failed(client, db_session):
    nb = client.post("/notebooks", json={"title": "n"}, headers=ALICE).json()["id"]
    job_id = client.post(f"/notebooks/{nb}/uploads", json={"filename": "a.pdf"}, headers=ALICE).json()["job_id"]

    def broken_download(key, dest):
        raise ConnectionError("s3 down")

    for attempt in range(1, MAX_RETRIES + 1):
        with pytest.raises(ConnectionError):
            run_job(db_session, job_id, download_fn=broken_download, embed_fn=embed)
        job = db_session.get(Job, job_id)
        assert job.retries == attempt
        assert job.state == ("failed" if attempt == MAX_RETRIES else "queued")

    # SQS keeps redelivering until the DLQ takes it; a failed job must not run (or count) again.
    run_job(db_session, job_id, download_fn=broken_download, embed_fn=embed)
    job = db_session.get(Job, job_id)
    assert (job.state, job.retries) == ("failed", MAX_RETRIES)


def test_duplicate_sqs_delivery_is_a_noop(client, db_session, pdf):
    _, job_id = ingest_via_api(client, db_session, pdf)
    run_job(db_session, job_id, download_fn=lambda k, d: (_ for _ in ()).throw(AssertionError("must not run twice")))
    assert db_session.get(Job, job_id).retries == 1
    assert db_session.query(AgentStep).count() == 0


def test_oversized_or_empty_input_is_422_not_500(client):
    assert client.post("/notebooks", json={"title": "t" * 256}, headers=ALICE).status_code == 422
    assert client.post("/notebooks", json={"title": ""}, headers=ALICE).status_code == 422
    nb = client.post("/notebooks", json={"title": "t" * 255}, headers=ALICE).json()["id"]
    assert client.post(f"/notebooks/{nb}/chat", json={"query": ""}, headers=ALICE).status_code == 422
    assert client.post(f"/notebooks/{nb}/chat", json={"query": "q" * 2001}, headers=ALICE).status_code == 422
    assert client.post(f"/notebooks/{nb}/reports", json={"question": ""}, headers=ALICE).status_code == 422
    long_name = "a" * 201 + ".pdf"
    assert client.post(f"/notebooks/{nb}/uploads", json={"filename": long_name}, headers=ALICE).status_code == 422


def test_concurrent_report_redelivery_keeps_one_report(client, db_session, pdf, monkeypatch):
    """SQS redelivers after the visibility timeout while worker A is still running; worker B finishes first."""
    nb, _ = ingest_via_api(client, db_session, pdf)
    monkeypatch.setattr("services.worker.report_worker.generate_embedding", embed)
    job_id = client.post(f"/notebooks/{nb}/reports", json={"question": "Revenue growth?"}, headers=ALICE).json()["job_id"]
    real = worker_main.process_report_job

    def worker_a(session, job, **deps):
        with Session(bind=session.get_bind(), expire_on_commit=False) as b:  # worker B, its own connection
            real(b, b.get(Job, job.id), **deps)
            b.get(Job, job.id).state = "completed"
            b.commit()
        return real(session, job, **deps)

    monkeypatch.setattr(worker_main, "process_report_job", worker_a)
    run_job(db_session, job_id, embed_fn=embed)  # must not raise: the job is done, the message can be deleted

    assert db_session.scalar(select(func.count()).select_from(Report).where(Report.job_id == job_id)) == 1
    resp = client.get(f"/jobs/{job_id}", headers=ALICE)
    assert resp.status_code == 200 and resp.json()["state"] == "completed"


@pytest.mark.real_gateway
def test_chat_without_llm_config_is_503(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    nb = client.post("/notebooks", json={"title": "n"}, headers=ALICE).json()["id"]
    resp = client.post(f"/notebooks/{nb}/chat", json={"query": "anything?"}, headers=ALICE)
    assert resp.status_code == 503
    assert "LLM_PROVIDER" in resp.json()["detail"]


def test_start_only_queues_a_pending_ingestion_job(client, db_session, pdf, queue):
    nb, job_id = ingest_via_api(client, db_session, pdf)
    assert client.post(f"/jobs/{job_id}/start", headers=ALICE).status_code == 409  # already completed
    report_job = client.post(f"/notebooks/{nb}/reports", json={"question": "q"}, headers=ALICE).json()["job_id"]
    assert client.post(f"/jobs/{report_job}/start", headers=ALICE).status_code == 409  # enqueued on creation
    assert queue == [{"job_id": job_id}, {"job_id": report_job}]


def test_first_request_race_on_user_insert(db_session, monkeypatch):
    """Two first requests: both see no user row, the other one inserts it first."""
    with Session(bind=db_session.get_bind()) as other:
        other.add(User(id="racer", cognito_sub="sub_racer", email="racer@example.com"))
        other.commit()
    real_get, seen = db_session.get, []
    monkeypatch.setattr(db_session, "get", lambda model, key: None if not seen.append(1) and len(seen) == 1 else real_get(model, key))
    user = current_user(AuthUser(user_id="racer", email="racer@example.com", cognito_sub="sub_racer"), db_session)
    assert user.id == "racer"


def test_missing_resources_are_404(client):
    assert client.post("/notebooks/nb_nope/chat", json={"query": "q"}, headers=ALICE).status_code == 404
    assert client.get("/jobs/job_nope", headers=ALICE).status_code == 404
    assert client.get("/reports/rep_nope", headers=ALICE).status_code == 404
    assert client.get("/reports/rep_nope/trace", headers=ALICE).status_code == 404


def test_cannot_continue_another_users_conversation(client, db_session, pdf):
    nb, _ = ingest_via_api(client, db_session, pdf)
    conv = client.post(f"/notebooks/{nb}/chat", json={"query": "revenues?"}, headers=ALICE).json()["conversation_id"]
    bob_nb = client.post("/notebooks", json={"title": "bob"}, headers=BOB).json()["id"]
    hijack = client.post(f"/notebooks/{bob_nb}/chat", json={"query": "and?", "conversation_id": conv}, headers=BOB)
    assert hijack.status_code == 403  # would otherwise leak Alice's history into Bob's query rewrite
    alice_nb2 = client.post("/notebooks", json={"title": "other"}, headers=ALICE).json()["id"]
    cross_nb = client.post(f"/notebooks/{alice_nb2}/chat", json={"query": "and?", "conversation_id": conv}, headers=ALICE)
    assert cross_nb.status_code == 403  # a conversation is bound to its notebook


def test_list_notebooks_only_shows_own(client):
    a = client.post("/notebooks", json={"title": "alice nb"}, headers=ALICE).json()["id"]
    client.post("/notebooks", json={"title": "bob nb"}, headers=BOB)
    rows = client.get("/notebooks", headers=ALICE).json()
    assert [r["id"] for r in rows] == [a]
    assert rows[0]["title"] == "alice nb" and rows[0]["created_at"]


def test_list_sources_and_pending_uploads(client, db_session, pdf):
    nb, job_id = ingest_via_api(client, db_session, pdf)
    pending = client.post(f"/notebooks/{nb}/uploads", json={"filename": "next.pdf"}, headers=ALICE).json()["job_id"]
    body = client.get(f"/notebooks/{nb}/sources", headers=ALICE).json()
    assert [s["title"] for s in body["sources"]] == ["q3_report"]
    assert body["sources"][0]["source_type"] == "pdf"
    # the finished upload is a source now; only the unfinished one is listed as a job
    assert [(j["job_id"], j["filename"], j["state"]) for j in body["pending_uploads"]] == [(pending, "next.pdf", "queued")]
    assert client.get(f"/notebooks/{nb}/sources", headers=BOB).status_code == 403
    assert client.get("/notebooks/nb_nope/sources", headers=ALICE).status_code == 404


def test_conversation_history_round_trip(client, db_session, pdf):
    nb, _ = ingest_via_api(client, db_session, pdf)
    chat = client.post(f"/notebooks/{nb}/chat", json={"query": "How much did revenues grow?"}, headers=ALICE).json()
    convs = client.get(f"/notebooks/{nb}/conversations", headers=ALICE).json()
    assert [c["id"] for c in convs] == [chat["conversation_id"]]

    msgs = client.get(f"/conversations/{chat['conversation_id']}/messages", headers=ALICE).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    answer = msgs[1]
    claim = answer["claims"][0]
    assert claim["support_status"] == "verified"
    # citations stay attached to the claim they support, with the document named
    assert claim["citations"][0]["quote"].startswith("Consolidated revenues")
    assert claim["citations"][0]["page_number"] == 1
    assert claim["citations"][0]["source_title"] == "q3_report"
    assert msgs[0]["claims"] == []
    assert answer["usage"]["cost_usd"] == chat["usage"]["cost_usd"] > 0
    assert msgs[0]["usage"] is None


def test_history_is_private(client, db_session, pdf):
    nb, _ = ingest_via_api(client, db_session, pdf)
    conv = client.post(f"/notebooks/{nb}/chat", json={"query": "revenues?"}, headers=ALICE).json()["conversation_id"]
    assert client.get(f"/notebooks/{nb}/conversations", headers=BOB).status_code == 403
    assert client.get(f"/conversations/{conv}/messages", headers=BOB).status_code == 403
    assert client.get("/conversations/conv_nope/messages", headers=ALICE).status_code == 404


def test_citations_carry_source_title_and_download_link(client, db_session, pdf):
    nb, job_id = ingest_via_api(client, db_session, pdf)
    chat = client.post(f"/notebooks/{nb}/chat", json={"query": "How much did revenues grow?"}, headers=ALICE).json()
    cit = chat["claims"][0]["citations"][0]
    assert cit["source_title"] == "q3_report" and cit["source_id"]

    s3_key = client.get(f"/jobs/{job_id}", headers=ALICE).json()["payload"]["s3_key"]
    url = client.get(f"/sources/{cit['source_id']}/download", headers=ALICE).json()["url"]
    assert url == f"https://s3.test/get/{s3_key}?sig=1"

    assert client.get(f"/sources/{cit['source_id']}/download", headers=BOB).status_code == 403
    assert client.get("/sources/src_nope/download", headers=ALICE).status_code == 404


def test_report_claims_carry_source_title(client, db_session, pdf, monkeypatch):
    nb, _ = ingest_via_api(client, db_session, pdf)
    monkeypatch.setattr("services.worker.report_worker.generate_embedding", embed)
    job_id = client.post(f"/notebooks/{nb}/reports", json={"question": "Summarise revenue growth."}, headers=ALICE).json()["job_id"]
    run_job(db_session, job_id, embed_fn=embed)
    report_id = client.get(f"/jobs/{job_id}", headers=ALICE).json()["report_id"]
    report = client.get(f"/reports/{report_id}", headers=ALICE).json()
    assert report["claims"][0]["citations"][0]["source_title"] == "q3_report"


def test_chat_and_report_cost_is_recorded(client, db_session, pdf, monkeypatch):
    nb, _ = ingest_via_api(client, db_session, pdf)
    chat = client.post(f"/notebooks/{nb}/chat", json={"query": "How much did revenues grow?"}, headers=ALICE).json()
    u = chat["usage"]
    assert u["prompt_tokens"] > 0 and u["completion_tokens"] > 0 and u["cost_usd"] > 0 and u["calls"] >= 1
    row = db_session.query(UsageLedger).filter_by(user_id="user_alice", job_type="chat").one()
    assert row.cost_usd == u["cost_usd"]

    monkeypatch.setattr("services.worker.report_worker.generate_embedding", embed)
    job_id = client.post(f"/notebooks/{nb}/reports", json={"question": "Summarise revenue growth."}, headers=ALICE).json()["job_id"]
    run_job(db_session, job_id, embed_fn=embed)
    report_id = client.get(f"/jobs/{job_id}", headers=ALICE).json()["report_id"]
    report = client.get(f"/reports/{report_id}", headers=ALICE).json()
    assert report["usage"]["cost_usd"] > 0 and report["usage"]["prompt_tokens"] > 0
    assert db_session.query(UsageLedger).filter_by(ref_id=report_id, job_type="report").count() == 1


def test_aws_rejection_is_503_with_reason(client, monkeypatch):
    from botocore.exceptions import ClientError

    from packages.llm_gateway import gateway

    def blocked(*_):
        raise ClientError({"Error": {"Code": "ValidationException", "Message": "Operation not allowed"}}, "InvokeModel")

    monkeypatch.setattr(gateway, "_call_external_embedding", blocked)
    nb = client.post("/notebooks", json={"title": "n"}, headers=ALICE).json()["id"]
    resp = TestClient(app, raise_server_exceptions=False).post(f"/notebooks/{nb}/chat", json={"query": "q?"}, headers=ALICE)
    assert resp.status_code == 503
    assert "Operation not allowed" in resp.json()["detail"]
