from rnh.claims.review import _render_report


def _report(run: dict) -> str:
    return _render_report(
        run=run,
        summary={},
        validation={},
        claims=[],
        frames=[],
        books={},
    )


def test_limited_run_is_reported_as_a_pilot() -> None:
    report = _report({"limit_units_per_book": 8})

    assert report.startswith("# Pilot Claim Candidate Extraction Report")
    assert "Run scope: pilot limited to the first 8 planned claim-input units per book" in report


def test_unlimited_run_is_reported_as_full_corpus() -> None:
    report = _report({"limit_units_per_book": None})

    assert report.startswith("# Full-Corpus Claim Candidate Extraction Report")
    assert "Run scope: full corpus (no per-book unit limit)" in report
