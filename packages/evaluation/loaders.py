"""Data loaders for golden questions and verifier pairs."""

import json
from pathlib import Path

from packages.evaluation.schemas import GoldenQuestion, VerifierPair


def load_golden_questions(path: str | Path) -> list[GoldenQuestion]:
    """Load and validate golden questions from a JSONL file."""
    path = Path(path)
    if not path.exists():
        return []

    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                questions.append(GoldenQuestion.model_validate(data))
    return questions


def load_verifier_pairs(path: str | Path) -> list[VerifierPair]:
    """Load and validate verifier pairs from a JSONL file."""
    path = Path(path)
    if not path.exists():
        return []

    pairs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                pairs.append(VerifierPair.model_validate(data))
    return pairs
