from __future__ import annotations

import copy
import json
import random
from pathlib import Path

from jsonschema import Draft202012Validator

from rnh.claims.io import BookInput, ClaimUnit, SourceSpan
from rnh.claims.pipeline import ClaimPipeline, PipelineAssets, PipelineConfig
from rnh.claims.providers import ReplayProvider
from rnh.claims.review import _stratified_sample, build_review_artifacts, validate_run


ROOT = Path(__file__).resolve().parents[1]


def example_candidate() -> dict:
    examples = json.loads((ROOT / "prompts" / "claim_examples_v1.json").read_text(encoding="utf-8"))
    return copy.deepcopy(examples[1]["response"]["claims"][0])


def source_span() -> SourceSpan:
    text = 'Rahman recalled, "We left the village in early April because the shelling had begun."'
    return SourceSpan(
        book_id="book:test",
        page_id="book:test:p0001",
        page_number=1,
        page_label="1",
        section={
            "section_id": "section:1",
            "section_title": "Chapter One",
            "part_title": None,
            "chapter_title": "Chapter One",
        },
        extraction_method="native",
        offset_basis="pages.text.normalized",
        span_id="span:example:0002",
        span_type="paragraph",
        parent_span_id=None,
        paragraph_index=1,
        page_char_start=20,
        page_char_end=20 + len(text),
        text=text,
        text_sha256="unused-in-direct-fixture",
    )


def book_and_unit() -> tuple[BookInput, ClaimUnit]:
    span = source_span()
    manifest = {
        "book_id": "book:test",
        "book": {
            "title": "Synthetic Memories",
            "creators": [{"name": "Example Author", "role": "author"}],
            "publication_year": 2020,
            "language": "en",
        },
        "source": {"sha256": "0" * 64},
    }
    book = BookInput(directory=ROOT, manifest=manifest, spans=(span,))
    unit = ClaimUnit(
        unit_id="unit:test:00001",
        book_id="book:test",
        ordinal=1,
        target_spans=(span,),
        context_before=(),
        context_after=(),
    )
    return book, unit


def pipeline(responses: list[dict] | None = None) -> ClaimPipeline:
    return ClaimPipeline(
        provider=ReplayProvider(responses or []),
        config=PipelineConfig(default_condition="rule_based"),
        assets=PipelineAssets.from_repository(ROOT),
        condition="rule_based",
        max_retries=0,
    )


def test_synthetic_examples_match_response_schema() -> None:
    assets = PipelineAssets.from_repository(ROOT)
    validator = Draft202012Validator(assets.response_schema)
    for example in assets.examples:
        assert list(validator.iter_errors(example["response"])) == []


def test_nested_attribution_and_frame_are_materialized_and_grounded() -> None:
    book, unit = book_and_unit()
    result = pipeline()._materialize_candidate(
        candidate=example_candidate(),
        candidate_index=1,
        book=book,
        unit=unit,
        run_id="run:test",
    )

    assert result["rejection"] is None
    claim = result["claim"]
    assert claim["attribution_chain"][-1]["speaker"] == "Rahman"
    assert claim["participants"][0]["grounding"] is not None
    assert claim["verification"]["evidence_grounding"] == "passed"
    assert claim["evidence"][0]["page_char_start"] == 20
    assert len(result["frames"]) == 1
    assert result["frames"][0]["verification"]["cue_grounded"] is True


def test_wrong_evidence_span_is_rejected() -> None:
    book, unit = book_and_unit()
    candidate = example_candidate()
    candidate["evidence"][0]["span_id"] = "span:not-a-target"
    result = pipeline()._materialize_candidate(
        candidate=candidate,
        candidate_index=1,
        book=book,
        unit=unit,
        run_id="run:test",
    )

    assert result["claim"] is None
    assert "evidence_span_not_in_target:span:not-a-target" in result["rejection"]["issues"]


def test_duplicate_topic_labels_are_repaired_without_changing_other_fields() -> None:
    response = {"claims": [{"topic_labels": ["military", "personal_memory", "military"]}]}
    normalized, repairs = ClaimPipeline._normalize_response(response)

    assert normalized["claims"][0]["topic_labels"] == ["military", "personal_memory"]
    assert repairs == ["claims[0].topic_labels:removed_duplicates"]


def _write_test_book(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "extraction").mkdir()
    span = source_span()
    manifest = {
        "book_id": span.book_id,
        "book": {
            "title": "Synthetic Memories",
            "creators": [{"name": "Example Author", "role": "author"}],
            "publication_year": 2020,
            "language": "en",
        },
        "source": {"sha256": "0" * 64},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    record = {
        "book_id": span.book_id,
        "page_id": span.page_id,
        "page_number": span.page_number,
        "page_label": span.page_label,
        "section": {**span.section, "claim_eligible": True},
        "extraction_method": span.extraction_method,
        "offset_basis": span.offset_basis,
        "claim_eligible": True,
        "span_id": span.span_id,
        "span_type": "paragraph",
        "parent_span_id": None,
        "paragraph_index": 1,
        "sentence_index": None,
        "page_char_start": span.page_char_start,
        "page_char_end": span.page_char_end,
        "word_count": len(span.text.split()),
        "char_count": len(span.text),
        "text": span.text,
        "text_sha256": __import__("hashlib").sha256(span.text.encode()).hexdigest(),
    }
    (directory / "extraction" / "spans.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")


def test_completed_run_resumes_without_calling_provider(tmp_path: Path) -> None:
    book_directory = tmp_path / "book"
    output_directory = tmp_path / "run"
    _write_test_book(book_directory)
    response = {"claims": [example_candidate()], "unit_complete": True, "warnings": []}
    first = pipeline([response])
    first.run(book_directories=[book_directory], output_directory=output_directory)
    assert first.provider.calls == 1

    resumed = pipeline([])
    resumed.run(book_directories=[book_directory], output_directory=output_directory, resume=True)
    assert resumed.provider.calls == 0
    assert len((output_directory / "claims.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    assets = PipelineAssets.from_repository(ROOT)
    validation = validate_run(output_directory, assets)
    artifacts = build_review_artifacts(output_directory, sample_size_per_book=1)
    assert validation["valid"] is True
    assert validation["planned_unit_count"] == 1
    assert validation["processed_unit_count"] == 1
    assert validation["successful_unit_count"] == 1
    assert validation["missing_unit_count"] == 0
    assert validation["claim_eligible_span_count"] == 1
    assert validation["covered_span_count"] == 1
    assert all(path.is_file() for path in artifacts.values())


def test_validation_detects_missing_unit_and_changed_evidence_hash(tmp_path: Path) -> None:
    book_directory = tmp_path / "book"
    output_directory = tmp_path / "run"
    _write_test_book(book_directory)
    response = {"claims": [example_candidate()], "unit_complete": True, "warnings": []}
    pipeline([response]).run(book_directories=[book_directory], output_directory=output_directory)

    claim_path = output_directory / "claims.jsonl"
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["evidence"][0]["quote_sha256"] = "0" * 64
    claim_path.write_text(json.dumps(claim) + "\n", encoding="utf-8")
    (output_directory / "units.jsonl").write_text("", encoding="utf-8")

    validation = validate_run(output_directory, PipelineAssets.from_repository(ROOT))

    assert validation["valid"] is False
    assert validation["missing_unit_count"] == 1
    issues = {error["issue"] for error in validation["errors"]}
    assert "planned_unit_missing" in issues
    assert "evidence_quote_hash_mismatch" in issues


def test_review_sample_spans_chapter_and_claim_kind_strata() -> None:
    claims = [
        {
            "claim_id": f"claim:{index}",
            "claim_kind": kind,
            "source_context": {"chapter_title": chapter},
        }
        for index, (chapter, kind) in enumerate(
            [
                ("One", "event"),
                ("One", "event"),
                ("One", "causal"),
                ("Two", "event"),
                ("Two", "interpretive"),
            ]
        )
    ]

    sample = _stratified_sample(claims, 4, random.Random(1971))
    strata = {(claim["source_context"]["chapter_title"], claim["claim_kind"]) for claim in sample}

    assert len(sample) == 4
    assert len(strata) == 4
