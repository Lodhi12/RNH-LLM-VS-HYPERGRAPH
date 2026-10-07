"""Input adapters and deterministic claim-unit construction."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


_JSONL_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class SourceSpan:
    book_id: str
    page_id: str
    page_number: int
    page_label: str | None
    section: dict[str, Any]
    extraction_method: str | None
    offset_basis: str
    span_id: str
    span_type: str
    parent_span_id: str | None
    paragraph_index: int | None
    page_char_start: int
    page_char_end: int
    text: str
    text_sha256: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "SourceSpan":
        return cls(
            book_id=record["book_id"],
            page_id=record["page_id"],
            page_number=record["page_number"],
            page_label=record.get("page_label") or None,
            section=record.get("section") or {},
            extraction_method=record.get("extraction_method"),
            offset_basis=record.get("offset_basis", "pages.text.normalized"),
            span_id=record["span_id"],
            span_type=record["span_type"],
            parent_span_id=record.get("parent_span_id"),
            paragraph_index=record.get("paragraph_index"),
            page_char_start=record["page_char_start"],
            page_char_end=record["page_char_end"],
            text=record["text"],
            text_sha256=record["text_sha256"],
        )

    def prompt_record(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "pdf_page_number": self.page_number,
            "printed_page_label": self.page_label,
            "chapter_title": self.section.get("chapter_title"),
            "section_title": self.section.get("section_title"),
            "text": self.text,
        }


@dataclass(frozen=True)
class BookInput:
    directory: Path
    manifest: dict[str, Any]
    spans: tuple[SourceSpan, ...]

    @property
    def book_id(self) -> str:
        return self.manifest["book_id"]

    @property
    def title(self) -> str:
        return self.manifest.get("book", {}).get("title") or "Unknown title"

    @property
    def authors(self) -> list[str]:
        creators = self.manifest.get("book", {}).get("creators") or []
        authors = [item.get("name") for item in creators if item.get("role") == "author" and item.get("name")]
        return authors or [item["name"] for item in creators if item.get("name")]

    def prompt_metadata(self) -> dict[str, Any]:
        book = self.manifest.get("book", {})
        source = self.manifest.get("source", {})
        return {
            "book_id": self.book_id,
            "title": self.title,
            "authors": self.authors,
            "publication_year": book.get("publication_year"),
            "language": book.get("language"),
            "source_sha256": source.get("sha256"),
        }


@dataclass(frozen=True)
class ClaimUnit:
    unit_id: str
    book_id: str
    ordinal: int
    target_spans: tuple[SourceSpan, ...]
    context_before: tuple[SourceSpan, ...]
    context_after: tuple[SourceSpan, ...]

    @property
    def target_span_ids(self) -> tuple[str, ...]:
        return tuple(span.span_id for span in self.target_spans)

    @property
    def target_character_count(self) -> int:
        return sum(len(span.text) for span in self.target_spans)

    def audit_record(self) -> dict[str, Any]:
        first = self.target_spans[0]
        last = self.target_spans[-1]
        return {
            "unit_id": self.unit_id,
            "book_id": self.book_id,
            "ordinal": self.ordinal,
            "target_span_ids": list(self.target_span_ids),
            "context_before_span_ids": [span.span_id for span in self.context_before],
            "context_after_span_ids": [span.span_id for span in self.context_after],
            "target_character_count": self.target_character_count,
            "first_pdf_page_number": first.page_number,
            "last_pdf_page_number": last.page_number,
            "part_title": first.section.get("part_title"),
            "chapter_title": first.section.get("chapter_title"),
        }


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _JSONL_WRITE_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


def write_json(path: Path, value: Any, *, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2 if pretty else None)
        handle.write("\n")
    temporary.replace(path)


def load_book_input(directory: str | Path) -> BookInput:
    directory = Path(directory).expanduser().resolve()
    manifest_path = directory / "manifest.json"
    spans_path = directory / "extraction" / "spans.jsonl"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Book manifest not found: {manifest_path}")
    if not spans_path.is_file():
        raise FileNotFoundError(f"Source spans not found: {spans_path}")

    manifest = read_json(manifest_path)
    book_id = manifest.get("book_id")
    paragraphs: list[SourceSpan] = []
    seen_ids: set[str] = set()
    for record in iter_jsonl(spans_path):
        if record.get("span_type") != "paragraph" or not record.get("claim_eligible", False):
            continue
        span = SourceSpan.from_record(record)
        if span.book_id != book_id:
            raise ValueError(f"Span {span.span_id} belongs to {span.book_id}, expected {book_id}")
        if span.span_id in seen_ids:
            raise ValueError(f"Duplicate source span ID: {span.span_id}")
        if hashlib.sha256(span.text.encode("utf-8")).hexdigest() != span.text_sha256:
            raise ValueError(f"Source text hash mismatch for {span.span_id}")
        seen_ids.add(span.span_id)
        paragraphs.append(span)

    if not paragraphs:
        raise ValueError(f"No claim-eligible paragraph spans found in {spans_path}")
    return BookInput(directory=directory, manifest=manifest, spans=tuple(paragraphs))


def _chapter_key(span: SourceSpan) -> tuple[str | None, str | None]:
    return (span.section.get("part_title"), span.section.get("chapter_title"))


def _unit_id(book_id: str, ordinal: int, spans: Iterable[SourceSpan]) -> str:
    material = "\n".join(span.span_id for span in spans)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    short_book_id = book_id.removeprefix("book:")[:12]
    return f"unit:{short_book_id}:{ordinal:05d}:{digest}"


def build_claim_units(
    book: BookInput,
    *,
    max_target_characters: int,
    max_target_spans: int,
    context_spans_before: int,
    context_spans_after: int,
) -> list[ClaimUnit]:
    """Group paragraphs without crossing a chapter boundary.

    A paragraph larger than the character target remains intact in its own unit;
    splitting it would destroy the extractor's stable source-span contract.
    """

    if max_target_characters < 1 or max_target_spans < 1:
        raise ValueError("Unit character and span limits must be positive")

    grouped: list[list[SourceSpan]] = []
    current_chapter: tuple[str | None, str | None] | None = None
    chapter_spans: list[SourceSpan] = []
    for span in book.spans:
        key = _chapter_key(span)
        if chapter_spans and key != current_chapter:
            grouped.append(chapter_spans)
            chapter_spans = []
        chapter_spans.append(span)
        current_chapter = key
    if chapter_spans:
        grouped.append(chapter_spans)

    units: list[ClaimUnit] = []
    ordinal = 0
    for spans in grouped:
        start = 0
        while start < len(spans):
            end = start
            characters = 0
            while end < len(spans) and end - start < max_target_spans:
                candidate_size = len(spans[end].text)
                if end > start and characters + candidate_size > max_target_characters:
                    break
                characters += candidate_size
                end += 1
            target = tuple(spans[start:end])
            ordinal += 1
            units.append(
                ClaimUnit(
                    unit_id=_unit_id(book.book_id, ordinal, target),
                    book_id=book.book_id,
                    ordinal=ordinal,
                    target_spans=target,
                    context_before=tuple(spans[max(0, start - context_spans_before) : start]),
                    context_after=tuple(spans[end : end + context_spans_after]),
                )
            )
            start = end
    return units


def span_lookup(books: Iterable[BookInput]) -> dict[str, SourceSpan]:
    result: dict[str, SourceSpan] = {}
    for book in books:
        for span in book.spans:
            if span.span_id in result:
                raise ValueError(f"Duplicate span ID across books: {span.span_id}")
            result[span.span_id] = span
    return result
