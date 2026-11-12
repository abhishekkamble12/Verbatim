"""FastAPI service for CiteGuard. All state lives in Postgres; heavy work goes to the SQS worker."""

import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.ingestion.ssrf_guard import SSRFBlockedError, validate_url_safe
from packages.llm_gateway.circuit_breaker import CircuitOpenError
from packages.llm_gateway.gateway import LLMNotConfiguredError, track_usage
from packages.observability.logging import bind_trace_context, get_logger
from packages.retrieval.db import new_session
from packages.retrieval.generation import generate_grounded_answer
from packages.retrieval.hybrid import RetrievalConfig, hybrid_retrieve
from packages.retrieval.models import (
    AgentStep,
    Chunk,
    Claim,
    Conversation,
    Job,
    Message,
    MessageCitation,
    Notebook,
    Report,
    Source,
    UsageLedger,
    User,
)
from packages.retrieval.query_rewrite import rewrite_query_if_followup
from packages.verification.pipeline import verify_grounded_answer
from services import aws
from services.api.auth import AuthUser, auth_mode, get_current_user
from services.api.rate_limit import rate_limiter
from services.env import load_env_file


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_env_file()
    auth_mode()  # refuse to start without an explicit AUTH_MODE
    yield


app = FastAPI(title="CiteGuard API", version="0.1.0", lifespan=lifespan)
logger = get_logger("citeguard.api")


@app.middleware("http")
async def trace_and_log_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or f"tr_{uuid.uuid4().hex[:12]}"
    user_id = request.headers.get("x-user-id")
    started = time.perf_counter()
    with bind_trace_context(trace_id=trace_id, user_id=user_id):
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            logger.info(
                f"{request.method} {request.url.path} -> {response.status_code}",
                extra={
                    "event": "http_request",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            response.headers["X-Trace-Id"] = trace_id
            return response
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            logger.error(
                f"{request.method} {request.url.path} failed with exception",
                extra={
                    "event": "http_request_error",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise


@app.exception_handler(LLMNotConfiguredError)
def llm_not_configured(_: Request, exc: LLMNotConfiguredError) -> JSONResponse:
    """A deployment config problem, not a bug in the request: say so instead of a bare 500."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(CircuitOpenError)
def circuit_open(_: Request, exc: CircuitOpenError) -> JSONResponse:
    """Downstream LLM provider tripped circuit breaker: 503 with retry-after."""
    return JSONResponse(
        status_code=503,
        content={"detail": f"Downstream provider temporarily unavailable. {exc}"},
        headers={"Retry-After": "30"},
    )


@app.exception_handler(ClientError)
def aws_rejected(_: Request, exc: ClientError) -> JSONResponse:
    """AWS said no (model access, permissions, throttling): an upstream outage, so 503 with AWS's reason."""
    err = exc.response.get("Error", {})
    reason = f"{err.get('Code', 'Error')}: {err.get('Message', '')}"
    return JSONResponse(status_code=503, content={"detail": f"AWS rejected the request ({exc.operation_name}). {reason}"})


def get_session():
    session = new_session()
    try:
        yield session
    finally:
        session.close()


def current_user(auth: AuthUser = Depends(get_current_user), session: Session = Depends(get_session)) -> User:
    """The logged-in user's row, created on first sight."""
    user = session.get(User, auth.user_id)
    if user is None:
        user = User(
            id=auth.user_id,
            cognito_sub=auth.cognito_sub or auth.user_id,
            email=auth.email or f"{auth.user_id}@cognito.local",
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:  # a concurrent first request inserted the same user
            session.rollback()
            user = session.get(User, auth.user_id)
    return user


def owned_notebook(session: Session, notebook_id: str, user: User) -> Notebook:
    notebook = session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=404, detail="Notebook not found.")
    if notebook.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied to this notebook.")
    return notebook


def get_owned_job(session: Session, job_id: str, user: User) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied to this job.")
    return job


def get_owned_report(session: Session, report_id: str, user: User) -> Report:
    report = session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    if report.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied to this report.")
    return report


def new_job(session: Session, user: User, notebook_id: str, job_type: str, payload: dict) -> Job:
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job = Job(
        id=job_id,
        user_id=user.id,
        notebook_id=notebook_id,
        job_type=job_type,
        state="queued",
        payload=json.dumps(payload),
        retries=0,
        idempotency_key=f"{job_type}:{job_id}",
    )
    session.add(job)
    session.commit()
    return job


def add_source_titles(session: Session, user: User, notebook_id: str, claims: list[dict]) -> list[dict]:
    """Attach source_id/source_title to every citation so the UI can name the document."""
    chunk_ids = {c["chunk_id"] for claim in claims for c in claim.get("citations", [])}
    rows = session.execute(
        select(Chunk.id, Source.id, Source.title)
        .join(Source, Source.id == Chunk.source_id)
        .where(Chunk.id.in_(chunk_ids), Chunk.user_id == user.id, Chunk.notebook_id == notebook_id)
    ).all()
    by_chunk = {chunk_id: (source_id, title) for chunk_id, source_id, title in rows}
    for claim in claims:
        for c in claim.get("citations", []):
            c["source_id"], c["source_title"] = by_chunk.get(c["chunk_id"], (None, None))
    return claims


def record_usage(session: Session, user: User, job_type: str, ref_id: str, totals: dict, latency_ms: float) -> None:
    session.add(
        UsageLedger(
            id=f"use_{uuid.uuid4().hex[:12]}",
            user_id=user.id,
            job_type=job_type,
            ref_id=ref_id,
            prompt_tokens=int(totals["prompt_tokens"]),
            completion_tokens=int(totals["completion_tokens"]),
            cost_usd=totals["cost_usd"],
            latency_ms=latency_ms,
        )
    )


def usage_for(session: Session, user: User, ref_ids: list[str]) -> dict[str, dict]:
    """LLM tokens and list-price cost per message/report id (embeddings are not metered)."""
    rows = session.execute(
        select(UsageLedger).where(UsageLedger.user_id == user.id, UsageLedger.ref_id.in_(ref_ids))
    ).scalars()
    return {
        r.ref_id: {"prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens, "cost_usd": r.cost_usd}
        for r in rows
    }


MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


# Bounds match the DB columns (title is VARCHAR(255)) and cap what one request can send to the LLM.
class CreateNotebookRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class CreateUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    file_size_bytes: int | None = Field(default=None, ge=1, le=MAX_UPLOAD_BYTES)


class CreateUrlIngestionRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class CreateReportRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


@app.post("/notebooks", status_code=status.HTTP_201_CREATED)
def create_notebook(
    req: CreateNotebookRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    notebook = Notebook(id=f"nb_{uuid.uuid4().hex[:12]}", user_id=user.id, title=req.title, description=req.description)
    session.add(notebook)
    session.commit()
    return {"id": notebook.id, "user_id": user.id, "title": notebook.title, "description": notebook.description}


@app.get("/notebooks")
def list_notebooks(user: User = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.execute(
        select(Notebook).where(Notebook.user_id == user.id).order_by(Notebook.created_at.desc())
    ).scalars()
    return [
        {"id": n.id, "title": n.title, "description": n.description, "created_at": n.created_at.isoformat()}
        for n in rows
    ]


@app.get("/notebooks/{notebook_id}/sources")
def list_sources(notebook_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Ready sources, plus uploads still queued/running/failed so the UI can show their progress."""
    owned_notebook(session, notebook_id, user)
    sources = session.execute(
        select(Source)
        .where(Source.user_id == user.id, Source.notebook_id == notebook_id)
        .order_by(Source.created_at.desc())
    ).scalars()
    jobs = session.execute(
        select(Job)
        .where(
            Job.user_id == user.id,
            Job.notebook_id == notebook_id,
            Job.job_type == "ingestion",
            Job.state != "completed",
        )
        .order_by(Job.created_at.desc())
    ).scalars()
    return {
        "sources": [
            {"id": s.id, "title": s.title, "source_type": s.source_type, "created_at": s.created_at.isoformat()}
            for s in sources
        ],
        "pending_uploads": [
            {"job_id": j.id, "filename": json.loads(j.payload or "{}").get("filename"), "state": j.state}
            for j in jobs
        ],
    }


@app.get("/sources/{source_id}/download")
def download_source(source_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    if source.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied to this source.")
    if source.source_type != "pdf" or not source.file_path:
        raise HTTPException(status_code=404, detail="This source has no downloadable file.")
    return {"url": aws.presign_download(source.file_path)}


@app.post("/notebooks/{notebook_id}/uploads", status_code=status.HTTP_202_ACCEPTED)
def create_upload(
    notebook_id: str,
    req: CreateUploadRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Step 1: get a presigned URL. Step 2: PUT the PDF there. Step 3: POST /jobs/{id}/start."""
    rate_limiter.check(user.id, "upload")
    owned_notebook(session, notebook_id, user)
    name = PurePosixPath(req.filename.replace("\\", "/")).name  # no path tricks in the S3 key
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF uploads are supported.")
    s3_key = f"uploads/{user.id}/{notebook_id}/{uuid.uuid4().hex[:8]}_{name}"
    job = new_job(session, user, notebook_id, "ingestion", {"filename": name, "s3_key": s3_key})
    return {"job_id": job.id, "upload_url": aws.presign_upload(s3_key), "s3_key": s3_key}


@app.post("/notebooks/{notebook_id}/urls", status_code=status.HTTP_202_ACCEPTED)
def ingest_url(
    notebook_id: str,
    req: CreateUrlIngestionRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """Safely ingest a web document from a URL with SSRF protection."""
    rate_limiter.check(user.id, "upload")
    owned_notebook(session, notebook_id, user)
    try:
        safe_url = validate_url_safe(req.url)
    except SSRFBlockedError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    job = new_job(session, user, notebook_id, "url_ingestion", {"url": safe_url})
    aws.enqueue({"job_id": job.id})
    return {"job_id": job.id, "state": job.state, "url": safe_url}


@app.post("/jobs/{job_id}/start", status_code=status.HTTP_202_ACCEPTED)
def start_job(job_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Tell the worker the file is uploaded."""
    job = get_owned_job(session, job_id, user)
    if job.job_type != "ingestion" or job.state != "queued":  # report jobs are enqueued on creation
        raise HTTPException(status_code=409, detail=f"Job is {job.state}; only a queued upload can be started.")
    aws.enqueue({"job_id": job.id})
    return {"job_id": job.id, "state": job.state}


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    job = get_owned_job(session, job_id, user)
    view = {
        "id": job.id,
        "job_type": job.job_type,
        "state": job.state,
        "retries": job.retries,
        "notebook_id": job.notebook_id,
        "payload": json.loads(job.payload or "{}"),
    }
    if job.job_type == "report":
        view["report_id"] = session.execute(select(Report.id).where(Report.job_id == job.id)).scalar_one_or_none()
    return view


@app.post("/notebooks/{notebook_id}/reports", status_code=status.HTTP_202_ACCEPTED)
def create_report(
    notebook_id: str,
    req: CreateReportRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    rate_limiter.check(user.id, "report")
    owned_notebook(session, notebook_id, user)
    job = new_job(session, user, notebook_id, "report", {"question": req.question})
    aws.enqueue({"job_id": job.id})
    return {"job_id": job.id, "status": "queued"}


@app.get("/reports/{report_id}")
def get_report(report_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    r = get_owned_report(session, report_id, user)
    return {
        "id": r.id,
        "job_id": r.job_id,
        "notebook_id": r.notebook_id,
        "question": r.question,
        "markdown": r.markdown,
        "claims": add_source_titles(session, user, r.notebook_id, json.loads(r.claims_json)),
        "is_partial": r.is_partial,
        "usage": usage_for(session, user, [r.id]).get(r.id),
    }


@app.get("/reports/{report_id}/trace")
def get_report_trace(report_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    r = get_owned_report(session, report_id, user)
    steps = session.execute(
        select(AgentStep).where(AgentStep.job_id == r.job_id).order_by(AgentStep.id)
    ).scalars()
    return {
        "report_id": r.id,
        "job_id": r.job_id,
        "agent_steps": [
            {
                "state": s.state,
                "tool": s.tool,
                "tool_input": s.tool_input,
                "tool_output": s.tool_output,
                "tokens": s.tokens,
                "latency_ms": s.latency_ms,
            }
            for s in steps
        ],
    }


@app.get("/notebooks/{notebook_id}/conversations")
def list_conversations(notebook_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    owned_notebook(session, notebook_id, user)
    rows = session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.notebook_id == notebook_id)
        .order_by(Conversation.created_at.desc())
    ).scalars()
    return [{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]


@app.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Reloaded history. Citations hang off the message (the schema has no claim link), so they are per message."""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")
    messages = list(
        session.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.user_id == user.id,
                Message.notebook_id == conversation.notebook_id,
            )
            .order_by(Message.created_at, Message.id)
        ).scalars()
    )
    ids = [m.id for m in messages]
    claims = list(session.execute(select(Claim).where(Claim.message_id.in_(ids)).order_by(Claim.id)).scalars())
    cites_by_claim: dict[str, list[dict]] = {}
    for c in session.execute(select(MessageCitation).where(MessageCitation.message_id.in_(ids))).scalars():
        cites_by_claim.setdefault(c.claim_id or "", []).append(
            {"chunk_id": c.chunk_id, "quote": c.quote, "page_number": c.page_number}
        )
    claims_by: dict[str, list[dict]] = {}
    for c in claims:
        claims_by.setdefault(c.message_id, []).append(
            {"text": c.claim_text, "support_status": c.status, "rejection_reason": c.reason,
             "citations": cites_by_claim.get(c.id, [])}
        )
    add_source_titles(session, user, conversation.notebook_id, [c for cs in claims_by.values() for c in cs])
    usage = usage_for(session, user, ids)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "claims": claims_by.get(m.id, []),
            "usage": usage.get(m.id),
        }
        for m in messages
    ]


@app.post("/notebooks/{notebook_id}/chat")
def chat_with_notebook(
    notebook_id: str,
    req: ChatRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    rate_limiter.check(user.id, "chat")
    owned_notebook(session, notebook_id, user)

    conversation = session.get(Conversation, req.conversation_id) if req.conversation_id else None
    if conversation is not None and (conversation.user_id != user.id or conversation.notebook_id != notebook_id):
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")
    if conversation is None:
        conversation = Conversation(
            id=f"conv_{uuid.uuid4().hex[:12]}", user_id=user.id, notebook_id=notebook_id, title=req.query[:80]
        )
        session.add(conversation)
        session.flush()

    history_rows = session.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id)
    ).scalars()
    history = [{"role": m.role, "content": m.content} for m in history_rows]

    started = time.perf_counter()
    with track_usage() as usage:
        rewritten_query, was_rewritten = rewrite_query_if_followup(query=req.query, conversation_history=history)
        retrieved = hybrid_retrieve(session, rewritten_query, user.id, notebook_id, RetrievalConfig(top_k=5))
        verified = verify_grounded_answer(generate_grounded_answer(query=rewritten_query, retrieved_chunks=retrieved))
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    def message(role: str, content: str) -> Message:
        return Message(
            id=f"msg_{uuid.uuid4().hex[:12]}",
            user_id=user.id,
            notebook_id=notebook_id,
            conversation_id=conversation.id,
            role=role,
            content=content,
        )

    user_msg = message("user", req.query)
    answer_msg = message("assistant", verified.answer)
    # Explicit, ordered timestamps: two defaults in one flush can tie, and history is ordered by time.
    user_msg.created_at = datetime.now(UTC)
    answer_msg.created_at = user_msg.created_at + timedelta(milliseconds=1)
    session.add(user_msg)
    session.add(answer_msg)
    session.flush()
    for claim in verified.claims:
        claim_id = f"clm_{uuid.uuid4().hex[:12]}"
        session.add(
            Claim(
                id=claim_id,
                message_id=answer_msg.id,
                claim_text=claim.text,
                status=claim.support_status,
                reason=claim.rejection_reason,
            )
        )
        for cit in claim.citations:
            if cit.quote is not None:
                session.add(
                    MessageCitation(
                        id=f"cit_{uuid.uuid4().hex[:12]}",
                        message_id=answer_msg.id,
                        claim_id=claim_id,
                        chunk_id=cit.chunk_id,
                        quote=cit.quote,
                        page_number=cit.page_number or 1,
                        start_char=cit.start_char or 0,
                        end_char=cit.end_char or 0,
                    )
                )
    record_usage(session, user, "chat", answer_msg.id, usage, latency_ms)
    session.commit()

    return {
        "conversation_id": conversation.id,
        "original_query": req.query,
        "rewritten_query": rewritten_query if was_rewritten else None,
        "query_rewritten": was_rewritten,
        "answer": verified.answer,
        "claims": add_source_titles(session, user, notebook_id, [c.model_dump() for c in verified.claims]),
        "insufficient_evidence": verified.insufficient_evidence,
        "usage": {**usage, "calls": int(usage["calls"])},
    }
