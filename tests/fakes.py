"""Scripted stand-in for the LLM, used by tests only. Production code never imports this."""

import hashlib
import json
import random
import re
from typing import Any


def scripted_chat(prompt: str, system_prompt: str | None, model: str) -> dict[str, Any]:
    if "PLAN:" in prompt:
        q = re.search(r"Question:\s*(.+)", prompt)
        q_str = q.group(1).strip() if q else "the question"
        return {
            "text": json.dumps({"sub_questions": [f"Details on {q_str}", f"Context and timeline for {q_str}"]}),
            "prompt_tokens": 60,
            "completion_tokens": 30,
        }

    if "RESEARCH:" in prompt:
        cids = re.findall(r"\[([^\]]+)\]:", prompt)
        first = re.search(r"\[[^\]]+\]:\s*([^\n]+)", prompt)
        claim = first.group(1).strip() if first else "No evidence."
        claims = [{"text": claim, "citations": [{"chunk_id": cids[0]}]}] if cids else []
        return {"text": json.dumps({"claims": claims}), "prompt_tokens": 120, "completion_tokens": 40}

    if "Return your answer and claims as JSON" in prompt:
        ids = re.findall(r"\[Chunk ID: ([^\]]+)\]", prompt)
        text_match = re.search(r"\[Chunk ID: [^\]]+\][^\n]*\n([^\n]+)", prompt)
        claim = text_match.group(1).strip() if text_match else "The evidence supports the reported metrics."
        payload = {
            "answer": claim,
            "claims": [{"text": claim, "citations": [{"chunk_id": ids[0] if ids else "chunk_1"}]}],
            "insufficient_evidence": False,
        }
        return {"text": json.dumps(payload), "prompt_tokens": 65, "completion_tokens": 30}

    if "Evaluate entailment as JSON" in prompt:
        return {
            "text": json.dumps({"verdict": "supports", "reason": "Claim is supported by quote."}),
            "prompt_tokens": 25,
            "completion_tokens": 15,
        }

    # Query rewrite and anything else: echo something non-empty.
    return {"text": f"Processed query regarding: {prompt[:40]}", "prompt_tokens": 20, "completion_tokens": 10}


def hash_embedding(text: str, model_version: str) -> list[float]:
    """Different text gives a different vector (a constant vector makes every cosine score equal)."""
    rng = random.Random(hashlib.sha256(text.encode()).digest())
    return [rng.uniform(-1, 1) for _ in range(1024)]
