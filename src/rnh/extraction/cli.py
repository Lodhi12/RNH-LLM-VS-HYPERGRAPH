"""Command-line interface for the bundled PDF extractor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .extraction import ExtractionConfig, extract_pdf
from .schema_validation import validate_book
from .verification import verify_extraction


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "private" / "books"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rnh-bookpipe",
        description="Extract a PDF into traceable pages, blocks, spans, structure, and images.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="Extract and validate one PDF")
    extract.add_argument("pdf", type=Path)
    extract.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    extract.add_argument("--ocr", choices=("auto", "on", "off"), default="auto")
    extract.add_argument("--ocr-language", default="eng")
    extract.add_argument("--ocr-dpi", type=int, default=220)
    extract.add_argument("--min-text-chars", type=int, default=80)
    extract.add_argument("--no-blocks", action="store_true")
    extract.add_argument("--no-images", action="store_true")
    extract.add_argument("--min-image-bytes", type=int, default=512)
    extract.add_argument("--title")
    extract.add_argument("--author")
    extract.add_argument("--publication-year", type=int)
    extract.add_argument("--language")
    extract.add_argument("--overwrite", action="store_true")

    verify = commands.add_parser("verify", help="Check extraction integrity and provenance")
    verify.add_argument("book_dir", type=Path)

    validate = commands.add_parser("validate", help="Validate extraction records against JSON Schema")
    validate.add_argument("book_dir", type=Path)
    validate.add_argument("--max-errors", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            config = ExtractionConfig(
                ocr_mode=args.ocr,
                ocr_language=args.ocr_language,
                ocr_dpi=args.ocr_dpi,
                min_text_chars=args.min_text_chars,
                include_blocks=not args.no_blocks,
                extract_images=not args.no_images,
                min_image_bytes=args.min_image_bytes,
                title=args.title,
                author=args.author,
                publication_year=args.publication_year,
                language=args.language,
            )
            book_dir = extract_pdf(args.pdf, args.output, config, PROJECT_ROOT, args.overwrite)
            integrity = verify_extraction(book_dir)
            schema = validate_book(PROJECT_ROOT, book_dir, max_errors=100)
            if integrity["status"] != "pass" or schema["status"] != "pass":
                raise RuntimeError("Extraction completed, but integrity or schema validation failed")
            print(book_dir)
            return 0

        if args.command == "verify":
            report = verify_extraction(args.book_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "pass" else 1

        report = validate_book(PROJECT_ROOT, args.book_dir, max_errors=args.max_errors)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "pass" else 1
    except (FileExistsError, FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
