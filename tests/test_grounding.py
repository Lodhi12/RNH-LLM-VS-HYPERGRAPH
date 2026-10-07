from rnh.claims.grounding import align_text, ground_surface


def test_exact_alignment_reports_source_offsets_and_repetition() -> None:
    source = "alpha beta; alpha beta"
    result = align_text(source, "alpha beta")

    assert result is not None
    assert result.start == 0
    assert result.end == 10
    assert result.match_count == 2
    assert result.method == "exact"
    assert result.source_text == "alpha beta"


def test_whitespace_alignment_maps_back_to_original_source() -> None:
    source = "The army did not\nenter   the town."
    result = align_text(source, "The army did not enter the town.")

    assert result is not None
    assert result.method == "whitespace_normalized"
    assert result.source_text == source
    assert source[result.start : result.end] == result.source_text


def test_ground_surface_uses_evidence_relative_offsets() -> None:
    evidence = [{"evidence_id": "evidence:1", "quote": "Rahman recalled the event."}]
    result = ground_surface("recalled", evidence)

    assert result == {
        "evidence_id": "evidence:1",
        "quote_char_start": 7,
        "quote_char_end": 15,
        "match_count": 1,
    }


def test_missing_surface_is_not_grounded() -> None:
    assert align_text("source text", "invented") is None


def test_source_normalization_handles_quotes_and_line_wrap_hyphens() -> None:
    source = "The ‘Indo-\nPak’ narrative shaped nation-\nmaking."
    submitted = "The 'Indo-Pak' narrative shaped nation-making."
    result = align_text(source, submitted)

    assert result is not None
    assert result.method == "source_normalized"
    assert result.source_text == source


def test_source_normalization_handles_pdf_soft_hyphen() -> None:
    result = align_text("Calcutta Uni\u00adversity", "Calcutta Uni-versity")

    assert result is not None
    assert result.method == "source_normalized"


def test_source_normalization_handles_line_break_before_dash() -> None:
    source = "Pakistan, Bangladesh and India\n—all have a narrative."
    result = align_text(source, "Pakistan, Bangladesh and India—all have a narrative.")

    assert result is not None
    assert result.method == "source_normalized"
