from pathlib import Path

import pytest

from packages.llm_gateway.gateway import (
    PRICE_PER_MTOK,
    DiskCache,
    LLMNotConfiguredError,
    calculate_cost,
    generate_chat,
    generate_embedding,
)


def test_chat_disk_caching_and_accounting(tmp_path: Path):
    """Verify first call executes provider, second call hits cache without calling provider."""
    cache = DiskCache(cache_dir=str(tmp_path / "cache"))
    call_count = 0

    def fake_chat_provider(prompt: str, model: str):
        nonlocal call_count
        call_count += 1
        return {
            "text": f"Response to: {prompt}",
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }

    # 1. First call -> misses cache, calls provider
    res1 = generate_chat(
        prompt="Explain quantum entanglement",
        cache=cache,
        provider_fn=fake_chat_provider,
        model="fake-model",
    )
    assert call_count == 1
    assert res1.cached is False
    assert res1.text == "Response to: Explain quantum entanglement"
    assert res1.prompt_tokens == 10
    assert res1.cost_usd > 0.0

    # 2. Second identical call -> hits disk cache, provider count remains 1
    res2 = generate_chat(
        prompt="Explain quantum entanglement",
        cache=cache,
        provider_fn=fake_chat_provider,
        model="fake-model",
    )
    assert call_count == 1
    assert res2.cached is True
    assert res2.text == res1.text


def test_embedding_disk_caching(tmp_path: Path):
    """Verify embedding cache keyed by (content hash, model version)."""
    cache = DiskCache(cache_dir=str(tmp_path / "embed_cache"))
    call_count = 0

    def fake_embed_provider(text: str, model_version: str):
        nonlocal call_count
        call_count += 1
        return [0.1] * 1024

    # First call -> computes embedding
    emb1, cached1 = generate_embedding(
        text="Sample paragraph for embedding",
        cache=cache,
        provider_fn=fake_embed_provider,
        model_version="titan-v2",
    )
    assert call_count == 1
    assert cached1 is False
    assert len(emb1) == 1024

    # Second call -> hits cache
    emb2, cached2 = generate_embedding(
        text="Sample paragraph for embedding",
        cache=cache,
        provider_fn=fake_embed_provider,
        model_version="titan-v2",
    )
    assert call_count == 1
    assert cached2 is True
    assert emb1 == emb2


@pytest.mark.real_gateway
def test_no_provider_configured_raises(monkeypatch):
    """With no provider set, the gateway must fail loudly, never invent an answer."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMNotConfiguredError):
        generate_chat(prompt="hello")
    with pytest.raises(LLMNotConfiguredError):
        generate_embedding(text="hello")


def test_one_price_table():
    assert calculate_cost(1_000_000, 0, "any-model") == PRICE_PER_MTOK["default"][0]


@pytest.mark.real_gateway
def test_voyage_embeddings_when_key_is_set(monkeypatch, tmp_path):
    from packages.llm_gateway import gateway

    sent = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"embedding": [0.5] * 1024}]}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, body=json, auth=headers["Authorization"])
        return Resp()

    monkeypatch.setenv("VOYAGE_API_KEY", "vk")
    monkeypatch.setattr(gateway.httpx, "post", fake_post)
    vec, cached = generate_embedding("hello", cache=DiskCache(str(tmp_path / "c")))
    assert (len(vec), cached) == (1024, False)
    assert sent["url"].startswith("https://api.voyageai.com/")
    assert sent["body"]["model"] == "voyage-3.5" and sent["body"]["output_dimension"] == 1024
    assert sent["auth"] == "Bearer vk"


@pytest.mark.real_gateway
def test_embeddings_without_any_provider_raise(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    with pytest.raises(LLMNotConfiguredError):
        generate_embedding("hello")


def test_cost_uses_the_model_that_answered(tmp_path):
    resp = generate_chat(
        "q", cache=DiskCache(str(tmp_path / "c")),
        provider_fn=lambda p, m: {"text": "a", "prompt_tokens": 1_000_000, "completion_tokens": 0, "model": "openai/gpt-oss-20b"},
    )
    assert resp.cost_usd == PRICE_PER_MTOK["openai/gpt-oss-20b"][0]  # Groq's rate, not the Bedrock default


@pytest.mark.real_gateway
def test_voyage_rate_limit_waits_and_retries(monkeypatch):
    from packages.llm_gateway import gateway

    class Resp:
        def __init__(self, code):
            self.status_code, self.headers = code, {"retry-after": "7"} if code == 429 else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise gateway.httpx.HTTPStatusError("x", request=None, response=self)

        def json(self):
            return {"data": [{"embedding": [0.0] * 1024}]}

    replies, slept = [Resp(429), Resp(429), Resp(200)], []
    monkeypatch.setenv("VOYAGE_API_KEY", "vk")
    monkeypatch.setattr(gateway.httpx, "post", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr(gateway.time, "sleep", slept.append)
    assert len(gateway._call_voyage_embedding("hi", "voyage-3.5")) == 1024
    assert slept == [7.0, 7.0]  # honours Retry-After


@pytest.mark.real_gateway
def test_groq_rate_limit_waits_and_retries(monkeypatch):
    from packages.llm_gateway import gateway

    class Resp:
        def __init__(self, code):
            self.status_code, self.headers = code, {"retry-after": "3"} if code == 429 else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise gateway.httpx.HTTPStatusError("x", request=None, response=self)

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    replies, slept = [Resp(429), Resp(200)], []
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setattr(gateway.httpx, "post", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr(gateway.time, "sleep", slept.append)
    assert gateway._call_groq("hi", None)["text"] == "ok"
    assert slept == [3.0]  # honours Retry-After


@pytest.mark.real_gateway
def test_groq_dropped_connection_is_retried(monkeypatch):
    from packages.llm_gateway import gateway

    class Ok:
        status_code, headers = 200, {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    calls = []

    def post(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise gateway.httpx.RemoteProtocolError("Server disconnected")
        return Ok()

    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setattr(gateway.httpx, "post", post)
    monkeypatch.setattr(gateway.time, "sleep", lambda s: None)
    assert gateway._call_groq("hi", None)["text"] == "ok"
    assert len(calls) == 2
