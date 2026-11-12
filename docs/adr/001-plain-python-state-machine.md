# ADR-001: Plain Python State Machine over Agent Frameworks (LangGraph/CrewAI)

## Status
Accepted

## Context
CiteGuard requires a multi-step research agent (Report Agent) that decomposes complex research questions into sub-questions, executes focused retrieval, verifies extracted claims against source quotes, retries when evidence is missing, and composes an evidence-backed report.

Many standard GenAI projects adopt third-party orchestration frameworks like LangChain, LangGraph, AutoGen, or CrewAI. However, in production systems and technical evaluation, these frameworks introduce heavy dependency trees, opaque abstractions, non-deterministic loop behaviors, and hidden token costs that make budget enforcement and debugging difficult.

## Decision
Implement the Report Agent as a plain Python state machine (`PLAN -> RESEARCH -> COMPOSE -> DONE`) with explicit state transitions and hard budget limits:
- Maximum 4 sub-questions.
- Exactly 1 retry per sub-question.
- Maximum 12 total LLM calls (counting both generation and verification calls).
- Strict token cap.
- Graceful halting upon budget exhaustion with explicit `is_partial = True` markers.
- Step traces recorded in PostgreSQL (`agent_steps`).

## Consequences
### Positive
- **Deterministic budget enforcement**: Every LLM call passes through the meter; no runaway loops or surprise bills.
- **High testability**: Every state transition is independently unit-testable using deterministic fakes without mocking framework internals.
- **Zero bloat**: Zero external agent framework dependencies.
- **Architectural defensibility in interviews**: Clear, defensible design where every line of code can be explained down to the byte.

### Negative
- Adding new dynamic branching requires writing explicit state transition methods rather than configuring framework graphs.

