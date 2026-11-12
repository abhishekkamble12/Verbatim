"""Follow-up query rewriting using conversation history."""

from collections.abc import Callable
from typing import Any

from packages.llm_gateway.gateway import SMALL_MODEL, generate_chat

REWRITE_SYSTEM_PROMPT = """You are a query rewriting assistant.
Given a conversation history and a follow-up query, rewrite the follow-up query into a single, fully self-contained search query.
Resolve all pronouns and implicit references. Do not answer the question; only return the rewritten query text."""


def rewrite_query_if_followup(
    query: str,
    conversation_history: list[dict[str, str]] | None = None,
    provider_fn: Callable[[str, str], dict[str, Any]] | None = None,
    model: str = SMALL_MODEL,
) -> tuple[str, bool]:
    """Rewrite follow-up query ONLY when conversation has prior turns.

    Returns:
        (rewritten_query, was_rewritten)
    """
    # Rule: Query rewriting is only performed when prior turns exist
    if not conversation_history:
        return query, False

    history_lines = []
    for turn in conversation_history[-4:]:  # inspect last 4 turns
        role = turn.get("role", "user").capitalize()
        content = turn.get("content", "")
        history_lines.append(f"{role}: {content}")

    prompt = (
        f"Conversation History:\n{chr(10).join(history_lines)}\n\n"
        f"Follow-up Query: {query}\n\n"
        "Rewritten Standalone Query:"
    )

    if provider_fn is not None:
        result = provider_fn(prompt, model)
        rewritten = result.get("text", "").strip()
    else:
        chat_res = generate_chat(
            prompt=prompt,
            system_prompt=REWRITE_SYSTEM_PROMPT,
            model=model,
        )
        rewritten = chat_res.text.strip()

    clean_rewritten = rewritten.strip('"').strip("'")
    if not clean_rewritten:
        return query, False

    return clean_rewritten, True

