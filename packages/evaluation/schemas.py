"""Pydantic schemas for evaluation datasets."""

from typing import Literal

from pydantic import BaseModel, Field

QuestionCategory = Literal[
    "factual",
    "numerical",
    "multi-document",
    "multi-hop",
    "comparative",
    "temporal",
    "unanswerable",
    "conflicting",
]

VerifierLabel = Literal["supports", "partial", "unsupported"]


class GoldenQuestion(BaseModel):
    id: str
    question: str
    category: QuestionCategory
    expected_answer: str
    gold_passages: list[str] = Field(default_factory=list)
    gold_chunk_ids: list[str] = Field(default_factory=list)
    relevant_source_ids: list[str] = Field(default_factory=list)
    answerable: bool = True


class VerifierPair(BaseModel):
    id: str
    claim: str
    quote: str
    gold_label: VerifierLabel
    source_id: str | None = None
    reason: str | None = None
