from pathlib import Path

import pymupdf

from rnh.extraction.extraction import ExtractionConfig, extract_pdf
from rnh.extraction.io_utils import read_json, read_jsonl
from rnh.extraction.schema_validation import validate_book
from rnh.extraction.structure import context_for_page
from rnh.extraction.verification import verify_extraction


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_extractor_produces_traceable_valid_records(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "The committee announced the agreement in Dhaka on 15 March 1971.",
    )
    document.set_toc([[1, "Chapter 1", 1]])
    document.set_metadata({"title": "Sample History", "author": "Test Author"})
    document.save(pdf_path)
    document.close()

    book_dir = extract_pdf(
        pdf_path,
        tmp_path / "books",
        ExtractionConfig(ocr_mode="off", extract_images=False),
        REPOSITORY_ROOT,
    )

    integrity = verify_extraction(book_dir)
    schema = validate_book(REPOSITORY_ROOT, book_dir)
    manifest = read_json(book_dir / "manifest.json")
    pages = list(read_jsonl(book_dir / "extraction" / "pages.jsonl"))
    spans = list(read_jsonl(book_dir / "extraction" / "spans.jsonl"))

    assert integrity["status"] == "pass"
    assert schema["status"] == "pass"
    assert manifest["pipeline"]["name"] == "rnh_research_pipeline"
    assert pages[0]["extraction"]["method"] == "native"
    assert any(span["span_type"] == "paragraph" for span in spans)
    assert all(
        pages[0]["text"]["normalized"][span["page_char_start"] : span["page_char_end"]]
        == span["text"]
        for span in spans
    )


def test_document_without_toc_remains_claim_eligible() -> None:
    section = context_for_page(1, [])

    assert section["section_id"] == "section:unstructured-body"
    assert section["section_kind"] == "body_unstructured"
    assert section["claim_eligible"] is True


def test_extractor_validates_document_without_toc(tmp_path: Path) -> None:
    pdf_path = tmp_path / "unstructured.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "The witness reported that the meeting occurred in Dhaka.")
    document.save(pdf_path)
    document.close()

    book_dir = extract_pdf(
        pdf_path,
        tmp_path / "books",
        ExtractionConfig(ocr_mode="off", extract_images=False),
        REPOSITORY_ROOT,
    )

    structure = read_json(book_dir / "extraction" / "structure.json")
    schema = validate_book(REPOSITORY_ROOT, book_dir)
    spans = list(read_jsonl(book_dir / "extraction" / "spans.jsonl"))

    assert structure["method"] == "fallback_unstructured_body"
    assert schema["status"] == "pass"
    assert all(span["claim_eligible"] for span in spans)
