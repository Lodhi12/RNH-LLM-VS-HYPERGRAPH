from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from . import __version__
from .io_utils import read_json, sha256_bytes, sha256_file, sha256_text, slugify, stable_id, utc_now, write_json, write_jsonl
from .structure import build_sections, context_for_page, normalize_toc
from .text import normalize_text, paragraph_offsets, sentence_offsets, word_count


DEFAULT_DPI = 220
DEFAULT_MIN_TEXT_CHARS = 80


@dataclass(frozen=True)
class ExtractionConfig:
    ocr_mode: str = "auto"
    ocr_language: str = "eng"
    ocr_dpi: int = DEFAULT_DPI
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS
    include_blocks: bool = True
    extract_images: bool = True
    min_image_bytes: int = 512
    title: str | None = None
    author: str | None = None
    publication_year: int | None = None
    language: str | None = None


def normalize_pdf_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    match = re.match(
        r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
        r"(?:(Z)|([+-])(\d{2})'?(\d{2})'?)?$",
        value,
    )
    if not match:
        return value
    year, month, day, hour, minute, second, zulu, sign, offset_h, offset_m = match.groups()
    result = f"{year}-{month or '01'}-{day or '01'}T{hour or '00'}:{minute or '00'}:{second or '00'}"
    if zulu:
        return result + "+00:00"
    if sign and offset_h and offset_m:
        return f"{result}{sign}{offset_h}:{offset_m}"
    return result


def find_tessdata_dir(language: str, project_root: Path) -> Path | None:
    candidates = [
        project_root / "models" / "tessdata",
        Path("/usr/share/tessdata"),
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/local/share/tessdata"),
    ]
    env_path = os.environ.get("TESSDATA_PREFIX")
    if env_path:
        candidates.append(Path(env_path))
    return next((path for path in candidates if (path / f"{language}.traineddata").exists()), None)


def should_ocr(native_text: str, config: ExtractionConfig) -> bool:
    if config.ocr_mode == "off":
        return False
    if config.ocr_mode == "on":
        return True
    return len(native_text.strip()) < config.min_text_chars


def ocr_page(
    page: pymupdf.Page,
    config: ExtractionConfig,
    tesseract_bin: str,
    tessdata_dir: Path,
) -> tuple[str, float | None]:
    scale = config.ocr_dpi / 72
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    with tempfile.TemporaryDirectory(prefix="book_pipeline_ocr_") as temporary_dir:
        temporary = Path(temporary_dir)
        image_path = temporary / "page.png"
        output_base = temporary / "result"
        pixmap.save(image_path)
        result = subprocess.run(
            [
                tesseract_bin,
                str(image_path),
                str(output_base),
                "-l",
                config.ocr_language,
                "--tessdata-dir",
                str(tessdata_dir),
                "--psm",
                "3",
                "txt",
                "tsv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Tesseract OCR failed")
        raw_text = (output_base.with_suffix(".txt")).read_text(encoding="utf-8", errors="replace")
        confidences: list[float] = []
        tsv_path = output_base.with_suffix(".tsv")
        if tsv_path.exists():
            with tsv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    try:
                        confidence = float(row.get("conf", "-1"))
                    except (TypeError, ValueError):
                        continue
                    if confidence >= 0 and str(row.get("text") or "").strip():
                        confidences.append(confidence)
        mean_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
        return raw_text, mean_confidence


def extract_text_blocks(page: pymupdf.Page, book_id: str, page_number: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    raw = page.get_text("dict", sort=True)
    for block_index, block in enumerate(raw.get("blocks", []), start=1):
        if block.get("type") != 0:
            continue
        lines: list[str] = []
        for line in block.get("lines", []):
            line_text = "".join(str(span.get("text") or "") for span in line.get("spans", []))
            if line_text.strip():
                lines.append(line_text)
        text = normalize_text("\n".join(lines))
        if not text:
            continue
        output.append(
            {
                "schema": "historical-book-text-block-v2",
                "block_id": f"{book_id}:p{page_number:04d}:block:{block_index:03d}",
                "book_id": book_id,
                "page_id": f"{book_id}:p{page_number:04d}",
                "page_number": page_number,
                "reading_order": block_index,
                "bbox": [round(float(item), 2) for item in block.get("bbox", [])],
                "text": text,
                "text_sha256": sha256_text(text),
                "extraction_method": "native",
            }
        )
    return output


def build_spans(page: dict[str, Any]) -> list[dict[str, Any]]:
    text = page["text"]["normalized"]
    book_id = page["book_id"]
    page_number = page["page_number"]
    output: list[dict[str, Any]] = []
    for paragraph_index, (start, end) in enumerate(paragraph_offsets(text), start=1):
        paragraph_text = text[start:end]
        paragraph_id = (
            f"{book_id}:p{page_number:04d}:para:{paragraph_index:03d}:"
            f"{sha256_text(paragraph_text)[:10]}"
        )
        base = {
            "schema": "historical-book-source-span-v2",
            "book_id": book_id,
            "page_id": page["page_id"],
            "page_number": page_number,
            "page_label": page["page_label"],
            "section": page["section"],
            "extraction_method": page["extraction"]["method"],
            "offset_basis": "pages.text.normalized",
            "claim_eligible": page["section"]["claim_eligible"],
        }
        output.append(
            {
                **base,
                "span_id": paragraph_id,
                "span_type": "paragraph",
                "parent_span_id": None,
                "paragraph_index": paragraph_index,
                "sentence_index": None,
                "page_char_start": start,
                "page_char_end": end,
                "word_count": word_count(paragraph_text),
                "char_count": len(paragraph_text),
                "text": paragraph_text,
                "text_sha256": sha256_text(paragraph_text),
            }
        )
        for sentence_index, (sentence_start, sentence_end) in enumerate(
            sentence_offsets(text, start, end), start=1
        ):
            sentence_text = text[sentence_start:sentence_end]
            if word_count(sentence_text) < 3:
                continue
            sentence_id = (
                f"{book_id}:p{page_number:04d}:sent:{paragraph_index:03d}-{sentence_index:03d}:"
                f"{sha256_text(sentence_text)[:10]}"
            )
            output.append(
                {
                    **base,
                    "span_id": sentence_id,
                    "span_type": "sentence",
                    "parent_span_id": paragraph_id,
                    "paragraph_index": paragraph_index,
                    "sentence_index": sentence_index,
                    "page_char_start": sentence_start,
                    "page_char_end": sentence_end,
                    "word_count": word_count(sentence_text),
                    "char_count": len(sentence_text),
                    "text": sentence_text,
                    "text_sha256": sha256_text(sentence_text),
                }
            )
    return output


def extract_page_images(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    book_dir: Path,
    book_id: str,
    page_number: int,
    min_bytes: int,
    known_images: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    skipped = 0
    image_dir = book_dir / "media" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for image_index, image_info in enumerate(page.get_images(full=True), start=1):
        xref = int(image_info[0])
        try:
            extracted = doc.extract_image(xref)
        except Exception as exc:
            rows.append(
                {
                    "schema": "historical-book-image-occurrence-v2",
                    "book_id": book_id,
                    "page_id": f"{book_id}:p{page_number:04d}",
                    "page_number": page_number,
                    "image_index": image_index,
                    "pdf_xref": xref,
                    "status": "extraction_failed",
                    "error": str(exc),
                }
            )
            continue
        payload = extracted.get("image") or b""
        if len(payload) < min_bytes:
            skipped += 1
            continue
        digest = sha256_bytes(payload)
        extension = re.sub(r"[^a-z0-9]", "", str(extracted.get("ext") or "bin").lower()) or "bin"
        file_name = known_images.get(digest)
        if not file_name:
            file_name = f"{digest[:20]}.{extension}"
            (image_dir / file_name).write_bytes(payload)
            known_images[digest] = file_name
        rows.append(
            {
                "schema": "historical-book-image-occurrence-v2",
                "image_id": f"image:{digest[:20]}",
                "book_id": book_id,
                "page_id": f"{book_id}:p{page_number:04d}",
                "page_number": page_number,
                "image_index": image_index,
                "pdf_xref": xref,
                "status": "extracted",
                "file_path": f"media/images/{file_name}",
                "sha256": digest,
                "bytes": len(payload),
                "format": extension,
                "width": int(image_info[2] or 0),
                "height": int(image_info[3] or 0),
                "caption": None,
                "caption_status": "not_extracted",
            }
        )
    return rows, skipped


def extract_pdf(
    pdf_path: Path,
    output_base: Path,
    config: ExtractionConfig,
    project_root: Path,
    overwrite: bool = False,
) -> Path:
    pdf_path = pdf_path.expanduser().resolve()
    output_base = output_base.expanduser().resolve()
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected an existing PDF: {pdf_path}")

    source_hash = sha256_file(pdf_path)
    book_id = f"book:{source_hash[:16]}"
    book_dir = output_base / f"{slugify(pdf_path.stem)}-{source_hash[:12]}"
    previous_book: dict[str, Any] = {}
    previous_manifest_path = book_dir / "manifest.json"
    if previous_manifest_path.is_file():
        previous_manifest = read_json(previous_manifest_path)
        if previous_manifest.get("book_id") == book_id:
            previous_book = previous_manifest.get("book") or {}
    if book_dir.exists() and any(book_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output already exists: {book_dir}. Use --overwrite to replace generated v2 data.")
    if overwrite and book_dir.exists():
        allowed_root = output_base.resolve()
        if book_dir.parent.resolve() != allowed_root:
            raise ValueError(f"Refusing to replace unexpected directory: {book_dir}")
        shutil.rmtree(book_dir)
    (book_dir / "extraction").mkdir(parents=True, exist_ok=True)
    (book_dir / "claims").mkdir(parents=True, exist_ok=True)
    (book_dir / "reports").mkdir(parents=True, exist_ok=True)

    tesseract_bin = shutil.which("tesseract")
    tessdata_dir = find_tessdata_dir(config.ocr_language, project_root)
    if config.ocr_mode != "off" and (not tesseract_bin or not tessdata_dir):
        raise RuntimeError(
            f"OCR requested but Tesseract or language data '{config.ocr_language}' is unavailable"
        )

    doc = pymupdf.open(pdf_path)
    raw_metadata = dict(doc.metadata or {})
    pdf_metadata = {
        key: normalize_pdf_date(value) if key in {"creationDate", "modDate"} else value
        for key, value in raw_metadata.items()
    }
    toc = normalize_toc(doc.get_toc(simple=True), doc.page_count)
    pages: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    known_images: dict[str, str] = {}
    skipped_images = 0
    extraction_errors: list[dict[str, Any]] = []

    print(f"Extracting {pdf_path.name} ({doc.page_count} pages) into {book_dir}")
    for page_number, page in enumerate(doc, start=1):
        raw_native = page.get_text("text", sort=True)
        native_text = normalize_text(raw_native)
        raw_selected = raw_native
        normalized = native_text
        method = "native"
        ocr_confidence: float | None = None
        ocr_error: str | None = None

        if should_ocr(native_text, config):
            try:
                assert tesseract_bin is not None and tessdata_dir is not None
                raw_selected, ocr_confidence = ocr_page(page, config, tesseract_bin, tessdata_dir)
                normalized = normalize_text(raw_selected)
                method = "ocr"
            except Exception as exc:
                method = "native_ocr_failed"
                ocr_error = str(exc)
                extraction_errors.append({"page_number": page_number, "error": ocr_error})

        quality_flags: list[str] = []
        if not normalized:
            quality_flags.append("empty_text")
        elif len(normalized) < config.min_text_chars:
            quality_flags.append("low_text")
        if method == "ocr":
            quality_flags.append("ocr_used")
        if method == "native_ocr_failed":
            quality_flags.append("ocr_failed")

        section = context_for_page(page_number, toc)
        page_id = f"{book_id}:p{page_number:04d}"
        page_record = {
            "schema": "historical-book-page-v2",
            "book_id": book_id,
            "page_id": page_id,
            "page_number": page_number,
            "page_label": page.get_label(),
            "geometry": {
                "width": round(float(page.rect.width), 2),
                "height": round(float(page.rect.height), 2),
                "rotation": int(page.rotation),
            },
            "section": section,
            "extraction": {
                "method": method,
                "native_engine": "PyMuPDF",
                "ocr_engine": "Tesseract" if method.startswith("ocr") else None,
                "ocr_language": config.ocr_language if method.startswith("ocr") else None,
                "ocr_dpi": config.ocr_dpi if method.startswith("ocr") else None,
                "ocr_mean_word_confidence": ocr_confidence,
                "error": ocr_error,
            },
            "text": {
                "raw": raw_selected,
                "normalized": normalized,
                "normalization": "normalize_text_v2",
                "sha256": sha256_text(normalized),
            },
            "counts": {"characters": len(normalized), "words": word_count(normalized)},
            "quality_flags": quality_flags,
        }
        pages.append(page_record)
        page_spans = build_spans(page_record)
        spans.extend(page_spans)
        if config.include_blocks:
            blocks.extend(extract_text_blocks(page, book_id, page_number))
        if config.extract_images:
            page_images, page_skipped = extract_page_images(
                doc,
                page,
                book_dir,
                book_id,
                page_number,
                config.min_image_bytes,
                known_images,
            )
            images.extend(page_images)
            skipped_images += page_skipped
        if page_number == 1 or page_number == doc.page_count or page_number % 25 == 0:
            print(f"  page {page_number}/{doc.page_count}: {method}, {len(normalized)} chars")

    sections = build_sections(toc, pages)
    page_methods = Counter(page["extraction"]["method"] for page in pages)
    empty_pages = [page["page_number"] for page in pages if not page["text"]["normalized"]]
    low_text_pages = [
        page["page_number"]
        for page in pages
        if 0 < page["counts"]["characters"] < config.min_text_chars
    ]
    span_offset_errors = []
    page_by_id = {page["page_id"]: page for page in pages}
    for span in spans:
        page_text = page_by_id[span["page_id"]]["text"]["normalized"]
        start, end = span["page_char_start"], span["page_char_end"]
        if not (0 <= start < end <= len(page_text)) or page_text[start:end] != span["text"]:
            span_offset_errors.append(span["span_id"])

    write_jsonl(book_dir / "extraction" / "pages.jsonl", pages)
    write_jsonl(book_dir / "extraction" / "spans.jsonl", spans)
    write_jsonl(book_dir / "extraction" / "blocks.jsonl", blocks)
    write_jsonl(book_dir / "media" / "images.jsonl", images)
    write_json(
        book_dir / "extraction" / "structure.json",
        {
            "schema": "historical-book-structure-v2",
            "book_id": book_id,
            "method": "pdf_bookmarks",
            "method_limitations": "PDF bookmarks may be missing or inaccurate and require sampled human review.",
            "toc": toc,
            "sections": sections,
        },
    )

    report = {
        "schema": "historical-book-extraction-verification-v2",
        "book_id": book_id,
        "verification_scope": "structural_integrity_and_source_traceability",
        "historical_truth_assessed": False,
        "page_count": doc.page_count,
        "pages_written": len(pages),
        "paragraph_span_count": sum(span["span_type"] == "paragraph" for span in spans),
        "sentence_span_count": sum(span["span_type"] == "sentence" for span in spans),
        "pages_by_method": dict(sorted(page_methods.items())),
        "empty_pages": empty_pages,
        "low_text_pages": low_text_pages,
        "span_offset_error_count": len(span_offset_errors),
        "span_offset_error_samples": span_offset_errors[:50],
        "toc_entry_count": len(toc),
        "section_count": len(sections),
        "image_occurrence_count": sum(row.get("status") == "extracted" for row in images),
        "unique_image_count": len(known_images),
        "skipped_small_image_count": skipped_images,
        "extraction_errors": extraction_errors,
        "status": "pass" if len(pages) == doc.page_count and not span_offset_errors else "needs_review",
    }
    write_json(book_dir / "reports" / "extraction_summary.json", report)

    previous_authors = [
        creator.get("name")
        for creator in previous_book.get("creators") or []
        if creator.get("role") == "author" and creator.get("name")
    ]
    selected_author = config.author or (previous_authors[0] if previous_authors else None) or pdf_metadata.get("author")
    selected_title = config.title or previous_book.get("title") or pdf_metadata.get("title") or pdf_path.stem
    selected_year = config.publication_year
    if selected_year is None:
        selected_year = previous_book.get("publication_year")
    selected_language = config.language or previous_book.get("language") or "en"

    manifest = {
        "schema": "historical-book-extraction-v2",
        "schema_version": "2.0.0",
        "book_id": book_id,
        "created_at": utc_now(),
        "book": {
            "title": selected_title,
            "creators": ([{"name": selected_author, "role": "author"}] if selected_author else []),
            "publication_year": selected_year,
            "language": selected_language,
            "page_count": doc.page_count,
            "pdf_metadata": pdf_metadata,
        },
        "source": {
            "file_name": pdf_path.name,
            "media_type": "application/pdf",
            "size_bytes": pdf_path.stat().st_size,
            "sha256": source_hash,
        },
        "pipeline": {
            "name": "rnh_research_pipeline",
            "version": __version__,
            "run_id": stable_id("extract-run", source_hash, utc_now()),
            "text_engine": "PyMuPDF",
            "text_engine_version": getattr(pymupdf, "__version__", None),
            "ocr_engine": "Tesseract",
            "configuration": {
                "ocr_mode": config.ocr_mode,
                "ocr_language": config.ocr_language,
                "ocr_dpi": config.ocr_dpi,
                "min_text_chars": config.min_text_chars,
                "include_blocks": config.include_blocks,
                "extract_images": config.extract_images,
                "min_image_bytes": config.min_image_bytes,
            },
        },
        "artifacts": {
            "pages": "extraction/pages.jsonl",
            "spans": "extraction/spans.jsonl",
            "blocks": "extraction/blocks.jsonl",
            "structure": "extraction/structure.json",
            "images": "media/images.jsonl",
            "extraction_summary": "reports/extraction_summary.json",
            "extraction_verification": "reports/extraction_verification.json",
        },
        "scope": {
            "represents": "what was extracted from this specific PDF",
            "does_not_represent": "independent historical truth",
        },
    }
    write_json(book_dir / "manifest.json", manifest)
    write_json(
        book_dir / "run_local.json",
        {
            "notice": "Local-only convenience metadata; do not commit when paths are sensitive.",
            "source_local_path": str(pdf_path),
            "book_directory": str(book_dir),
        },
    )
    doc.close()
    print(f"Extraction complete: {book_dir}")
    return book_dir
