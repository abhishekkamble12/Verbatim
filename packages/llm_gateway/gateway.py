"""LLM gateway: Bedrock (default) or Groq, disk caching, and token/cost accounting.

Nothing here fakes a model. If no provider is configured the call raises, so a missing
config can never turn into silently "verified" claims. Tests patch `_call_external_provider`
and `_call_external_embedding` (see tests/conftest.py).
"""

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from packages.llm_gateway.circuit_breaker import CircuitBreaker

# Set once here; override with env vars. Confirm the exact Bedrock model IDs for your region.
SMALL_MODEL = os.environ.get("CITEGUARD_SMALL_MODEL", "anthropic.claude-haiku-5-5")
LARGE_MODEL = os.environ.get("CITEGUARD_LARGE_MODEL", "anthropic.claude-sonnet-5-5")
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
VOYAGE_MODEL = "voyage-3.5"  # used instead of Titan whenever VOYAGE_API_KEY is set
EMBEDDING_DIM = 1024

# USD per 1M tokens (input, output). Estimates: check current Bedrock pricing before quoting a cost.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "default": (0.80, 4.00),
    "openai/gpt-oss-20b": (0.075, 0.30),  # Groq list price
}


class LLMNotConfiguredError(RuntimeError):
    """Raised when no real LLM provider is configured."""


chat_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    cooldown_seconds=30.0,
    ignored_exceptions=(LLMNotConfiguredError,),
)

embedding_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    cooldown_seconds=30.0,
    ignored_exceptions=(LLMNotConfiguredError,),
)


class ChatResponse(BaseModel):
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    cached: bool = False
    model: str = "default"


class DiskCache:
    """File-based persistent cache keyed by sha256 hash."""

    def __init__(self, cache_dir: str = ".cache/llm"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._get_path(key)
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                return None
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        # A failed cache write must not fail the request, the answer was already paid for.
        try:
            with open(self._get_path(key), "w", encoding="utf-8") as f:
                json.dump(value, f)
        except OSError:
            pass


DEFAULT_CACHE = DiskCache()


# Running totals for this process, so evaluation can measure what a question really cost.
# Cache hits are counted too: the cost shown is what the call costs at list price, not what a rerun paid.
USAGE: dict[str, float] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}


# Per-request totals (one chat answer, one report). A ContextVar, so concurrent requests never mix.
_SCOPE: ContextVar[dict[str, float] | None] = ContextVar("usage_scope", default=None)


@contextmanager
def track_usage() -> Iterator[dict[str, float]]:
    totals: dict[str, float] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    token = _SCOPE.set(totals)
    try:
        yield totals
    finally:
        _SCOPE.reset(token)
        totals["cost_usd"] = round(totals["cost_usd"], 8)


def _meter(prompt_tokens: int, completion_tokens: int, cost_usd: float) -> None:
    for totals in (USAGE, _SCOPE.get()):
        if totals is None:
            continue
        totals["calls"] += 1
        totals["prompt_tokens"] += prompt_tokens
        totals["completion_tokens"] += completion_tokens
        totals["cost_usd"] += cost_usd


def calculate_cost(prompt_tokens: int, completion_tokens: int, model: str = "default") -> float:
    """USD cost of one call, from the single price table above."""
    in_rate, out_rate = PRICE_PER_MTOK.get(model, PRICE_PER_MTOK["default"])
    return round((prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000, 8)


def generate_chat(
    prompt: str,
    system_prompt: str | None = None,
    model: str = SMALL_MODEL,
    cache: DiskCache | None = None,
    provider_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> ChatResponse:
    """Generate chat response with disk caching and cost/token accounting."""
    if cache is None:
        cache = DEFAULT_CACHE

    full_payload = f"{system_prompt or ''}\n{prompt}"
    cache_key = hashlib.sha256(f"chat:{model}:{full_payload}".encode()).hexdigest()

    cached_data = cache.get(cache_key)
    if cached_data is not None:
        _meter(cached_data["prompt_tokens"], cached_data["completion_tokens"], cached_data.get("cost_usd", 0.0))
        return ChatResponse(
            text=cached_data["text"],
            prompt_tokens=cached_data["prompt_tokens"],
            completion_tokens=cached_data["completion_tokens"],
            total_tokens=cached_data["prompt_tokens"] + cached_data["completion_tokens"],
            cost_usd=cached_data.get("cost_usd", 0.0),
            latency_ms=0.0,
            cached=True,
            model=model,
        )

    start_time = time.perf_counter()
    if provider_fn is not None:
        result = provider_fn(prompt, model)
    else:
        result = chat_circuit_breaker.call(_call_external_provider, prompt, system_prompt, model)

    latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    prompt_tokens = result.get("prompt_tokens", len(prompt.split()) + 5)
    completion_tokens = result.get("completion_tokens", len(result.get("text", "").split()))
    cost_usd = calculate_cost(prompt_tokens, completion_tokens, result.get("model", model))  # Groq fallback has its own price

    response_data = {
        "text": result.get("text", ""),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost_usd,
    }
    cache.set(cache_key, response_data)
    _meter(prompt_tokens, completion_tokens, cost_usd)

    return ChatResponse(
        text=response_data["text"],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        cached=False,
        model=model,
    )


def generate_embedding(
    text: str,
    model_version: str | None = None,
    cache: DiskCache | None = None,
    provider_fn: Callable[[str, str], list[float]] | None = None,
) -> tuple[list[float], bool]:
    """Generate a 1024-dim embedding, cached by (content hash, model version)."""
    # Chosen per call, not at import: the API loads .env at startup. Different models never share a cache entry.
    model_version = model_version or (VOYAGE_MODEL if os.environ.get("VOYAGE_API_KEY") else EMBEDDING_MODEL)
    if cache is None:
        cache = DEFAULT_CACHE

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cache_key = hashlib.sha256(f"embed:{model_version}:{content_hash}".encode()).hexdigest()

    cached_data = cache.get(cache_key)
    if cached_data is not None and "embedding" in cached_data:
        return cached_data["embedding"], True

    if provider_fn is not None:
        embedding = provider_fn(text, model_version)
    else:
        embedding = embedding_circuit_breaker.call(_call_external_embedding, text, model_version)

    cache.set(cache_key, {"embedding": embedding})
    return embedding, False


def _provider_name() -> str:
    name = os.environ.get("LLM_PROVIDER") or ("groq" if os.environ.get("GROQ_API_KEY") else "")
    if name not in {"bedrock", "groq"}:
        raise LLMNotConfiguredError(
            "No LLM provider configured. Set LLM_PROVIDER=bedrock (AWS credentials) or "
            "LLM_PROVIDER=groq with GROQ_API_KEY."
        )
    return name


def _call_external_provider(prompt: str, system_prompt: str | None, model: str) -> dict[str, Any]:
    """Chat call: Bedrock by default, Groq if LLM_PROVIDER=groq or as a fallback when Bedrock fails."""
    if _provider_name() == "bedrock":
        try:
            return _call_bedrock(prompt, system_prompt, model)
        except Exception:
            if not os.environ.get("GROQ_API_KEY"):
                raise
    return _call_groq(prompt, system_prompt)


def _call_bedrock(prompt: str, system_prompt: str | None, model: str) -> dict[str, Any]:
    import boto3

    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    kwargs: dict[str, Any] = {
        "modelId": model,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"temperature": 0.0, "maxTokens": 2048},
    }
    if system_prompt:
        kwargs["system"] = [{"text": system_prompt}]
    resp = client.converse(**kwargs)
    return {
        "text": resp["output"]["message"]["content"][0]["text"],
        "prompt_tokens": resp["usage"]["inputTokens"],
        "completion_tokens": resp["usage"]["outputTokens"],
    }


def _call_groq(prompt: str, system_prompt: str | None) -> dict[str, Any]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMNotConfiguredError("GROQ_API_KEY is not set.")
    groq_model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")  # Groq retires models; override without a deploy
    payload = {
        "model": groq_model,
        "messages": [
            *([{"role": "system", "content": system_prompt}] if system_prompt else []),
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }
    # Groq's free tier has per-minute token limits, so a 429 means wait, not fail. It also drops
    # connections now and then; temperature is 0, so sending the same request again is safe.
    for attempt in range(6):
        try:
            res = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
        except httpx.TransportError:
            if attempt == 5:
                raise
            time.sleep(5)
            continue
        if res.status_code != 429 or attempt == 5:
            break
        time.sleep(float(res.headers.get("retry-after") or 20))
    res.raise_for_status()
    data = res.json()
    usage = data.get("usage", {})
    return {
        "text": data["choices"][0]["message"]["content"],
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "model": groq_model,
    }


def _call_external_embedding(text: str, model_version: str) -> list[float]:
    """Voyage AI when VOYAGE_API_KEY is set, else Titan Embeddings v2 on Bedrock (Groq has no embeddings)."""
    if model_version.startswith("voyage"):
        return _call_voyage_embedding(text, model_version)
    if os.environ.get("LLM_PROVIDER") != "bedrock":
        raise LLMNotConfiguredError("Embeddings need VOYAGE_API_KEY, or LLM_PROVIDER=bedrock and AWS credentials.")
    import boto3

    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    body = json.dumps({"inputText": text, "dimensions": EMBEDDING_DIM, "normalize": True})
    resp = client.invoke_model(modelId=model_version, body=body)
    return json.loads(resp["body"].read())["embedding"]


def _call_voyage_embedding(text: str, model: str) -> list[float]:
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise LLMNotConfiguredError("VOYAGE_API_KEY is not set.")
    # shortcut: no input_type (query vs document), so chunks and questions embed alike; add it if recall lags.
    # Voyage's free tier without a card allows ~3 requests/min, so a 429 means wait, not fail.
    for attempt in range(6):
        res = httpx.post(
            "https://api.voyageai.com/v1/embeddings",
            json={"input": [text], "model": model, "output_dimension": EMBEDDING_DIM},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        if res.status_code != 429 or attempt == 5:
            break
        time.sleep(float(res.headers.get("retry-after") or 20))
    res.raise_for_status()
    return res.json()["data"][0]["embedding"]
