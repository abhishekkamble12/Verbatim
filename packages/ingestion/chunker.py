"""Structure-aware document chunking with character-offset preservation."""

import hashlib
import re

from pydantic import BaseModel


class DocumentChunk(BaseModel):
    text: str
    page_number: int
    section: str
    start_char: int
    end_char: int
    token_count: int
    sha256: str


def estimate_token_count(text: str) -> int:
    """Approximate token count based on whitespace word splits (approx 1.3 tokens per word)."""
    words = text.strip().split()
    return max(1, int(len(words) * 1.3))


def extract_sentence_spans(page_text: str) -> list[tuple[int, int]]:
    """Extract (start_char, end_char) spans for all sentences in page_text."""
    spans = []
    # Match non-empty sentence-like units ending with ., !, ?, or end of string
    pattern = re.compile(r"\S.*?(?:[.!?](?=\s+|$)|$)", re.DOTALL)
    for match in pattern.finditer(page_text):
        start = match.start()
        end = match.end()
        if page_text[start:end].strip():
            spans.append((start, end))
    return spans


def chunk_page_text(
    page_text: str,
    page_number: int = 1,
    section: str = "General",
    max_tokens: int = 500,
    overlap_tokens: int = 80,
) -> list[DocumentChunk]:
    """Slice page_text into sentence-bounded chunks maintaining exact character offsets.

    Guarantees: page_text[start_char:end_char] == chunk.text
    """
    clean_text = page_text
    if not clean_text or not clean_text.strip():
        return []

    sentence_spans = extract_sentence_spans(clean_text)
    if not sentence_spans:
        # Fallback for single line without punctuation
        start = 0
        end = len(clean_text)
        text_slice = clean_text[start:end]
        sha = hashlib.sha256(text_slice.encode("utf-8")).hexdigest()
        return [
            DocumentChunk(
                text=text_slice,
                page_number=page_number,
                section=section,
                start_char=start,
                end_char=end,
                token_count=estimate_token_count(text_slice),
                sha256=sha,
            )
        ]

    chunks = []
    i = 0
    num_sentences = len(sentence_spans)

    while i < num_sentences:
        start_idx = sentence_spans[i][0]
        end_idx = sentence_spans[i][1]
        current_tokens = 0
        j = i

        while j < num_sentences:
            candidate_end = sentence_spans[j][1]
            span_text = clean_text[start_idx:candidate_end]
            tokens = estimate_token_count(span_text)

            if tokens > max_tokens and j > i:
                # Exceeds max tokens and we already have at least one sentence
                break

            end_idx = candidate_end
            current_tokens = tokens
            j += 1

            if current_tokens >= max_tokens:
                break

        chunk_text = clean_text[start_idx:end_idx]
        sha = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        chunks.append(
            DocumentChunk(
                text=chunk_text,
                page_number=page_number,
                section=section,
                start_char=start_idx,
                end_char=end_idx,
                token_count=current_tokens,
                sha256=sha,
            )
        )

        if j >= num_sentences:
            break

        # Calculate overlap for next chunk
        # Step back sentences until overlap is within overlap_tokens
        step_back_j = j
        accumulated_overlap = 0
        while step_back_j > i + 1:
            step_back_j -= 1
            prev_sentence = clean_text[sentence_spans[step_back_j][0] : end_idx]
            accumulated_overlap = estimate_token_count(prev_sentence)
            if accumulated_overlap >= overlap_tokens:
                break

        i = step_back_j if step_back_j > i else j

    return chunks



def chunk_fixed(
    page_text: str,
    page_number: int = 1,
    section: str = "General",
    max_tokens: int = 500,
    overlap_tokens: int = 80,
) -> list[DocumentChunk]:
    """Baseline chunker for ablation E1: fixed-size word windows that ignore sentence boundaries.

    Same offset guarantee as chunk_page_text: page_text[start_char:end_char] == chunk.text.
    """
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", page_text)]
    size = max(1, int(max_tokens / 1.3))
    step = max(1, size - int(overlap_tokens / 1.3))
    chunks = []
    for i in range(0, len(words), step):
        window = words[i : i + size]
        start, end = window[0][0], window[-1][1]
        text = page_text[start:end]
        chunks.append(
            DocumentChunk(
                text=text,
                page_number=page_number,
                section=section,
                start_char=start,
                end_char=end,
                token_count=estimate_token_count(text),
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
        if i + size >= len(words):
            break
    return chunks
