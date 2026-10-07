"""Command-line entry point for the RNH claim pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from .io import build_claim_units, load_book_input
from .pipeline import ClaimPipeline, PipelineAssets, PipelineConfig
from .providers import OllamaProvider, OpenAIProvider
from .review import build_review_artifacts, validate_run


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPOSITORY_ROOT / "configs" / "claims" / "claim_pipeline_v1.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Source-grounded historical claim extraction")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Validate inputs and report planned model units")
    inspect_parser.add_argument("--book-dir", action="append", type=Path, required=True)
    inspect_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    run_parser = subparsers.add_parser("run", help="Run or resume model claim extraction")
    run_parser.add_argument("--book-dir", action="append", type=Path, required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run_parser.add_argument("--backend", choices=["ollama", "openai"], default="ollama")
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    run_parser.add_argument("--timeout-seconds", type=float, default=900)
    run_parser.add_argument("--context-length", type=int, default=16384)
    run_parser.add_argument("--condition", choices=["llm_zero_shot", "llm_few_shot", "hybrid_rule_guided_few_shot"])
    run_parser.add_argument("--max-retries", type=int, default=2)
    run_parser.add_argument("--workers", type=int, default=1)
    run_parser.add_argument("--limit-units-per-book", type=int)
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--sample-size-per-book", type=int, default=50)

    validate_parser = subparsers.add_parser("validate", help="Revalidate schemas and source offsets")
    validate_parser.add_argument("--run-dir", type=Path, required=True)

    report_parser = subparsers.add_parser("report", help="Regenerate JSON, CSV and Markdown review files")
    report_parser.add_argument("--run-dir", type=Path, required=True)
    report_parser.add_argument("--sample-size-per-book", type=int, default=50)
    return parser


def command_inspect(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_file(args.config)
    assets = PipelineAssets.from_repository(args.repository_root)
    _validate_assets(assets)
    result = []
    for directory in args.book_dir:
        book = load_book_input(directory)
        units = build_claim_units(
            book,
            max_target_characters=config.max_target_characters,
            max_target_spans=config.max_target_spans,
            context_spans_before=config.context_spans_before,
            context_spans_after=config.context_spans_after,
        )
        result.append(
            {
                **book.prompt_metadata(),
                "claim_eligible_paragraphs": len(book.spans),
                "planned_units": len(units),
                "target_characters": sum(unit.target_character_count for unit in units),
                "oversized_single_span_units": sum(
                    len(unit.target_spans) == 1 and unit.target_character_count > config.max_target_characters
                    for unit in units
                ),
            }
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_run(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_file(args.config)
    assets = PipelineAssets.from_repository(args.repository_root)
    _validate_assets(assets)
    if args.backend == "ollama":
        provider = OllamaProvider(
            args.model,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            context_length=args.context_length,
        )
    else:
        provider = OpenAIProvider(args.model, timeout_seconds=args.timeout_seconds)
    pipeline = ClaimPipeline(
        provider=provider,
        config=config,
        assets=assets,
        condition=args.condition,
        max_retries=args.max_retries,
        workers=args.workers,
    )
    summary = pipeline.run(
        book_directories=args.book_dir,
        output_directory=args.output_dir,
        resume=args.resume,
        limit_units_per_book=args.limit_units_per_book,
    )
    validation = validate_run(args.output_dir, assets)
    artifacts = build_review_artifacts(args.output_dir, sample_size_per_book=args.sample_size_per_book)
    print(json.dumps({"summary": summary, "validation": validation, "artifacts": {k: str(v) for k, v in artifacts.items()}}, indent=2))
    return 0 if validation["valid"] and summary["failed_units"] == 0 else 2


def command_validate(args: argparse.Namespace) -> int:
    assets = PipelineAssets.from_repository(args.repository_root)
    _validate_assets(assets)
    report = validate_run(args.run_dir, assets)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 2


def command_report(args: argparse.Namespace) -> int:
    artifacts = build_review_artifacts(args.run_dir, sample_size_per_book=args.sample_size_per_book)
    print(json.dumps({key: str(path) for key, path in artifacts.items()}, indent=2))
    return 0


def _validate_assets(assets: PipelineAssets) -> None:
    Draft202012Validator.check_schema(assets.response_schema)
    Draft202012Validator.check_schema(assets.claim_schema)
    Draft202012Validator.check_schema(assets.frame_schema)
    response_validator = Draft202012Validator(assets.response_schema)
    errors = []
    for example in assets.examples:
        for error in response_validator.iter_errors(example["response"]):
            errors.append(f"{example.get('name')}: {error.json_path}: {error.message}")
    if errors:
        raise ValueError("Few-shot examples fail the response schema: " + "; ".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "inspect": command_inspect,
        "run": command_run,
        "validate": command_validate,
        "report": command_report,
    }
    try:
        return commands[args.command](args)
    except KeyboardInterrupt:
        print("Interrupted; completed units remain resumable with --resume.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
