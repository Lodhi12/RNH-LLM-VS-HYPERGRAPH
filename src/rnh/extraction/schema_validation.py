from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .io_utils import read_json, read_jsonl, utc_now, write_json


SCHEMA_FILES = {
    "manifest": "book_extraction_v2.schema.json",
    "page": "page_v2.schema.json",
    "span": "source_span_v2.schema.json",
    "block": "text_block_v2.schema.json",
    "structure": "book_structure_v2.schema.json",
    "image": "image_occurrence_v2.schema.json",
}


def format_error(error: Any, record_number: int | None = None) -> dict[str, Any]:
    path = ".".join(str(part) for part in error.absolute_path)
    return {
        "record_number": record_number,
        "field": path or "$",
        "message": error.message,
    }


def validate_records(
    validator: Any,
    records: Iterable[dict[str, Any]],
    max_errors: int,
) -> tuple[int, list[dict[str, Any]]]:
    count = 0
    errors: list[dict[str, Any]] = []
    for count, record in enumerate(records, start=1):
        for error in validator.iter_errors(record):
            errors.append(format_error(error, count))
            if len(errors) >= max_errors:
                return count, errors
    return count, errors


def validate_book(
    project_root: Path,
    book_dir: Path,
    claims_path: Path | None = None,
    max_errors: int = 100,
) -> dict[str, Any]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise RuntimeError("Schema validation requires the 'jsonschema' package") from exc

    project_root = project_root.expanduser().resolve()
    book_dir = book_dir.expanduser().resolve()
    schemas_dir = project_root / "schemas"
    manifest = read_json(book_dir / "manifest.json")
    checks: dict[str, Any] = {}
    all_errors: list[dict[str, Any]] = []

    def validator(name: str) -> Any:
        schema = read_json(schemas_dir / SCHEMA_FILES[name])
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    manifest_errors = [format_error(error) for error in validator("manifest").iter_errors(manifest)]
    checks["manifest"] = {"records": 1, "errors": len(manifest_errors)}
    all_errors.extend({"artifact": "manifest", **error} for error in manifest_errors)

    pages_path = book_dir / manifest["artifacts"]["pages"]
    page_count, page_errors = validate_records(validator("page"), read_jsonl(pages_path), max_errors)
    checks["pages"] = {"records": page_count, "errors": len(page_errors)}
    all_errors.extend({"artifact": "pages", **error} for error in page_errors)

    spans_path = book_dir / manifest["artifacts"]["spans"]
    span_count, span_errors = validate_records(validator("span"), read_jsonl(spans_path), max_errors)
    checks["spans"] = {"records": span_count, "errors": len(span_errors)}
    all_errors.extend({"artifact": "spans", **error} for error in span_errors)

    blocks_path = book_dir / manifest["artifacts"]["blocks"]
    block_count, block_errors = validate_records(validator("block"), read_jsonl(blocks_path), max_errors)
    checks["blocks"] = {"records": block_count, "errors": len(block_errors)}
    all_errors.extend({"artifact": "blocks", **error} for error in block_errors)

    structure = read_json(book_dir / manifest["artifacts"]["structure"])
    structure_errors = [format_error(error) for error in validator("structure").iter_errors(structure)]
    checks["structure"] = {"records": 1, "errors": len(structure_errors)}
    all_errors.extend({"artifact": "structure", **error} for error in structure_errors)

    images_path = book_dir / manifest["artifacts"]["images"]
    image_count, image_errors = validate_records(validator("image"), read_jsonl(images_path), max_errors)
    checks["images"] = {"records": image_count, "errors": len(image_errors)}
    all_errors.extend({"artifact": "images", **error} for error in image_errors)

    if claims_path:
        raise ValueError(
            "Claim records use the RNH claim schemas and must be checked with `rnh-claims validate`."
        )

    report = {
        "schema": "historical-book-schema-validation-v2",
        "book_id": manifest.get("book_id"),
        "validated_at": utc_now(),
        "status": "pass" if not all_errors else "fail",
        "checks": checks,
        "error_count": len(all_errors),
        "error_samples": all_errors[:max_errors],
    }
    output_path = book_dir / "reports" / "schema_validation.json"
    write_json(output_path, report)
    return report
