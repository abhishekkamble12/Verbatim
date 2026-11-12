from packages.verification.fuzzy import VerificationVerdict, verify_claim_against_quote


def test_altered_digit_rejection():
    """Verify that altered digits (e.g., 12.5% vs 13.5%) fail verification."""
    quote = "The operating margin increased by 12.5% in the fourth quarter."
    claim = "The operating margin increased by 13.5% in the fourth quarter."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.UNSUPPORTED
    assert "number mismatch" in result.reason.lower() or "digit mismatch" in result.reason.lower()


def test_changed_date_rejection():
    """Verify that altered dates (e.g., 2023 vs 2024) fail verification."""
    quote = "The policy went into effect on March 15, 2023."
    claim = "The policy went into effect on March 15, 2024."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.UNSUPPORTED
    assert "date mismatch" in result.reason.lower() or "number mismatch" in result.reason.lower()


def test_changed_unit_rejection():
    """Verify that changed units (e.g., million vs billion, km vs miles) fail verification."""
    quote = "The company raised $100 million in series B funding."
    claim = "The company raised $100 billion in series B funding."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.UNSUPPORTED
    assert "unit mismatch" in result.reason.lower() or "number mismatch" in result.reason.lower()


def test_negation_rejection():
    """Verify that negation flipping (did not improve vs improved) fails verification."""
    quote = "The clinical trial results did not improve patient recovery times."
    claim = "The clinical trial results improved patient recovery times."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.UNSUPPORTED
    assert "negation mismatch" in result.reason.lower() or "polarity mismatch" in result.reason.lower()


def test_wrong_entity_rejection():
    """Verify that mismatched entity names fail verification."""
    # Mid-sentence: a plain capitalised first word ("Generation", "Moderna") cannot be told from an
    # ordinary word without a dictionary, so stage 1 leaves those to the stage-2 entailment check.
    quote = "Record earnings in the oncology portfolio were reported by Pfizer."
    claim = "Record earnings in the oncology portfolio were reported by Moderna."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.UNSUPPORTED
    assert "entity mismatch" in result.reason.lower()


def test_partial_support_detection():
    """Verify that claims with broader scope than the quote are marked PARTIAL."""
    quote = "Revenue grew by 15% across our Asian markets."
    claim = "Worldwide revenue grew by 15%."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.PARTIAL
    assert "partial" in result.reason.lower() or "scope" in result.reason.lower()


def test_exact_match_support():
    """Verify that exact matches pass with SUPPORTS."""
    quote = "Operating margin increased by 12.5% in the fourth quarter."
    claim = "Operating margin increased by 12.5% in the fourth quarter."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.SUPPORTS


def test_approximate_tolerance_allowed():
    """Verify that when claim uses 'about', 'approximately', or '~', tolerance is granted."""
    quote = "The project finished in 52 days."
    claim = "The project finished in about 50 days."
    result = verify_claim_against_quote(claim=claim, quote=quote)
    assert result.verdict == VerificationVerdict.SUPPORTS

    claim_approx = "The project finished in approximately 50 days."
    assert verify_claim_against_quote(claim=claim_approx, quote=quote).verdict == VerificationVerdict.SUPPORTS

    claim_tilde = "The project finished in ~50 days."
    assert verify_claim_against_quote(claim=claim_tilde, quote=quote).verdict == VerificationVerdict.SUPPORTS


def test_approximate_still_rejects_far_numbers():
    """'about 3%' must not match '8%' (old rule allowed any gap <= 5)."""
    v = verify_claim_against_quote("Revenue was about 3%.", "Revenue was 8%.")
    assert v.verdict == VerificationVerdict.UNSUPPORTED


def test_approximate_still_checks_units():
    """'about 50 days' must not match '52%'."""
    v = verify_claim_against_quote("The trial lasted about 50 days.", "Accuracy reached 52%.")
    assert v.verdict == VerificationVerdict.UNSUPPORTED


def test_written_numbers_are_compared():
    """'twelve percent' vs 'three percent' must be rejected; same words must pass."""
    bad = verify_claim_against_quote("Revenue grew twelve percent.", "Revenue grew three percent.")
    assert bad.verdict == VerificationVerdict.UNSUPPORTED
    ok = verify_claim_against_quote("Revenue grew 12%.", "Revenue grew twelve percent.")
    assert ok.verdict == VerificationVerdict.SUPPORTS


def test_thousands_separator_is_one_number():
    ok = verify_claim_against_quote("Revenue was $1,200 million.", "Revenue was $1,200 million.")
    assert ok.verdict == VerificationVerdict.SUPPORTS
    bad = verify_claim_against_quote("Revenue was $1,200 million.", "Revenue was $1,300 million.")
    assert bad.verdict == VerificationVerdict.UNSUPPORTED


def test_global_word_inside_other_word_is_not_global_scope():
    """'overall' contains 'all' and 'local' is a regional term; neither should trigger PARTIAL."""
    v = verify_claim_against_quote("Overall revenue grew 15%.", "Revenue grew 15% in local currency terms.")
    assert v.verdict == VerificationVerdict.SUPPORTS


def test_unrelated_no_in_quote_does_not_flip_polarity():
    v = verify_claim_against_quote(
        "The drug improved recovery.", "The drug improved recovery, with no serious side effects."
    )
    assert v.verdict == VerificationVerdict.SUPPORTS


def test_possessive_entity_matches_plain_name():
    from packages.verification.fuzzy import (
        VerificationVerdict,
        extract_capitalized_entities,
        verify_claim_against_quote,
    )

    assert extract_capitalized_entities("Revenue at Acme's stores and Acme’s, rose.") == {"Acme"}
    quote = "Acme Corp reported consolidated revenue of $482 million in Q3."
    assert verify_claim_against_quote("Acme's total revenue in Q3 was $482 million.", quote).verdict == VerificationVerdict.SUPPORTS


def test_model_names_with_hyphens_and_dots_match_the_quote():
    # Found on real arXiv quotes: "R1-Qwen3-8B" was compared as "R1Qwen38B" against the raw quote.
    quote = "A similar pattern appears on code generation, where R1-Qwen3-8B improves from 0.382 to 0.514."
    result = verify_claim_against_quote("On code generation, R1-Qwen3-8B improves from 0.382 to 0.514.", quote)
    assert result.verdict == VerificationVerdict.SUPPORTS


def test_entity_split_by_a_pdf_line_break_still_matches():
    quote = "Qwen3.5- 4B exhibits the highest and most persistent leakage with nearly 50% at early"
    result = verify_claim_against_quote("Qwen3.5-4B shows leakage of nearly 50% at early exits.", quote)
    assert result.verdict == VerificationVerdict.SUPPORTS


def test_ordinary_first_word_is_not_an_entity():
    result = verify_claim_against_quote("Generation used a temperature of 0.6.", "All use temperature of 0.6.")
    assert result.verdict == VerificationVerdict.SUPPORTS


def test_wrong_model_name_at_sentence_start_is_still_rejected():
    quote = "Initially, we used Qwen2.5-7B as the verification model."
    result = verify_claim_against_quote("Qwen2.5-72B was the initial verification model.", quote)
    assert result.verdict == VerificationVerdict.UNSUPPORTED
