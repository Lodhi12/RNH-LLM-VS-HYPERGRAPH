"""Validation and human-readable review artifacts for claim runs."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from .io import build_claim_units, iter_jsonl, load_book_input, read_json, write_json
from .pipeline import PipelineAssets, utc_now


def _load_jsonl_if_present(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path)) if path.is_file() else []


def validate_run(run_directory: str | Path, assets: PipelineAssets) -> dict[str, Any]:
    run_directory = Path(run_directory).resolve()
    run = read_json(run_directory / "run.json")
    claims = _load_jsonl_if_present(run_directory / "claims.jsonl")
    frames = _load_jsonl_if_present(run_directory / "frames.jsonl")
    claim_validator = Draft202012Validator(assets.claim_schema, format_checker=FormatChecker())
    frame_validator = Draft202012Validator(assets.frame_schema, format_checker=FormatChecker())

    source_spans = {}
    expected_units: dict[str, Any] = {}
    source_errors: list[str] = []
    config = run.get("config", {})
    for source in run.get("book_inputs", []):
        try:
            book = load_book_input(source["directory"])
        except Exception as exc:
            source_errors.append(f"{source.get('book_id')}: {type(exc).__name__}: {exc}")
            continue
        source_spans.update({span.span_id: span for span in book.spans})
        try:
            units = build_claim_units(
                book,
                max_target_characters=int(config["max_target_characters"]),
                max_target_spans=int(config["max_target_spans"]),
                context_spans_before=int(config["context_spans_before"]),
                context_spans_after=int(config["context_spans_after"]),
            )
            limit = run.get("limit_units_per_book")
            if limit is not None:
                units = units[: int(limit)]
            expected_units.update({unit.unit_id: unit for unit in units})
        except (KeyError, TypeError, ValueError) as exc:
            source_errors.append(f"{source.get('book_id')}: cannot reconstruct units: {exc}")

    errors: list[dict[str, Any]] = []
    unit_history = _load_jsonl_if_present(run_directory / "units.jsonl")
    latest_units = {unit["unit_id"]: unit for unit in unit_history}
    expected_unit_ids = set(expected_units)
    recorded_unit_ids = set(latest_units)
    unexpected_unit_ids = sorted(recorded_unit_ids - expected_unit_ids)
    missing_unit_ids = sorted(expected_unit_ids - recorded_unit_ids)
    terminal_run = run.get("status") in {
        "complete",
        "complete_with_errors",
        "complete_with_incomplete_units",
    }
    for unit_id in unexpected_unit_ids:
        errors.append({"record": unit_id, "issue": "unexpected_unit"})
    if terminal_run:
        for unit_id in missing_unit_ids:
            errors.append({"record": unit_id, "issue": "planned_unit_missing"})
    for unit_id in sorted(recorded_unit_ids & expected_unit_ids):
        recorded = latest_units[unit_id]
        expected = expected_units[unit_id]
        if recorded.get("book_id") != expected.book_id:
            errors.append({"record": unit_id, "issue": "unit_book_mismatch"})
        if recorded.get("target_span_ids") != list(expected.target_span_ids):
            errors.append({"record": unit_id, "issue": "unit_target_spans_mismatch"})

    claim_ids: set[str] = set()
    frame_ids: set[str] = set()
    for index, claim in enumerate(claims, start=1):
        claim_id = claim.get("claim_id", f"line:{index}")
        if claim_id in claim_ids:
            errors.append({"record": claim_id, "issue": "duplicate_claim_id"})
        claim_ids.add(claim_id)
        for error in claim_validator.iter_errors(claim):
            errors.append(
                {
                    "record": claim_id,
                    "issue": "schema_error",
                    "path": list(error.absolute_path),
                    "message": error.message,
                }
            )
        claim_unit_id = claim.get("extraction", {}).get("unit_id")
        expected_unit = expected_units.get(claim_unit_id)
        if expected_unit is None:
            errors.append({"record": claim_id, "issue": "claim_unit_missing", "unit_id": claim_unit_id})
            expected_target_ids: set[str] = set()
        else:
            expected_target_ids = set(expected_unit.target_span_ids)
            if claim.get("book_id") != expected_unit.book_id:
                errors.append({"record": claim_id, "issue": "claim_unit_book_mismatch"})
        for evidence in claim.get("evidence", []):
            span = source_spans.get(evidence.get("span_id"))
            if span is None:
                errors.append({"record": claim_id, "issue": "source_span_missing", "evidence": evidence.get("evidence_id")})
                continue
            if evidence.get("span_id") not in expected_target_ids:
                errors.append({"record": claim_id, "issue": "evidence_outside_claim_unit", "evidence": evidence.get("evidence_id")})
            if claim.get("book_id") != span.book_id:
                errors.append({"record": claim_id, "issue": "evidence_book_mismatch", "evidence": evidence.get("evidence_id")})
            if evidence.get("page_id") != span.page_id:
                errors.append({"record": claim_id, "issue": "evidence_page_mismatch", "evidence": evidence.get("evidence_id")})
            start = evidence.get("span_char_start")
            end = evidence.get("span_char_end")
            offsets_are_integers = isinstance(start, int) and isinstance(end, int)
            if not offsets_are_integers or span.text[start:end] != evidence.get("quote"):
                errors.append({"record": claim_id, "issue": "source_offset_mismatch", "evidence": evidence.get("evidence_id")})
            elif evidence.get("page_char_start") != span.page_char_start + start or evidence.get("page_char_end") != span.page_char_start + end:
                errors.append({"record": claim_id, "issue": "page_offset_mismatch", "evidence": evidence.get("evidence_id")})
            quote = evidence.get("quote")
            if not isinstance(quote, str) or hashlib.sha256(quote.encode("utf-8")).hexdigest() != evidence.get("quote_sha256"):
                errors.append({"record": claim_id, "issue": "evidence_quote_hash_mismatch", "evidence": evidence.get("evidence_id")})

    for index, frame in enumerate(frames, start=1):
        frame_id = frame.get("frame_id", f"frame-line:{index}")
        if frame_id in frame_ids:
            errors.append({"record": frame_id, "issue": "duplicate_frame_id"})
        frame_ids.add(frame_id)
        for error in frame_validator.iter_errors(frame):
            errors.append(
                {
                    "record": frame_id,
                    "issue": "schema_error",
                    "path": list(error.absolute_path),
                    "message": error.message,
                }
            )
        if frame.get("claim_id") not in claim_ids:
            errors.append({"record": frame_id, "issue": "claim_reference_missing"})

    for claim in claims:
        for frame_id in claim.get("frame_candidate_ids", []):
            if frame_id not in frame_ids:
                errors.append({"record": claim["claim_id"], "issue": "frame_reference_missing", "frame_id": frame_id})

    successful_units = {
        unit_id
        for unit_id, unit in latest_units.items()
        if unit.get("status") in {"complete", "model_incomplete"}
    }
    covered_span_ids = {
        span_id
        for unit_id in successful_units
        for span_id in latest_units[unit_id].get("target_span_ids", [])
    }
    report = {
        "validated_at": utc_now(),
        "run_id": run.get("run_id"),
        "valid": not errors and not source_errors,
        "run_status": run.get("status"),
        "planned_unit_count": len(expected_units),
        "processed_unit_count": len(recorded_unit_ids & expected_unit_ids),
        "successful_unit_count": len(successful_units & expected_unit_ids),
        "missing_unit_count": len(missing_unit_ids),
        "missing_unit_ids": missing_unit_ids[:1000],
        "missing_unit_ids_truncated": len(missing_unit_ids) > 1000,
        "claim_eligible_span_count": len(source_spans),
        "covered_span_count": len(covered_span_ids & set(source_spans)),
        "claim_count": len(claims),
        "frame_count": len(frames),
        "source_span_count": len(source_spans),
        "source_errors": source_errors,
        "error_count": len(errors),
        "errors": errors[:1000],
        "errors_truncated": len(errors) > 1000,
    }
    write_json(run_directory / "validation_report.json", report)
    return report


def build_review_artifacts(run_directory: str | Path, *, sample_size_per_book: int = 50) -> dict[str, Path]:
    run_directory = Path(run_directory).resolve()
    run = read_json(run_directory / "run.json")
    summary = read_json(run_directory / "summary.json")
    validation_path = run_directory / "validation_report.json"
    validation = read_json(validation_path) if validation_path.is_file() else {}
    claims = _load_jsonl_if_present(run_directory / "claims.jsonl")
    frames = _load_jsonl_if_present(run_directory / "frames.jsonl")
    rejected = _load_jsonl_if_present(run_directory / "rejected_candidates.jsonl")
    units = _load_jsonl_if_present(run_directory / "units.jsonl")
    frames_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for frame in frames:
        frames_by_claim[frame["claim_id"]].append(frame)
    books = {item["book_id"]: item for item in run.get("book_inputs", [])}

    pretty_claims = run_directory / "claims.pretty.json"
    pretty_frames = run_directory / "frames.pretty.json"
    pretty_rejected = run_directory / "rejected_candidates.pretty.json"
    write_json(pretty_claims, claims)
    write_json(pretty_frames, frames)
    write_json(pretty_rejected, rejected)

    review_csv = run_directory / "claims_review.csv"
    _write_claim_csv(review_csv, claims, frames_by_claim, books)

    sample_claims: list[dict[str, Any]] = []
    claims_by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        claims_by_book[claim["book_id"]].append(claim)
    randomizer = random.Random(1971)
    for book_id, book_claims in sorted(claims_by_book.items()):
        count = min(sample_size_per_book, len(book_claims))
        sample_claims.extend(_stratified_sample(book_claims, count, randomizer))
    sample_claims.sort(key=lambda claim: (claim["book_id"], claim["source_context"]["pdf_page_number"], claim["claim_id"]))
    sample_csv = run_directory / "human_review_sample.csv"
    _write_claim_csv(sample_csv, sample_claims, frames_by_claim, books, human_columns=True)

    rejected_csv = run_directory / "rejected_candidates_review.csv"
    _write_rejected_csv(rejected_csv, rejected, books)
    unit_csv = run_directory / "unit_audit.csv"
    _write_unit_csv(unit_csv, units, books)

    per_book_directory = run_directory / "by_book"
    per_book_directory.mkdir(parents=True, exist_ok=True)
    per_book_index: list[dict[str, Any]] = []
    for book_id, metadata in books.items():
        short_id = book_id.removeprefix("book:")[:12]
        book_directory = per_book_directory / short_id
        book_directory.mkdir(parents=True, exist_ok=True)
        book_claims = claims_by_book.get(book_id, [])
        book_frames = [frame for frame in frames if frame["book_id"] == book_id]
        claims_path = book_directory / "claims.pretty.json"
        frames_path = book_directory / "frames.pretty.json"
        csv_path = book_directory / "claims_review.csv"
        write_json(claims_path, book_claims)
        write_json(frames_path, book_frames)
        _write_claim_csv(csv_path, book_claims, frames_by_claim, books)
        per_book_index.append(
            {
                "book_id": book_id,
                "title": metadata.get("title"),
                "authors": metadata.get("authors", []),
                "claim_count": len(book_claims),
                "frame_count": len(book_frames),
                "directory": str(book_directory.relative_to(run_directory)),
            }
        )
    per_book_index_path = per_book_directory / "index.json"
    write_json(per_book_index_path, per_book_index)

    report_path = run_directory / "CLAIM_EXTRACTION_REPORT.md"
    report_path.write_text(_render_report(run, summary, validation, claims, frames, books), encoding="utf-8")
    return {
        "claims_pretty_json": pretty_claims,
        "frames_pretty_json": pretty_frames,
        "rejected_candidates_pretty_json": pretty_rejected,
        "all_claims_csv": review_csv,
        "human_review_sample_csv": sample_csv,
        "rejected_candidates_review_csv": rejected_csv,
        "unit_audit_csv": unit_csv,
        "per_book_index": per_book_index_path,
        "markdown_report": report_path,
    }


def _stratified_sample(
    claims: list[dict[str, Any]],
    count: int,
    randomizer: random.Random,
) -> list[dict[str, Any]]:
    """Sample across chapter and claim-kind strata with a fixed random seed."""

    if count <= 0:
        return []
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        context = claim.get("source_context", {})
        key = (context.get("chapter_title") or "", claim.get("claim_kind") or "")
        strata[key].append(claim)
    keys = sorted(strata)
    randomizer.shuffle(keys)
    for key in keys:
        randomizer.shuffle(strata[key])

    selected: list[dict[str, Any]] = []
    while keys and len(selected) < count:
        remaining_keys: list[tuple[str, str]] = []
        for key in keys:
            group = strata[key]
            if group and len(selected) < count:
                selected.append(group.pop())
            if group:
                remaining_keys.append(key)
        keys = remaining_keys
    return selected


def _write_claim_csv(
    path: Path,
    claims: Iterable[dict[str, Any]],
    frames_by_claim: dict[str, list[dict[str, Any]]],
    books: dict[str, dict[str, Any]],
    *,
    human_columns: bool = False,
) -> None:
    columns = [
        "claim_id", "book_id", "book_title", "pdf_page_number", "printed_page_label",
        "part_title", "chapter_title", "claim_text", "claim_kind", "polarity",
        "epistemic_status", "attribution_chain", "predicate", "participants", "times",
        "locations", "quantities", "topic_labels", "frame_candidates", "evidence_quote",
        "evidence_span_id", "span_char_start", "span_char_end", "extraction_method",
        "exact_quote_match", "field_grounding", "verification_issues", "review_flags",
    ]
    if human_columns:
        columns.extend(
            [
                "human_is_claim", "human_is_atomic", "human_source_faithful",
                "human_attribution_correct", "human_semantic_fields_correct",
                "human_frame_correct", "human_decision", "human_note", "reviewer_id",
            ]
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for claim in claims:
            primary = next((item for item in claim["evidence"] if item["support_type"] == "primary"), claim["evidence"][0])
            source = claim["source_context"]
            row = {
                "claim_id": claim["claim_id"],
                "book_id": claim["book_id"],
                "book_title": books.get(claim["book_id"], {}).get("title", ""),
                "pdf_page_number": source["pdf_page_number"],
                "printed_page_label": source["printed_page_label"] or "",
                "part_title": source["part_title"] or "",
                "chapter_title": source["chapter_title"] or "",
                "claim_text": claim["claim_text"],
                "claim_kind": claim["claim_kind"],
                "polarity": claim["polarity"],
                "epistemic_status": claim["epistemic_status"],
                "attribution_chain": json.dumps(claim["attribution_chain"], ensure_ascii=False),
                "predicate": json.dumps(claim["predicate"], ensure_ascii=False),
                "participants": json.dumps(claim["participants"], ensure_ascii=False),
                "times": json.dumps(claim["times"], ensure_ascii=False),
                "locations": json.dumps(claim["locations"], ensure_ascii=False),
                "quantities": json.dumps(claim["quantities"], ensure_ascii=False),
                "topic_labels": "; ".join(claim["topic_labels"]),
                "frame_candidates": json.dumps(frames_by_claim.get(claim["claim_id"], []), ensure_ascii=False),
                "evidence_quote": primary["quote"],
                "evidence_span_id": primary["span_id"],
                "span_char_start": primary["span_char_start"],
                "span_char_end": primary["span_char_end"],
                "extraction_method": source["extraction_method"] or "",
                "exact_quote_match": claim["verification"]["exact_quote_match"],
                "field_grounding": claim["verification"]["field_grounding"],
                "verification_issues": "; ".join(claim["verification"]["issues"]),
                "review_flags": "; ".join(claim["review"]["flags"]),
            }
            if human_columns:
                row.update({column: "" for column in columns if column.startswith("human_") or column == "reviewer_id"})
            writer.writerow(row)


def _write_rejected_csv(
    path: Path,
    rejected: Iterable[dict[str, Any]],
    books: dict[str, dict[str, Any]],
) -> None:
    columns = [
        "candidate_id", "book_id", "book_title", "unit_id", "claim_text",
        "claim_kind", "polarity", "epistemic_status", "evidence_span_ids",
        "submitted_evidence_quotes", "issues", "rejected_at", "human_decision",
        "human_note", "reviewer_id",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in rejected:
            candidate = record.get("candidate") or {}
            evidence = candidate.get("evidence") or []
            writer.writerow(
                {
                    "candidate_id": record.get("candidate_id", ""),
                    "book_id": record.get("book_id", ""),
                    "book_title": books.get(record.get("book_id", ""), {}).get("title", ""),
                    "unit_id": record.get("unit_id", ""),
                    "claim_text": candidate.get("claim_text", ""),
                    "claim_kind": candidate.get("claim_kind", ""),
                    "polarity": candidate.get("polarity", ""),
                    "epistemic_status": candidate.get("epistemic_status", ""),
                    "evidence_span_ids": "; ".join(item.get("span_id", "") for item in evidence),
                    "submitted_evidence_quotes": json.dumps(
                        [item.get("quote", "") for item in evidence], ensure_ascii=False
                    ),
                    "issues": "; ".join(record.get("issues", [])),
                    "rejected_at": record.get("rejected_at", ""),
                    "human_decision": "",
                    "human_note": "",
                    "reviewer_id": "",
                }
            )


def _write_unit_csv(
    path: Path,
    units: Iterable[dict[str, Any]],
    books: dict[str, dict[str, Any]],
) -> None:
    columns = [
        "unit_id", "book_id", "book_title", "ordinal", "status",
        "first_pdf_page_number", "last_pdf_page_number", "part_title",
        "chapter_title", "target_span_ids", "target_character_count", "attempts",
        "claim_count", "frame_count", "rejected_count", "model_unit_complete",
        "warnings", "error", "duration_seconds", "completed_at",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for unit in units:
            writer.writerow(
                {
                    "unit_id": unit.get("unit_id", ""),
                    "book_id": unit.get("book_id", ""),
                    "book_title": books.get(unit.get("book_id", ""), {}).get("title", ""),
                    "ordinal": unit.get("ordinal", ""),
                    "status": unit.get("status", ""),
                    "first_pdf_page_number": unit.get("first_pdf_page_number", ""),
                    "last_pdf_page_number": unit.get("last_pdf_page_number", ""),
                    "part_title": unit.get("part_title") or "",
                    "chapter_title": unit.get("chapter_title") or "",
                    "target_span_ids": "; ".join(unit.get("target_span_ids", [])),
                    "target_character_count": unit.get("target_character_count", ""),
                    "attempts": unit.get("attempts", ""),
                    "claim_count": unit.get("claim_count", ""),
                    "frame_count": unit.get("frame_count", ""),
                    "rejected_count": unit.get("rejected_count", ""),
                    "model_unit_complete": unit.get("model_unit_complete", ""),
                    "warnings": "; ".join(unit.get("warnings", [])),
                    "error": unit.get("error") or "",
                    "duration_seconds": unit.get("duration_seconds", ""),
                    "completed_at": unit.get("completed_at", ""),
                }
            )


def _render_report(
    run: dict[str, Any],
    summary: dict[str, Any],
    validation: dict[str, Any],
    claims: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    books: dict[str, dict[str, Any]],
) -> str:
    unit_limit = run.get("limit_units_per_book")
    is_pilot = unit_limit is not None
    report_title = (
        "# Pilot Claim Candidate Extraction Report"
        if is_pilot
        else "# Full-Corpus Claim Candidate Extraction Report"
    )
    run_scope = (
        f"pilot limited to the first {unit_limit} planned claim-input units per book"
        if is_pilot
        else "full corpus (no per-book unit limit)"
    )
    lines = [
        report_title,
        "",
        "> These are model-generated, source-grounded claim candidates. Exact quotation and offset checks do not prove semantic fidelity or historical truth. Human review remains pending.",
        "",
        "## Run",
        "",
        f"- Run ID: `{run.get('run_id')}`",
        f"- Backend/model: `{run.get('backend')}` / `{run.get('model')}`",
        f"- Condition: `{run.get('condition')}`",
        f"- Prompt: `{run.get('prompt_version')}`",
        f"- Run scope: {run_scope}",
        f"- Processed units: {summary.get('processed_units', 0)}",
        f"- Planned units: {validation.get('planned_unit_count', run.get('planned_unit_count', 0))}",
        f"- Successfully covered units: {validation.get('successful_unit_count', summary.get('complete_units', 0))}",
        f"- Covered eligible source spans: {validation.get('covered_span_count', 'not calculated')} / {validation.get('claim_eligible_span_count', 'not calculated')}",
        f"- Grounded claim candidates: {len(claims)}",
        f"- Provisional frame candidates: {len(frames)}",
        f"- Rejected ungrounded/duplicate candidates: {summary.get('rejected_candidates', 0)}",
        f"- Failed units: {summary.get('failed_units', 0)}",
        f"- Units marked incomplete by the model: {summary.get('model_incomplete_units', 0)}",
        f"- Structural/provenance validation: {'passed' if validation.get('valid') else 'not passed'} ({validation.get('error_count', 'not calculated')} errors)",
        "- Historical truth assessment: not performed",
        "",
        "## Books",
        "",
    ]
    claims_by_book = Counter(claim["book_id"] for claim in claims)
    for book_id, metadata in books.items():
        lines.append(f"- **{metadata.get('title', book_id)}**: {claims_by_book[book_id]} grounded candidates (`{book_id}`)")
    lines.extend(["", "## Claim Kinds", ""])
    for label, count in sorted(Counter(claim["claim_kind"] for claim in claims).items()):
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Provisional Frame Functions", ""])
    if frames:
        for label, count in sorted(Counter(frame["function"] for frame in frames).items()):
            lines.append(f"- `{label}`: {count}")
    else:
        lines.append("- No frame candidates were proposed.")
    lines.extend(
        [
            "",
            "## What Was Verified Automatically",
            "",
            "- Every retained evidence quote resolves to its declared target span.",
            "- Every retained quote has deterministic span-relative and page-relative character offsets.",
            "- Every claim's evidence belongs to the model unit and book recorded on that claim.",
            "- Evidence hashes are recomputed and checked against the exact retained source quotation.",
            "- Final unit coverage is checked against units reconstructed from the frozen run configuration.",
            "- Claim and frame records conform to their JSON Schemas.",
            "- Surface forms for predicates, participants, times, locations, quantities, attribution cues, and frame cues are checked against supplied source text.",
            "",
            "## What Still Requires Human Review",
            "",
            "- Whether each record is genuinely a claim and is sufficiently atomic.",
            "- Whether the normalized claim preserves the quotation's meaning, attribution, negation, modality, and uncertainty.",
            "- Whether participant roles and entity types are semantically correct.",
            "- Whether any claim was missed; completeness requires an annotated gold sample.",
            "- Whether provisional frame labels satisfy the supervisor-approved codebook.",
            "- Whether a book's statements correspond to historical reality; this dataset does not assess that question.",
            "- Rejected candidates are retained for adjudication and are never silently rewritten into accepted claims.",
            "",
            "## Files",
            "",
            "- `claims.jsonl`: canonical machine-readable claim records",
            "- `frames.jsonl`: separate provisional frame records",
            "- `claims.pretty.json`: human-readable JSON array",
            "- `claims_review.csv`: all claims in spreadsheet form",
            "- `human_review_sample.csv`: stratified review sample with blank annotation columns",
            "- `by_book/index.json`: index of readable JSON and CSV exports for each book",
            "- `raw_responses.jsonl`: unmodified model responses and provider metadata",
            "- `rejected_candidates.jsonl`: candidates that failed grounding or were duplicates",
            "- `rejected_candidates.pretty.json`: readable rejected-candidate records",
            "- `rejected_candidates_review.csv`: rejected candidates prepared for adjudication or recovery",
            "- `units.jsonl`: one audit record per model input unit",
            "- `unit_audit.csv`: spreadsheet view of unit coverage, counts, errors, and timings",
            "- `validation_report.json`: schema and source-offset integrity checks",
            "",
        ]
    )
    return "\n".join(lines)
