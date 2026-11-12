"""Deterministic stage-1 fuzzy and strict factual verification."""

import re
from dataclasses import dataclass
from enum import StrEnum


class VerificationVerdict(StrEnum):
    SUPPORTS = "SUPPORTS"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class VerificationResult:
    verdict: VerificationVerdict
    reason: str
    confidence: float = 1.0


# Regex patterns for entities, numbers, dates, and units
APPROXIMATE_PATTERN = re.compile(r"\b(about|approximately|approx|around|roughly|nearly)\b|~", re.IGNORECASE)
# shortcut: "no"/"none" are left out (they usually negate a noun, e.g. "no side effects"), stage 2 LLM catches "no improvement".
NEGATION_WORDS = {"not", "never", "didn't", "did not", "cannot", "can't", "failed"}
UNIT_SCALES = {
    "million": 1e6,
    "billion": 1e9,
    "trillion": 1e12,
    "thousand": 1e3,
    "k": 1e3,
    "m": 1e6,
    "b": 1e9,
}
GLOBAL_TERMS = {"worldwide", "globally", "global", "universal", "all"}
REGIONAL_TERMS = {"asian", "asia", "europe", "european", "north american", "domestic"}
# shortcut: sentence-initial words cannot be told from proper nouns without NER, so common openers are listed; add more when eval shows a miss.
STOP_WORDS_AT_START = {
    "the", "a", "an", "this", "our", "in", "on", "revenue", "operating", "worldwide", "globally", "global",
    "overall", "however", "also", "thus", "therefore", "additionally", "total", "net", "it", "they", "there",
}


_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_UNIT_WORDS = r"(?:%|percent|per cent|million|billion|trillion|thousand|km|miles|meters|days|weeks|months|years)"
_WORD_NUMBER = re.compile(
    rf"\b((?:{'|'.join(_TENS)})(?:[-\s](?:{'|'.join(list(_ONES)[1:10])}))?|{'|'.join(_ONES)})\b(?=\s*{_UNIT_WORDS})",
    re.IGNORECASE,
)


# "one" is also a pronoun ("no one", "one of"), so it only converts before a unit; other words always convert.
_WORD_NUMBER_ANY = re.compile(
    rf"\b((?:{'|'.join(_TENS)})(?:[-\s](?:{'|'.join(list(_ONES)[2:10])}))?|{'|'.join(w for w in _ONES if w != 'one')})\b",
    re.IGNORECASE,
)


def _words_to_digits(match: re.Match) -> str:
    return str(sum(_TENS.get(w, _ONES.get(w, 0)) for w in re.split(r"[-\s]", match.group(1).lower())))


def normalize_numbers(text: str) -> str:
    """Make '1,200', 'twelve percent' and '12%' comparable. "one" only counts before a unit."""
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    text = _WORD_NUMBER.sub(_words_to_digits, text)
    text = _WORD_NUMBER_ANY.sub(_words_to_digits, text)
    return re.sub(r"\s*(?:percent|per cent)\b", "%", text, flags=re.IGNORECASE)


def extract_numbers_and_units(text: str) -> list[dict]:
    """Extract numbers along with associated currency, percentage, and scale units."""
    text = normalize_numbers(text)
    results = []
    pattern = re.compile(
        r"(\$|€|£)?\s*(\d+(?:\.\d+)?)\s*(%|million|billion|trillion|thousand|km|miles|meters|days|weeks|months|years)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        currency, val_str, unit = match.groups()
        if not val_str:
            continue
        val = float(val_str)
        unit = (unit or "").lower()
        currency = currency or ""
        effective_val = val
        if unit in UNIT_SCALES:
            effective_val = val * UNIT_SCALES[unit]
        results.append({
            "raw": match.group(0).strip(),
            "val": val,
            "effective_val": effective_val,
            "unit": unit,
            "currency": currency,
        })
    return results


DIRECTION_UP = {"increase", "increased", "increasing", "rose", "rising", "grow", "grew", "growth", "gain", "gained", "climbed", "expanded", "expansion"}
DIRECTION_DOWN = {"decrease", "decreased", "decreasing", "fell", "falling", "drop", "dropped", "declined", "decline", "loss", "lost", "contracted", "contraction"}


def _has_term(text: str, terms: set[str]) -> bool:
    """Whole-word match, so 'all' does not fire inside 'overall' or 'local' inside 'locally'."""
    return any(re.search(rf"\b{re.escape(t)}\b", text) for t in terms)


def has_directional_conflict(claim: str, quote: str) -> bool:
    """Check if claim asserts positive direction while quote asserts negative, or vice versa."""
    claim_words = set(re.findall(r"\b\w+\b", claim.lower()))
    quote_words = set(re.findall(r"\b\w+\b", quote.lower()))

    claim_up = bool(claim_words.intersection(DIRECTION_UP))
    claim_down = bool(claim_words.intersection(DIRECTION_DOWN))
    quote_up = bool(quote_words.intersection(DIRECTION_UP))
    quote_down = bool(quote_words.intersection(DIRECTION_DOWN))

    if (claim_up and quote_down and not quote_up) or (claim_down and quote_up and not quote_down):
        return True
    return False


def has_negation(text: str) -> bool:
    """Check if the text contains explicit negation keywords."""
    words = re.findall(r"\b\w+(?:'\w+)?\b", text.lower())
    return any(w in NEGATION_WORDS for w in words) or "did not" in text.lower() or "failed to" in text.lower()


def extract_capitalized_entities(text: str) -> set[str]:
    """Extract potential proper nouns / entity names (excluding sentence start and common stop words)."""
    sentences = re.split(r"[.!?]\s+", text)
    entities = set()
    for s in sentences:
        words = s.strip().split()
        if not words:
            continue
        for i, word in enumerate(words):
            clean = re.sub(r"[^\w]", "", re.sub(r"['’]s\b", "", word))  # "Acme's" names Acme
            if not clean:
                continue
            if clean.lower() in STOP_WORDS_AT_START:
                continue
            if clean.isupper() and len(clean) > 1:
                entities.add(clean)
            elif i > 0 and clean[0].isupper() and not clean.isupper():
                entities.add(clean)
            elif i == 0 and any(ch.isdigit() or ch.isupper() for ch in clean[1:]):
                # A sentence's first word is capitalised anyway; only a digit or inner capital
                # ("Qwen3-8B", "DeepSeek") marks it as a name. Stage 2 judges the rest.
                entities.add(clean)
    return entities


def verify_claim_against_quote(claim: str, quote: str) -> VerificationResult:
    """Stage 1 deterministic verification.

    Checks:
    1. Polarity / Negation match.
    2. Scope / Partial support detection.
    3. Exact entity presence.
    4. Strict numeric, date, and unit match (unless claim has approx qualifiers).
    """
    is_approximate = bool(APPROXIMATE_PATTERN.search(claim))

    # 1. Check Polarity / Negation
    claim_neg = has_negation(claim)
    quote_neg = has_negation(quote)
    if claim_neg != quote_neg:
        return VerificationResult(
            verdict=VerificationVerdict.UNSUPPORTED,
            reason=f"Negation mismatch: claim polarity ({'negative' if claim_neg else 'positive'}) conflicts with quote polarity ({'negative' if quote_neg else 'positive'}).",
        )

    if has_directional_conflict(claim, quote):
        return VerificationResult(
            verdict=VerificationVerdict.UNSUPPORTED,
            reason="Directional conflict: claim asserts an opposite trajectory (increase vs decrease) relative to quote.",
        )

    # 2. Check Scope / Partial Support (e.g. worldwide vs regional)
    claim_lower = claim.lower()
    quote_lower = quote.lower()
    if _has_term(claim_lower, GLOBAL_TERMS) and _has_term(quote_lower, REGIONAL_TERMS) and not _has_term(quote_lower, GLOBAL_TERMS):
        return VerificationResult(
            verdict=VerificationVerdict.PARTIAL,
            reason="Partial support: claim asserts global scope while quote provides only regional scope.",
        )

    # 3. Check Entities
    claim_entities = extract_capitalized_entities(claim)
    # Entities are compared without punctuation or spaces, so "R1-Qwen3-8B" matches the quote's
    # "R1-Qwen3-8B" and a name a PDF line break split in two ("Qwen3.5- 4B").
    quote_squashed = re.sub(r"[^\w]", "", quote.lower())
    for ent in claim_entities:
        if ent.lower() not in quote_squashed:
            return VerificationResult(
                verdict=VerificationVerdict.UNSUPPORTED,
                reason=f"Entity mismatch: entity '{ent}' in claim is not supported by quote.",
            )

    # 4. Check Numbers, Dates, and Units
    claim_nums = extract_numbers_and_units(claim)
    quote_nums = extract_numbers_and_units(quote)

    if claim_nums:
        for c_num in claim_nums:
            matched = False
            for q_num in quote_nums:
                same_unit = c_num["currency"] == q_num["currency"] and (
                    c_num["unit"] == q_num["unit"] or (c_num["unit"] in UNIT_SCALES and q_num["unit"] in UNIT_SCALES)
                )
                if not same_unit:
                    continue
                if is_approximate:
                    rel_diff = abs(c_num["effective_val"] - q_num["effective_val"]) / max(abs(q_num["effective_val"]), 1e-6)
                    if rel_diff <= 0.15:
                        matched = True
                        break
                elif c_num["effective_val"] == q_num["effective_val"]:
                    matched = True
                    break

            if not matched:
                unit_mismatch = any(
                    c_num["val"] == q_num["val"] and (c_num["unit"] != q_num["unit"] or c_num["currency"] != q_num["currency"])
                    for q_num in quote_nums
                )
                if unit_mismatch:
                    return VerificationResult(
                        verdict=VerificationVerdict.UNSUPPORTED,
                        reason=f"Unit mismatch: number {c_num['raw']} in claim conflicts with units in quote.",
                    )
                if len(str(int(c_num["val"]))) == 4 and 1900 <= c_num["val"] <= 2100:
                    return VerificationResult(
                        verdict=VerificationVerdict.UNSUPPORTED,
                        reason=f"Date mismatch: year {int(c_num['val'])} in claim is not in quote.",
                    )
                return VerificationResult(
                    verdict=VerificationVerdict.UNSUPPORTED,
                    reason=f"Number mismatch: value {c_num['raw']} in claim is unsupported by quote.",
                )

    return VerificationResult(
        verdict=VerificationVerdict.SUPPORTS,
        reason="Claim is supported by quote.",
    )
