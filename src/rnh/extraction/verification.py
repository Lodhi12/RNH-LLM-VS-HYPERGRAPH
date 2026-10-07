from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .io_utils import read_json, read_jsonl, sha256_file, sha256_text, stable_id, utc_now, write_json, write_jsonl
from .text import word_count


CLAIM_DEFINITION = """A claim is an atomic proposition that an identifiable source presents
as asserted, reported, remembered, interpreted, disputed, denied, or uncertain."""


def normalized_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


FIDELITY_PROMPT_VERSION = "historical-claim-source-fidelity-v2.0"

FIDELITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_claim": {"type": "boolean"},
        "is_atomic": {"type": "boolean"},
        "faithfulness": {
            "type": "string",
            "enum": ["faithful", "partially_faithful", "unsupported", "uncertain"],
        },
        "attribution_correct": {"type": "boolean"},
        "brief_reason": {"type": "string"},
    },
    "required": ["is_claim", "is_atomic", "faithfulness", "attribution_correct", "brief_reason"],
    "additionalProperties": False,
}


def verify_extraction(book_dir: Path) -> dict[str, Any]:
    book_dir = book_dir.expanduser().resolve()
    manifest = read_json(book_dir / "manifest.json")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def artifact_path(name: str) -> Path | None:
        value = (manifest.get("artifacts") or {}).get(name)
        if not isinstance(value, str) or not value:
            errors.append({"type": "missing_artifact_reference", "artifact": name})
            return None
        path = (book_dir / value).resolve()
        if not path.is_relative_to(book_dir):
            errors.append({"type": "artifact_outside_book_directory", "artifact": name, "path": value})
            return None
        if not path.is_file():
            errors.append({"type": "artifact_file_missing", "artifact": name, "path": value})
            return None
        return path

    pages_path = artifact_path("pages")
    spans_path = artifact_path("spans")
    blocks_path = artifact_path("blocks")
    structure_path = artifact_path("structure")
    images_path = artifact_path("images")
    pages = list(read_jsonl(pages_path)) if pages_path else []
    spans = list(read_jsonl(spans_path)) if spans_path else []
    blocks = list(read_jsonl(blocks_path)) if blocks_path else []
    images = list(read_jsonl(images_path)) if images_path else []
    structure = read_json(structure_path) if structure_path else {}
    expected_book_id = manifest.get("book_id")
    page_by_id: dict[str, dict[str, Any]] = {}
    seen_page_numbers: set[int] = set()
    pages_by_method: Counter[str] = Counter()

    for page in pages:
        page_id = page.get("page_id")
        page_number = page.get("page_number")
        if page_id in page_by_id:
            errors.append({"type": "duplicate_page_id", "page_id": page_id})
        else:
            page_by_id[str(page_id)] = page
        if page_number in seen_page_numbers:
            errors.append({"type": "duplicate_page_number", "page_number": page_number})
        elif isinstance(page_number, int):
            seen_page_numbers.add(page_number)
        if page.get("book_id") != expected_book_id:
            errors.append({"type": "page_book_id_mismatch", "page_id": page_id})
        expected_page_id = f"{expected_book_id}:p{int(page_number):04d}" if isinstance(page_number, int) else None
        if page_id != expected_page_id:
            errors.append({"type": "invalid_page_id", "page_id": page_id, "expected": expected_page_id})
        text = str((page.get("text") or {}).get("normalized") or "")
        if (page.get("text") or {}).get("sha256") != sha256_text(text):
            errors.append({"type": "page_text_hash_mismatch", "page_id": page_id})
        counts = page.get("counts") or {}
        if counts.get("characters") != len(text) or counts.get("words") != word_count(text):
            errors.append({"type": "page_text_count_mismatch", "page_id": page_id})
        pages_by_method[str((page.get("extraction") or {}).get("method") or "unknown")] += 1

    if len(pages) != int(manifest["book"]["page_count"]):
        errors.append(
            {
                "type": "page_count_mismatch",
                "manifest": manifest["book"]["page_count"],
                "actual": len(pages),
            }
        )
    expected_page_numbers = set(range(1, int(manifest["book"]["page_count"]) + 1))
    if seen_page_numbers != expected_page_numbers:
        errors.append(
            {
                "type": "page_number_sequence_mismatch",
                "missing": sorted(expected_page_numbers - seen_page_numbers)[:100],
                "unexpected": sorted(seen_page_numbers - expected_page_numbers)[:100],
            }
        )

    span_by_id: dict[str, dict[str, Any]] = {}
    for span in spans:
        span_id = span.get("span_id")
        if span_id in span_by_id:
            errors.append({"type": "duplicate_span_id", "span_id": span_id})
        else:
            span_by_id[str(span_id)] = span
        page = page_by_id.get(span.get("page_id"))
        if not page:
            errors.append({"type": "missing_page", "span_id": span_id})
            continue
        if span.get("book_id") != expected_book_id:
            errors.append({"type": "span_book_id_mismatch", "span_id": span_id})
        for field in ("page_number", "page_label", "section"):
            expected = page.get(field)
            actual = span.get(field)
            if actual != expected:
                errors.append({"type": f"span_{field}_mismatch", "span_id": span_id})
        if span.get("extraction_method") != (page.get("extraction") or {}).get("method"):
            errors.append({"type": "span_extraction_method_mismatch", "span_id": span_id})
        text = page["text"]["normalized"]
        start, end = span.get("page_char_start"), span.get("page_char_end")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
            errors.append({"type": "invalid_span_offsets", "span_id": span_id})
        elif text[start:end] != span.get("text"):
            errors.append({"type": "span_text_mismatch", "span_id": span_id})
        span_text = str(span.get("text") or "")
        if span.get("text_sha256") != sha256_text(span_text):
            errors.append({"type": "span_text_hash_mismatch", "span_id": span_id})
        if span.get("char_count") != len(span_text) or span.get("word_count") != word_count(span_text):
            errors.append({"type": "span_text_count_mismatch", "span_id": span_id})

    for span in spans:
        span_id = span.get("span_id")
        parent_id = span.get("parent_span_id")
        if span.get("span_type") == "paragraph" and parent_id is not None:
            errors.append({"type": "paragraph_has_parent", "span_id": span_id})
        if span.get("span_type") == "sentence":
            parent = span_by_id.get(parent_id)
            if not parent or parent.get("span_type") != "paragraph":
                errors.append({"type": "sentence_parent_missing", "span_id": span_id, "parent_span_id": parent_id})
            elif (
                parent.get("page_id") != span.get("page_id")
                or parent.get("page_char_start", 0) > span.get("page_char_start", -1)
                or parent.get("page_char_end", 0) < span.get("page_char_end", -1)
            ):
                errors.append({"type": "sentence_parent_range_mismatch", "span_id": span_id})

    seen_block_ids: set[str] = set()
    for block in blocks:
        block_id = str(block.get("block_id"))
        if block_id in seen_block_ids:
            errors.append({"type": "duplicate_block_id", "block_id": block_id})
        seen_block_ids.add(block_id)
        if block.get("book_id") != expected_book_id:
            errors.append({"type": "block_book_id_mismatch", "block_id": block_id})
        if block.get("page_id") not in page_by_id:
            errors.append({"type": "block_page_missing", "block_id": block_id})
        if block.get("text_sha256") != sha256_text(str(block.get("text") or "")):
            errors.append({"type": "block_text_hash_mismatch", "block_id": block_id})

    image_files: set[str] = set()
    for image in images:
        if image.get("book_id") != expected_book_id:
            errors.append({"type": "image_book_id_mismatch", "page_number": image.get("page_number")})
        if image.get("page_id") not in page_by_id:
            errors.append({"type": "image_page_missing", "page_number": image.get("page_number")})
        if image.get("status") != "extracted":
            warnings.append({"type": "image_extraction_failed", "page_number": image.get("page_number")})
            continue
        relative_path = image.get("file_path")
        if not isinstance(relative_path, str):
            errors.append({"type": "image_file_path_missing", "image_id": image.get("image_id")})
            continue
        image_path = (book_dir / relative_path).resolve()
        if not image_path.is_relative_to(book_dir) or not image_path.is_file():
            errors.append({"type": "image_file_missing", "image_id": image.get("image_id"), "path": relative_path})
            continue
        image_files.add(relative_path)
        if image_path.stat().st_size != image.get("bytes"):
            errors.append({"type": "image_size_mismatch", "image_id": image.get("image_id")})
        if sha256_file(image_path) != image.get("sha256"):
            errors.append({"type": "image_hash_mismatch", "image_id": image.get("image_id")})

    if structure.get("book_id") != expected_book_id:
        errors.append({"type": "structure_book_id_mismatch"})
    for section in structure.get("sections") or []:
        start, end = section.get("page_start"), section.get("page_end")
        if not isinstance(start, int) or not isinstance(end, int) or not (1 <= start <= end <= len(pages)):
            errors.append({"type": "invalid_section_page_range", "section_id": section.get("section_id")})

    source_pdf_status = "unavailable"
    run_local_path = book_dir / "run_local.json"
    if run_local_path.is_file():
        local_source = Path(str(read_json(run_local_path).get("source_local_path") or "")).expanduser()
        if local_source.is_file():
            source_pdf_status = "matched"
            if local_source.stat().st_size != manifest.get("source", {}).get("size_bytes"):
                source_pdf_status = "mismatch"
                errors.append({"type": "source_pdf_size_mismatch"})
            if sha256_file(local_source) != manifest.get("source", {}).get("sha256"):
                source_pdf_status = "mismatch"
                errors.append({"type": "source_pdf_hash_mismatch"})
        else:
            warnings.append({"type": "local_source_pdf_unavailable"})

    report = {
        "schema": "historical-book-extraction-verification-v2",
        "book_id": manifest["book_id"],
        "verified_at": utc_now(),
        "verification_scope": "structural_integrity_and_source_traceability",
        "historical_truth_assessed": False,
        "source_pdf_status": source_pdf_status,
        "counts": {
            "pages": len(pages),
            "spans": len(spans),
            "paragraphs": sum(span.get("span_type") == "paragraph" for span in spans),
            "sentences": sum(span.get("span_type") == "sentence" for span in spans),
            "blocks": len(blocks),
            "image_occurrences": sum(image.get("status") == "extracted" for image in images),
            "unique_image_files": len(image_files),
            "pages_by_method": dict(sorted(pages_by_method.items())),
            "empty_pages": sum(not str((page.get("text") or {}).get("normalized") or "") for page in pages),
            "warnings": len(warnings),
            "errors": len(errors),
        },
        "status": "pass" if not errors else "fail",
        "warning_samples": warnings[:100],
        "error_samples": errors[:100],
    }
    write_json(book_dir / "reports" / "extraction_verification.json", report)
    return report


def fidelity_prompt(claim: dict[str, Any], span: dict[str, Any]) -> list[dict[str, str]]:
    system = f"""Evaluate whether a candidate claim faithfully represents its supplied book passage.

Claim definition:
{CLAIM_DEFINITION}

Evaluate only source fidelity. Do not judge external historical truth.
Preserve negation, uncertainty, reported speech, disputes, and speaker attribution.
The brief reason must be concise and cite no information outside the supplied passage."""
    user = (
        f"SOURCE PASSAGE:\n{span.get('text') or ''}\n\n"
        f"CANDIDATE CLAIM:\n{claim.get('claim_text') or ''}\n\n"
        f"ATTRIBUTION:\n{json.dumps(claim.get('attribution') or {}, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def openai_fidelity(
    claim: dict[str, Any],
    span: dict[str, Any],
    model: str,
    client: Any | None = None,
) -> dict[str, Any]:
    if client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI verification requires the 'openai' package") from exc
        client = OpenAI(max_retries=3, timeout=120.0)
    response = client.responses.create(
        model=model,
        input=fidelity_prompt(claim, span),
        store=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "historical_claim_source_fidelity",
                "strict": True,
                "schema": FIDELITY_SCHEMA,
            }
        },
    )
    return json.loads(response.output_text)


def ollama_fidelity(
    claim: dict[str, Any],
    span: dict[str, Any],
    model: str,
    url: str,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(
            {
                "model": model,
                "stream": False,
                "format": FIDELITY_SCHEMA,
                "messages": fidelity_prompt(claim, span),
                "options": {"temperature": 0},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Ollama verification failed: {exc}") from exc
    return json.loads((payload.get("message") or {}).get("content") or "{}")


def verify_claim_record(
    claim: dict[str, Any],
    spans: dict[str, dict[str, Any]],
    pages: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    if claim.get("schema") != "historical-book-claim-v2":
        issues.append("wrong_schema")
    source = claim.get("source") or {}
    span = spans.get(source.get("span_id"))
    if not span:
        issues.append("source_span_not_found")
    if claim.get("book_id") != (span or {}).get("book_id"):
        issues.append("book_id_mismatch")
    page = pages.get(source.get("page_id"))
    if not page:
        issues.append("source_page_not_found")
    if span:
        for field in ("span_type", "parent_span_id", "page_id", "page_number", "page_label", "extraction_method"):
            if source.get(field) != span.get(field):
                issues.append(f"source_{field}_mismatch")
        section = span.get("section") or {}
        for field in ("section_id", "part_title", "chapter_title", "section_title"):
            if source.get(field) != section.get(field):
                issues.append(f"source_{field}_mismatch")
    if page and span and page.get("page_id") != span.get("page_id"):
        issues.append("span_page_link_mismatch")
    evidence_items = claim.get("evidence") or []
    if not evidence_items:
        issues.append("missing_evidence")
    for evidence in evidence_items:
        quote = str(evidence.get("quote") or "")
        if not quote:
            issues.append("empty_evidence_quote")
            continue
        if span:
            if evidence.get("span_id") != span.get("span_id"):
                issues.append("evidence_span_id_mismatch")
            if evidence.get("quote_sha256") != sha256_text(quote):
                issues.append("evidence_quote_hash_mismatch")
            if evidence.get("offset_basis") != "pages.text.normalized":
                issues.append("evidence_offset_basis_mismatch")
            start, end = evidence.get("span_char_start"), evidence.get("span_char_end")
            if not isinstance(start, int) or not isinstance(end, int):
                issues.append("missing_span_offsets")
            elif not (0 <= start < end <= len(span["text"])) or span["text"][start:end] != quote:
                issues.append("span_offset_mismatch")
        if page:
            page_text = page["text"]["normalized"]
            start, end = evidence.get("page_char_start"), evidence.get("page_char_end")
            if not isinstance(start, int) or not isinstance(end, int):
                issues.append("missing_page_offsets")
            elif not (0 <= start < end <= len(page_text)) or page_text[start:end] != quote:
                issues.append("page_offset_mismatch")
        submitted_quote = evidence.get("submitted_quote")
        alignment_method = evidence.get("alignment_method")
        if submitted_quote is not None or alignment_method is not None:
            if alignment_method not in {"exact", "whitespace_normalized"}:
                issues.append("invalid_evidence_alignment_method")
            elif alignment_method == "exact" and submitted_quote != quote:
                issues.append("submitted_quote_alignment_mismatch")
            elif alignment_method == "whitespace_normalized" and normalized_whitespace(
                str(submitted_quote or "")
            ) != normalized_whitespace(quote):
                issues.append("submitted_quote_alignment_mismatch")
        if span:
            span_start, span_end = evidence.get("span_char_start"), evidence.get("span_char_end")
            page_start, page_end = evidence.get("page_char_start"), evidence.get("page_char_end")
            if all(isinstance(value, int) for value in (span_start, span_end, page_start, page_end)):
                if (
                    int(span["page_char_start"]) + span_start != page_start
                    or int(span["page_char_start"]) + span_end != page_end
                ):
                    issues.append("span_to_page_offset_mismatch")

    if span and evidence_items:
        expected_claim_id = stable_id(
            "claim",
            claim.get("book_id"),
            span.get("span_id"),
            claim.get("claim_text"),
            evidence_items[0].get("quote"),
        )
        if claim.get("claim_id") != expected_claim_id:
            issues.append("claim_id_mismatch")
    for context_span_id in (claim.get("generation") or {}).get("context_span_ids") or []:
        context_span = spans.get(context_span_id)
        if not context_span:
            issues.append("context_span_not_found")
        elif context_span.get("book_id") != claim.get("book_id"):
            issues.append("context_span_book_id_mismatch")

    primary_quote = str(evidence_items[0].get("quote") or "") if evidence_items else ""
    proposition = claim.get("proposition") or {}
    for group_name in ("actors", "affected_entities", "other_entities"):
        for index, mention_record in enumerate(proposition.get(group_name) or []):
            mention = str(mention_record.get("mention") or "")
            start = mention_record.get("quote_char_start")
            end = mention_record.get("quote_char_end")
            issue_prefix = f"proposition_{group_name}_{index}"
            if not isinstance(start, int) or not isinstance(end, int):
                issues.append(f"{issue_prefix}_missing_offsets")
            elif not (0 <= start < end <= len(primary_quote)) or primary_quote[start:end] != mention:
                issues.append(f"{issue_prefix}_offset_mismatch")
            expected_mention_id = stable_id(
                "mention",
                claim.get("claim_id"),
                mention,
                mention_record.get("semantic_role"),
            )
            if mention_record.get("mention_id") != expected_mention_id:
                issues.append(f"{issue_prefix}_id_mismatch")
            if mention_record.get("book_id") != claim.get("book_id"):
                issues.append(f"{issue_prefix}_book_id_mismatch")

    action = proposition.get("action")
    if action is not None and (not isinstance(action, str) or not action or action not in primary_quote):
        issues.append("proposition_action_not_grounded")
    for field in ("dates", "locations", "quantities"):
        for value in proposition.get(field) or []:
            if not isinstance(value, str) or not value or value not in primary_quote:
                issues.append(f"proposition_{field}_not_grounded")

    output = dict(claim)
    exact_quote_match = bool(evidence_items) and not any(
        issue in {"source_span_not_found", "empty_evidence_quote", "span_offset_mismatch"}
        for issue in issues
    )
    exact_offset_match = bool(evidence_items) and not any("offset" in issue for issue in issues)
    verification = dict(output.get("verification") or {})
    verification.update(
        {
            "grounding_status": "grounded" if not issues else "failed",
            "exact_quote_match": exact_quote_match,
            "exact_offset_match": exact_offset_match,
            "historical_truth_status": "not_assessed",
            "issues": sorted(set(issues)),
            "verified_at": utc_now(),
        }
    )
    output["verification"] = verification
    return output, issues


def verify_claim_run(
    book_dir: Path,
    claim_run_dir: Path,
    semantic_backend: str = "none",
    model: str | None = None,
    allow_external_api: bool = False,
    max_claims: int | None = None,
    ollama_url: str = "http://localhost:11434/api/chat",
) -> Path:
    book_dir = book_dir.expanduser().resolve()
    claim_run_dir = claim_run_dir.expanduser().resolve()
    manifest = read_json(book_dir / "manifest.json")
    spans = {row["span_id"]: row for row in read_jsonl(book_dir / manifest["artifacts"]["spans"])}
    pages = {row["page_id"]: row for row in read_jsonl(book_dir / manifest["artifacts"]["pages"])}
    claims_path = claim_run_dir / "claims.jsonl"
    output_path = claim_run_dir / "claims_verified.jsonl"
    report_path = claim_run_dir / "verification_report.json"

    if semantic_backend == "openai" and not allow_external_api:
        raise ValueError("OpenAI sends claim evidence to an external API. Add --allow-external-api after approval.")
    if semantic_backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    if semantic_backend != "none" and not model:
        raise ValueError("--judge-model is required when using a semantic judge")
    semantic_judge: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    if semantic_backend == "openai":
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI verification requires the 'openai' package") from exc
        client = OpenAI(max_retries=3, timeout=120.0)
        semantic_judge = lambda claim, span: openai_fidelity(claim, span, str(model), client)
    elif semantic_backend == "ollama":
        semantic_judge = lambda claim, span: ollama_fidelity(claim, span, str(model), ollama_url)

    output: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for index, claim in enumerate(read_jsonl(claims_path), start=1):
        if max_claims is not None and index > max_claims:
            break
        verified, issues = verify_claim_record(claim, spans, pages)
        counts["total"] += 1
        counts["grounded" if not issues else "grounding_failed"] += 1
        if semantic_judge and not issues:
            try:
                span = spans[verified["source"]["span_id"]]
                judgement = semantic_judge(verified, span)
                verified["verification"]["source_fidelity_status"] = judgement["faithfulness"]
                verified["verification"]["source_fidelity_method"] = {
                    "backend": semantic_backend,
                    "model": model,
                    "prompt_version": FIDELITY_PROMPT_VERSION,
                    "is_claim": judgement["is_claim"],
                    "is_atomic": judgement["is_atomic"],
                    "attribution_correct": judgement["attribution_correct"],
                    "brief_reason": judgement["brief_reason"],
                }
                counts[f"fidelity_{judgement['faithfulness']}"] += 1
            except Exception as exc:
                verified["verification"]["source_fidelity_status"] = "judge_error"
                verified["verification"]["source_fidelity_method"] = {
                    "backend": semantic_backend,
                    "model": model,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                counts["semantic_judge_errors"] += 1
        output.append(verified)

    write_jsonl(output_path, output)
    report = {
        "schema": "historical-book-claim-verification-report-v2",
        "book_id": manifest["book_id"],
        "claim_run": str(claim_run_dir.relative_to(book_dir)),
        "verified_at": utc_now(),
        "verification_scope": {
            "deterministic": "exact source IDs, quotations, and character offsets",
            "semantic": "source fidelity only" if semantic_backend != "none" else "not assessed",
            "historical_truth": "not assessed",
        },
        "semantic_judge": {"backend": semantic_backend, "model": model},
        "counts": dict(counts),
        "status": (
            "pass"
            if counts["grounding_failed"] == 0 and counts["semantic_judge_errors"] == 0
            else "fail"
        ),
    }
    write_json(report_path, report)
    print(f"Claim verification complete: {output_path}")
    return output_path
