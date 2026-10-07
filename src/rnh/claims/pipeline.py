"""Resumable LLM claim extraction and deterministic source grounding."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from .grounding import align_text, ground_surface, normalize_whitespace
from .io import (
    BookInput,
    ClaimUnit,
    SourceSpan,
    append_jsonl,
    build_claim_units,
    iter_jsonl,
    load_book_input,
    read_json,
    write_json,
)
from .prompting import build_system_prompt, build_user_prompt, load_prompt_assets, prompt_sha256
from .providers import ClaimProvider


@dataclass(frozen=True)
class PipelineConfig:
    schema_version: str = "1.0.0"
    prompt_version: str = "claim-extraction-1.0.1"
    annotation_guideline_version: str = "claim-annotation-1.0.0-draft"
    default_condition: str = "llm_few_shot"
    target_span_type: str = "paragraph"
    max_target_characters: int = 3000
    max_target_spans: int = 5
    context_spans_before: int = 0
    context_spans_after: int = 0
    max_claims_per_unit: int = 20
    passes: int = 1
    temperature: float = 0.0
    historical_truth_policy: str = "not_assessed"
    frame_policy: str = "provisional_candidates_separate_from_claims"

    @classmethod
    def from_file(cls, path: str | Path) -> "PipelineConfig":
        raw = read_json(Path(path))
        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"Unknown pipeline config keys: {', '.join(unknown)}")
        return cls(**raw)


@dataclass(frozen=True)
class PipelineAssets:
    root: Path
    response_schema: dict[str, Any]
    claim_schema: dict[str, Any]
    frame_schema: dict[str, Any]
    base_prompt: str
    examples: list[dict[str, Any]]

    @classmethod
    def from_repository(cls, root: str | Path) -> "PipelineAssets":
        root = Path(root).resolve()
        base_prompt, examples = load_prompt_assets(
            root / "prompts" / "claim_extraction_v1.md",
            root / "prompts" / "claim_examples_v1.json",
        )
        return cls(
            root=root,
            response_schema=read_json(root / "schemas" / "claim_candidate_response.schema.json"),
            claim_schema=read_json(root / "schemas" / "claim.schema.json"),
            frame_schema=read_json(root / "schemas" / "frame_candidate.schema.json"),
            base_prompt=base_prompt,
            examples=examples,
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, value: Any, length: int = 24) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


class ClaimPipeline:
    def __init__(
        self,
        *,
        provider: ClaimProvider,
        config: PipelineConfig,
        assets: PipelineAssets,
        condition: str | None = None,
        max_retries: int = 2,
        workers: int = 1,
    ) -> None:
        self.provider = provider
        self.config = config
        self.assets = assets
        self.condition = condition or config.default_condition
        self.max_retries = max_retries
        if workers < 1:
            raise ValueError("workers must be at least 1")
        self.workers = workers
        self._duplicate_lock = threading.Lock()
        self.response_schema = deepcopy(assets.response_schema)
        self.response_schema["properties"]["claims"]["maxItems"] = config.max_claims_per_unit
        self.response_validator = Draft202012Validator(self.response_schema, format_checker=FormatChecker())
        self.claim_validator = Draft202012Validator(assets.claim_schema, format_checker=FormatChecker())
        self.frame_validator = Draft202012Validator(assets.frame_schema, format_checker=FormatChecker())
        self.system_prompt = build_system_prompt(
            assets.base_prompt,
            assets.examples,
            condition=self.condition,
            max_claims=config.max_claims_per_unit,
        )

    def run(
        self,
        *,
        book_directories: Iterable[str | Path],
        output_directory: str | Path,
        resume: bool = False,
        limit_units_per_book: int | None = None,
    ) -> dict[str, Any]:
        books = [load_book_input(directory) for directory in book_directories]
        if len({book.book_id for book in books}) != len(books):
            raise ValueError("The same book_id was supplied more than once")
        output = Path(output_directory).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        run_path = output / "run.json"
        existing_files = [path for path in output.iterdir() if path.name != ".gitkeep"]
        if existing_files and not (resume and run_path.is_file()):
            raise FileExistsError(f"Output directory is not empty; use --resume or choose a new directory: {output}")

        units_by_book: list[tuple[BookInput, list[ClaimUnit]]] = []
        for book in books:
            units = build_claim_units(
                book,
                max_target_characters=self.config.max_target_characters,
                max_target_spans=self.config.max_target_spans,
                context_spans_before=self.config.context_spans_before,
                context_spans_after=self.config.context_spans_after,
            )
            if limit_units_per_book is not None:
                units = units[:limit_units_per_book]
            units_by_book.append((book, units))

        if resume and run_path.is_file():
            run_record = read_json(run_path)
            self._check_resume_compatibility(run_record, books)
            run_id = run_record["run_id"]
            run_record["resumed_at"] = utc_now()
            run_record["status"] = "running"
        else:
            run_id = stable_id(
                "run",
                {
                    "created_at": utc_now(),
                    "book_ids": [book.book_id for book in books],
                    "backend": self.provider.backend,
                    "model": self.provider.model,
                    "condition": self.condition,
                },
            )
            run_record = {
                "schema_version": self.config.schema_version,
                "run_id": run_id,
                "status": "running",
                "created_at": utc_now(),
                "backend": self.provider.backend,
                "model": self.provider.model,
                "provider_provenance": self.provider.describe(),
                "condition": self.condition,
                "workers": self.workers,
                "prompt_version": self.config.prompt_version,
                "prompt_sha256": hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest(),
                "response_schema_sha256": hashlib.sha256(
                    json.dumps(self.response_schema, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "claim_schema_sha256": hashlib.sha256(
                    json.dumps(self.assets.claim_schema, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "annotation_guideline_version": self.config.annotation_guideline_version,
                "book_inputs": [
                    {
                        **book.prompt_metadata(),
                        "directory": str(book.directory),
                        "eligible_paragraph_count": len(book.spans),
                    }
                    for book in books
                ],
                "config": {field.name: getattr(self.config, field.name) for field in fields(self.config)},
                "planned_unit_count": sum(len(units) for _, units in units_by_book),
                "limit_units_per_book": limit_units_per_book,
            }
        write_json(run_path, run_record)

        completed = self._completed_unit_ids(output / "units.jsonl") if resume else set()
        duplicate_keys = self._existing_duplicate_keys(output / "claims.jsonl") if resume else set()
        total_units = sum(len(units) for _, units in units_by_book)
        interrupted = False
        try:
            work = [
                (book, unit)
                for book, units in units_by_book
                for unit in units
                if unit.unit_id not in completed
            ]
            skipped = total_units - len(work)
            if skipped:
                print(f"Resume: skipping {skipped} completed units", flush=True)
            if self.workers == 1:
                for completed_index, (book, unit) in enumerate(work, start=skipped + 1):
                    outcome = self._run_unit(
                        book=book,
                        unit=unit,
                        run_id=run_id,
                        output=output,
                        duplicate_keys=duplicate_keys,
                    )
                    self._print_progress(completed_index, total_units, unit, outcome)
            else:
                executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="claim-unit")
                try:
                    futures = {
                        executor.submit(
                            self._run_unit,
                            book=book,
                            unit=unit,
                            run_id=run_id,
                            output=output,
                            duplicate_keys=duplicate_keys,
                        ): unit
                        for book, unit in work
                    }
                    for completed_index, future in enumerate(as_completed(futures), start=skipped + 1):
                        unit = futures[future]
                        outcome = future.result()
                        self._print_progress(completed_index, total_units, unit, outcome)
                except BaseException:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                else:
                    executor.shutdown(wait=True)
        except KeyboardInterrupt:
            interrupted = True
            raise
        finally:
            summary = self.summarize(output)
            if interrupted:
                run_record["status"] = "interrupted"
            elif summary["failed_units"]:
                run_record["status"] = "complete_with_errors"
            elif summary["model_incomplete_units"]:
                run_record["status"] = "complete_with_incomplete_units"
            else:
                run_record["status"] = "complete"
            run_record["finished_at"] = utc_now()
            run_record["summary"] = summary
            write_json(run_path, run_record)
            write_json(output / "summary.json", summary)
        return summary

    @staticmethod
    def _print_progress(completed_index: int, total_units: int, unit: ClaimUnit, outcome: dict[str, Any]) -> None:
        print(
            f"[{completed_index}/{total_units}] {outcome['status']} {unit.unit_id} "
            f"claims={outcome.get('claim_count', 0)} rejected={outcome.get('rejected_count', 0)} "
            f"seconds={outcome.get('duration_seconds', 0):.1f}",
            flush=True,
        )

    def _check_resume_compatibility(self, run: dict[str, Any], books: list[BookInput]) -> None:
        expected_ids = [book.book_id for book in books]
        actual_ids = [book["book_id"] for book in run.get("book_inputs", [])]
        checks = {
            "book IDs": (actual_ids, expected_ids),
            "backend": (run.get("backend"), self.provider.backend),
            "model": (run.get("model"), self.provider.model),
            "condition": (run.get("condition"), self.condition),
            "prompt version": (run.get("prompt_version"), self.config.prompt_version),
        }
        mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
        if mismatches:
            raise ValueError(f"Cannot resume because these settings changed: {', '.join(mismatches)}")

    def _run_unit(
        self,
        *,
        book: BookInput,
        unit: ClaimUnit,
        run_id: str,
        output: Path,
        duplicate_keys: set[str],
    ) -> dict[str, Any]:
        started = time.monotonic()
        validation_error: str | None = None
        response: dict[str, Any] | None = None
        response_normalizations: list[str] = []
        attempts = 0
        for attempt in range(1, self.max_retries + 2):
            attempts = attempt
            user_prompt = build_user_prompt(book, unit, retry_error=validation_error)
            try:
                result = self.provider.generate(
                    system_prompt=self.system_prompt,
                    user_prompt=user_prompt,
                    response_schema=self.response_schema,
                    temperature=self.config.temperature,
                )
                raw_record = {
                    "run_id": run_id,
                    "unit_id": unit.unit_id,
                    "book_id": book.book_id,
                    "attempt": attempt,
                    "generated_at": utc_now(),
                    "backend": self.provider.backend,
                    "model": self.provider.model,
                    "prompt_sha256": prompt_sha256(self.system_prompt, user_prompt),
                    "response_text": result.text,
                    "duration_seconds": result.duration_seconds,
                    "provider_metadata": result.metadata,
                }
                append_jsonl(output / "raw_responses.jsonl", raw_record)
                response = parse_json_object(result.text)
                response, response_normalizations = self._normalize_response(response)
                errors = sorted(self.response_validator.iter_errors(response), key=lambda error: list(error.path))
                if errors:
                    validation_error = self._format_validation_errors(errors)
                    response = None
                    continue
                if len(response["claims"]) > self.config.max_claims_per_unit:
                    validation_error = (
                        f"Response contains {len(response['claims'])} claims; configured maximum is "
                        f"{self.config.max_claims_per_unit}"
                    )
                    response = None
                    continue
                break
            except Exception as exc:  # Provider and malformed-response failures are retryable.
                validation_error = f"{type(exc).__name__}: {exc}"
                append_jsonl(
                    output / "errors.jsonl",
                    {
                        "run_id": run_id,
                        "unit_id": unit.unit_id,
                        "book_id": book.book_id,
                        "attempt": attempt,
                        "occurred_at": utc_now(),
                        "error": validation_error,
                    },
                )

        if response is None:
            audit = {
                **unit.audit_record(),
                "run_id": run_id,
                "status": "failed",
                "attempts": attempts,
                "claim_count": 0,
                "frame_count": 0,
                "rejected_count": 0,
                "model_unit_complete": False,
                "warnings": [],
                "response_normalizations": response_normalizations,
                "error": validation_error,
                "duration_seconds": time.monotonic() - started,
                "completed_at": utc_now(),
            }
            append_jsonl(output / "units.jsonl", audit)
            return audit

        claim_count = 0
        frame_count = 0
        rejected_count = 0
        for candidate_index, candidate in enumerate(response["claims"], start=1):
            result = self._materialize_candidate(
                candidate=candidate,
                candidate_index=candidate_index,
                book=book,
                unit=unit,
                run_id=run_id,
            )
            if result["rejection"] is not None:
                append_jsonl(output / "rejected_candidates.jsonl", result["rejection"])
                rejected_count += 1
                continue
            claim = result["claim"]
            duplicate_key = self._duplicate_key(claim)
            with self._duplicate_lock:
                is_duplicate = duplicate_key in duplicate_keys
                if not is_duplicate:
                    duplicate_keys.add(duplicate_key)
            if is_duplicate:
                append_jsonl(
                    output / "rejected_candidates.jsonl",
                    {
                        "record_type": "rejected_claim_candidate",
                        "run_id": run_id,
                        "unit_id": unit.unit_id,
                        "book_id": book.book_id,
                        "candidate_id": claim["candidate_id"],
                        "candidate": candidate,
                        "issues": ["exact_duplicate_of_existing_grounded_claim"],
                        "rejected_at": utc_now(),
                    },
                )
                rejected_count += 1
                continue
            append_jsonl(output / "claims.jsonl", claim)
            claim_count += 1
            for frame in result["frames"]:
                append_jsonl(output / "frames.jsonl", frame)
                frame_count += 1

        status = "complete" if response["unit_complete"] else "model_incomplete"
        audit = {
            **unit.audit_record(),
            "run_id": run_id,
            "status": status,
            "attempts": attempts,
            "claim_count": claim_count,
            "frame_count": frame_count,
            "rejected_count": rejected_count,
            "model_unit_complete": response["unit_complete"],
            "warnings": response["warnings"],
            "response_normalizations": response_normalizations,
            "error": None,
            "duration_seconds": time.monotonic() - started,
            "completed_at": utc_now(),
        }
        append_jsonl(output / "units.jsonl", audit)
        return audit

    @staticmethod
    def _normalize_response(response: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Apply only lossless, declared repairs before schema validation."""

        repairs: list[str] = []
        claims = response.get("claims")
        if not isinstance(claims, list):
            return response, repairs
        for claim_index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            labels = claim.get("topic_labels")
            if isinstance(labels, list):
                unique_labels = list(dict.fromkeys(labels))
                if unique_labels != labels:
                    claim["topic_labels"] = unique_labels
                    repairs.append(f"claims[{claim_index}].topic_labels:removed_duplicates")
        return response, repairs

    def _materialize_candidate(
        self,
        *,
        candidate: dict[str, Any],
        candidate_index: int,
        book: BookInput,
        unit: ClaimUnit,
        run_id: str,
    ) -> dict[str, Any]:
        candidate_id = stable_id(
            "candidate",
            {"run_id": run_id, "unit_id": unit.unit_id, "index": candidate_index, "candidate": candidate},
        )
        target_lookup = {span.span_id: span for span in unit.target_spans}
        grounded_evidence: list[dict[str, Any]] = []
        fatal_issues: list[str] = []
        if not any(item.get("support_type") == "primary" for item in candidate["evidence"]):
            fatal_issues.append("no_primary_evidence")
        for evidence_index, submitted in enumerate(candidate["evidence"], start=1):
            span = target_lookup.get(submitted["span_id"])
            if span is None:
                fatal_issues.append(f"evidence_span_not_in_target:{submitted['span_id']}")
                continue
            alignment = align_text(span.text, submitted["quote"])
            if alignment is None:
                fatal_issues.append(f"evidence_quote_not_found:{submitted['span_id']}")
                continue
            evidence_id = stable_id(
                "evidence",
                {
                    "candidate_id": candidate_id,
                    "index": evidence_index,
                    "span_id": span.span_id,
                    "start": alignment.start,
                    "end": alignment.end,
                },
            )
            grounded_evidence.append(
                {
                    "evidence_id": evidence_id,
                    "span_id": span.span_id,
                    "page_id": span.page_id,
                    "support_type": submitted["support_type"],
                    "quote": alignment.source_text,
                    "quote_sha256": hashlib.sha256(alignment.source_text.encode("utf-8")).hexdigest(),
                    "submitted_quote": submitted["quote"],
                    "alignment_method": alignment.method,
                    "span_char_start": alignment.start,
                    "span_char_end": alignment.end,
                    "page_char_start": span.page_char_start + alignment.start,
                    "page_char_end": span.page_char_start + alignment.end,
                    "offset_basis": "page_normalized_text",
                }
            )
        if fatal_issues:
            return {
                "claim": None,
                "frames": [],
                "rejection": {
                    "record_type": "rejected_claim_candidate",
                    "run_id": run_id,
                    "unit_id": unit.unit_id,
                    "book_id": book.book_id,
                    "candidate_id": candidate_id,
                    "candidate": candidate,
                    "issues": fatal_issues,
                    "rejected_at": utc_now(),
                },
            }

        primary = next(item for item in grounded_evidence if item["support_type"] == "primary")
        primary_span = target_lookup[primary["span_id"]]
        claim_id = stable_id(
            "claim",
            {
                "book_id": book.book_id,
                "claim_text": normalize_whitespace(candidate["claim_text"]).casefold(),
                "evidence": [
                    (item["span_id"], item["span_char_start"], item["span_char_end"])
                    for item in grounded_evidence
                ],
            },
        )
        issues: list[str] = []
        flags: set[str] = set()

        predicate = dict(candidate["predicate"])
        predicate["grounding"] = ground_surface(predicate.get("surface_form"), grounded_evidence)
        if predicate.get("surface_form") and predicate["grounding"] is None:
            issues.append("predicate_surface_not_grounded")

        participants = []
        for index, participant_candidate in enumerate(candidate["participants"], start=1):
            participant = dict(participant_candidate)
            participant["mention_id"] = stable_id(
                "mention",
                {"claim_id": claim_id, "index": index, "mention": participant["mention"]},
                length=20,
            )
            participant["entity_id"] = None
            participant["grounding"] = ground_surface(participant["mention"], grounded_evidence)
            if participant["grounding"] is None:
                issues.append(f"participant_not_grounded:{participant['mention']}")
                flags.add("participant_role_uncertain")
            if participant["mention"].strip().casefold() in {
                "i", "me", "my", "we", "us", "our", "he", "him", "his", "she", "her", "they", "them", "their", "it", "its"
            }:
                flags.add("unresolved_pronoun")
            participants.append(participant)

        times = self._ground_field_list(candidate["times"], grounded_evidence, issues, "time")
        locations = self._ground_field_list(candidate["locations"], grounded_evidence, issues, "location")
        quantities = self._ground_field_list(candidate["quantities"], grounded_evidence, issues, "quantity")
        if any(item["grounding"] is None for item in times):
            flags.add("time_unparseable")
        if any(item["grounding"] is None for item in locations):
            flags.add("location_ambiguous")

        self._check_attribution(candidate, book, unit, issues, flags)
        if candidate.get("epistemic_cue") and not self._surface_in_spans(candidate["epistemic_cue"], unit):
            issues.append("epistemic_cue_not_grounded")
            flags.add("wrong_attribution")

        frame_records: list[dict[str, Any]] = []
        frame_ids: list[str] = []
        for frame_index, frame_candidate in enumerate(candidate["frame_candidates"], start=1):
            cue_grounding = ground_surface(frame_candidate["cue_quote"], grounded_evidence)
            frame_id = stable_id(
                "frame",
                {"claim_id": claim_id, "index": frame_index, "frame": frame_candidate},
            )
            frame_ids.append(frame_id)
            frame_issues: list[str] = []
            if cue_grounding is None:
                frame_issues.append("frame_cue_not_grounded_in_claim_evidence")
                flags.add("frame_uncertain")
            frame_record = {
                "schema_version": "0.1.0",
                "record_type": "frame_candidate",
                "frame_id": frame_id,
                "claim_id": claim_id,
                "book_id": book.book_id,
                "function": frame_candidate["function"],
                "label": frame_candidate["label"],
                "target": frame_candidate["target"],
                "cue_quote": frame_candidate["cue_quote"],
                "evidence_id": cue_grounding["evidence_id"] if cue_grounding else None,
                "codebook": {
                    "name": "entman_frame_functions",
                    "version": "0.1.0",
                    "status": "provisional_requires_supervisor_approval",
                },
                "assignment": {"method": "llm_candidate", "run_id": run_id},
                "verification": {"cue_grounded": cue_grounding is not None, "issues": frame_issues},
                "review": {
                    "status": "pending" if cue_grounding else "needs_revision",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "note": None,
                },
            }
            frame_errors = list(self.frame_validator.iter_errors(frame_record))
            if frame_errors:
                issues.append("invalid_materialized_frame:" + self._format_validation_errors(frame_errors))
                flags.add("frame_uncertain")
                frame_ids.pop()
            else:
                frame_records.append(frame_record)

        exact_quote_match = all(item["alignment_method"] == "exact" for item in grounded_evidence)
        if not exact_quote_match:
            flags.add("quote_not_exact")
        all_grounded = not any(
            issue.startswith(("predicate_", "participant_", "time_", "location_", "quantity_", "epistemic_", "attribution_"))
            for issue in issues
        )
        claim = {
            "schema_version": "1.0.0",
            "record_type": "claim",
            "claim_id": claim_id,
            "candidate_id": candidate_id,
            "book_id": book.book_id,
            "claim_text": candidate["claim_text"],
            "claim_kind": candidate["claim_kind"],
            "polarity": candidate["polarity"],
            "epistemic_status": candidate["epistemic_status"],
            "epistemic_cue": candidate["epistemic_cue"],
            "attribution_chain": candidate["attribution_chain"],
            "predicate": predicate,
            "participants": participants,
            "times": times,
            "locations": locations,
            "quantities": quantities,
            "topic_labels": candidate["topic_labels"],
            "evidence": grounded_evidence,
            "frame_candidate_ids": frame_ids,
            "source_context": {
                "primary_span_id": primary_span.span_id,
                "page_id": primary_span.page_id,
                "pdf_page_number": primary_span.page_number,
                "printed_page_label": primary_span.page_label,
                "part_title": primary_span.section.get("part_title"),
                "chapter_title": primary_span.section.get("chapter_title"),
                "section_title": primary_span.section.get("section_title"),
                "extraction_method": primary_span.extraction_method,
            },
            "extraction": {
                "condition": self.condition,
                "backend": self.provider.backend,
                "model": self.provider.model,
                "prompt_version": self.config.prompt_version,
                "run_id": run_id,
                "unit_id": unit.unit_id,
                "pass_index": 1,
                "generated_at": utc_now(),
            },
            "verification": {
                "schema_valid": True,
                "evidence_grounding": "passed",
                "field_grounding": "passed" if all_grounded else "needs_review",
                "exact_quote_match": exact_quote_match,
                "exact_offset_match": True,
                "source_fidelity": "pending",
                "historical_truth": "not_assessed",
                "issues": issues,
            },
            "review": {
                "status": "pending",
                "flags": sorted(flags),
                "reviewer_id": None,
                "reviewed_at": None,
                "guideline_version": self.config.annotation_guideline_version,
                "note": None,
            },
        }
        claim_errors = list(self.claim_validator.iter_errors(claim))
        if claim_errors:
            return {
                "claim": None,
                "frames": [],
                "rejection": {
                    "record_type": "rejected_claim_candidate",
                    "run_id": run_id,
                    "unit_id": unit.unit_id,
                    "book_id": book.book_id,
                    "candidate_id": candidate_id,
                    "candidate": candidate,
                    "issues": ["invalid_materialized_claim", self._format_validation_errors(claim_errors)],
                    "rejected_at": utc_now(),
                },
            }
        return {"claim": claim, "frames": frame_records, "rejection": None}

    @staticmethod
    def _ground_field_list(
        candidates: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        issues: list[str],
        field_name: str,
    ) -> list[dict[str, Any]]:
        grounded = []
        for candidate in candidates:
            item = dict(candidate)
            item["grounding"] = ground_surface(item.get("mention"), evidence)
            if item["grounding"] is None:
                issues.append(f"{field_name}_not_grounded:{item.get('mention')}")
            if field_name == "location":
                item["entity_id"] = None
            grounded.append(item)
        return grounded

    @staticmethod
    def _surface_in_spans(surface: str, unit: ClaimUnit) -> bool:
        return any(
            align_text(span.text, surface) is not None
            for span in (*unit.context_before, *unit.target_spans, *unit.context_after)
        )

    def _check_attribution(
        self,
        candidate: dict[str, Any],
        book: BookInput,
        unit: ClaimUnit,
        issues: list[str],
        flags: set[str],
    ) -> None:
        authors = {author.casefold() for author in book.authors}
        for attribution in candidate["attribution_chain"]:
            speaker = attribution.get("speaker")
            cue = attribution.get("cue")
            basis = attribution.get("basis")
            if basis == "book_metadata" and (not speaker or speaker.casefold() not in authors):
                issues.append(f"attribution_book_metadata_mismatch:{speaker}")
                flags.add("wrong_attribution")
            elif basis in {"target_text", "context_text"} and speaker and not self._surface_in_spans(speaker, unit):
                issues.append(f"attribution_speaker_not_grounded:{speaker}")
                flags.add("wrong_attribution")
            if cue and not self._surface_in_spans(cue, unit):
                issues.append(f"attribution_cue_not_grounded:{cue}")
                flags.add("wrong_attribution")

    @staticmethod
    def _format_validation_errors(errors: Iterable[Any]) -> str:
        messages = []
        for error in errors:
            path = ".".join(str(item) for item in error.absolute_path) or "$"
            messages.append(f"{path}: {error.message}")
        return "; ".join(messages[:12])

    @staticmethod
    def _completed_unit_ids(path: Path) -> set[str]:
        if not path.is_file():
            return set()
        latest: dict[str, str] = {}
        for record in iter_jsonl(path):
            latest[record["unit_id"]] = record["status"]
        return {unit_id for unit_id, status in latest.items() if status in {"complete", "model_incomplete"}}

    @staticmethod
    def _duplicate_key(claim: dict[str, Any]) -> str:
        material = {
            "book_id": claim["book_id"],
            "claim_text": normalize_whitespace(claim["claim_text"]).casefold(),
            "evidence": [
                (item["span_id"], item["span_char_start"], item["span_char_end"])
                for item in claim["evidence"]
            ],
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()

    def _existing_duplicate_keys(self, path: Path) -> set[str]:
        if not path.is_file():
            return set()
        return {self._duplicate_key(claim) for claim in iter_jsonl(path)}

    @staticmethod
    def summarize(output: Path) -> dict[str, Any]:
        unit_history = list(iter_jsonl(output / "units.jsonl")) if (output / "units.jsonl").is_file() else []
        latest_units = {unit["unit_id"]: unit for unit in unit_history}
        units = list(latest_units.values())
        claims = list(iter_jsonl(output / "claims.jsonl")) if (output / "claims.jsonl").is_file() else []
        frames = list(iter_jsonl(output / "frames.jsonl")) if (output / "frames.jsonl").is_file() else []
        rejected = (
            list(iter_jsonl(output / "rejected_candidates.jsonl"))
            if (output / "rejected_candidates.jsonl").is_file()
            else []
        )
        status_counts = Counter(unit["status"] for unit in units)
        book_claims = Counter(claim["book_id"] for claim in claims)
        completed_units = status_counts["complete"] + status_counts["model_incomplete"]
        total_duration = sum(float(unit.get("duration_seconds", 0)) for unit in units)
        return {
            "generated_at": utc_now(),
            "processed_units": len(units),
            "complete_units": status_counts["complete"],
            "model_incomplete_units": status_counts["model_incomplete"],
            "failed_units": status_counts["failed"],
            "grounded_claim_candidates": len(claims),
            "rejected_candidates": len(rejected),
            "frame_candidates": len(frames),
            "grounded_claims_per_completed_unit": round(len(claims) / completed_units, 3) if completed_units else 0,
            "unit_runtime_seconds": round(total_duration, 3),
            "mean_unit_runtime_seconds": round(total_duration / len(units), 3) if units else 0,
            "claims_by_book": dict(sorted(book_claims.items())),
            "claim_kinds": dict(sorted(Counter(claim["claim_kind"] for claim in claims).items())),
            "epistemic_statuses": dict(sorted(Counter(claim["epistemic_status"] for claim in claims).items())),
            "frame_functions": dict(sorted(Counter(frame["function"] for frame in frames).items())),
            "claims_pending_human_review": sum(claim["review"]["status"] == "pending" for claim in claims),
            "claims_with_field_review_issues": sum(
                claim["verification"]["field_grounding"] == "needs_review" for claim in claims
            ),
            "claims_with_exact_model_quote": sum(
                claim["verification"]["exact_quote_match"] for claim in claims
            ),
            "claims_with_review_flags": sum(bool(claim["review"]["flags"]) for claim in claims),
            "grounded_frame_cues": sum(frame["verification"]["cue_grounded"] for frame in frames),
            "historical_truth_assessed": 0,
        }
