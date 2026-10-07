"""Orchestrate PDF extraction and source-grounded claim extraction.

The master runner delegates PDF processing to the bundled, versioned
``rnh-bookpipe`` executable and claim processing to this package's
``rnh-claims`` CLI. It records the exact commands and paths without combining
their separate provenance models.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = REPOSITORY_ROOT / "schemas" / "master_pipeline_config.schema.json"


class MasterPipelineError(RuntimeError):
    """Raised when a master run cannot proceed without compromising provenance."""


@dataclass(frozen=True)
class MasterConfig:
    path: Path
    raw: dict[str, Any]
    workspace_root: Path
    extractor_command: tuple[str, ...]
    extraction_output_root: Path
    claim_output_dir: Path
    books: tuple[dict[str, Any], ...]

    @property
    def state_path(self) -> Path:
        return self.claim_output_dir.parent / f".{self.claim_output_dir.name}.master-state.json"

    @property
    def log_directory(self) -> Path:
        return self.claim_output_dir.parent / f".{self.claim_output_dir.name}.master-logs"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MasterPipelineError(f"Expected a JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _resolve_path(workspace: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return candidate.resolve()


def _resolve_executable(workspace: Path, value: str, *, require_exists: bool) -> str:
    if os.sep not in value and (os.altsep is None or os.altsep not in value):
        resolved = shutil.which(value)
        if resolved:
            return resolved
        if require_exists:
            raise MasterPipelineError(f"Extractor executable is not on PATH: {value}")
        return value
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    # Preserve virtual-environment interpreter symlinks. Resolving the symlink
    # to /usr/bin/python would discard the environment's package context.
    path = Path(os.path.abspath(candidate))
    if require_exists and (not path.is_file() or not os.access(path, os.X_OK)):
        raise MasterPipelineError(f"Extractor executable is missing or not executable: {path}")
    return str(path)


def _resolve_command(workspace: Path, values: list[str], *, require_exists: bool) -> tuple[str, ...]:
    executable = _resolve_executable(workspace, values[0], require_exists=require_exists)
    return (executable, *values[1:])


def load_master_config(
    config_path: str | Path,
    *,
    schema_path: str | Path = DEFAULT_SCHEMA,
    require_inputs: bool = True,
) -> MasterConfig:
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise MasterPipelineError(f"Master configuration not found: {path}")
    raw = read_json(path)
    schema = read_json(Path(schema_path).expanduser().resolve())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(raw), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(f"{error.json_path}: {error.message}" for error in errors[:20])
        raise MasterPipelineError(f"Master configuration is invalid: {details}")

    workspace_value = Path(raw["workspace_root"]).expanduser()
    if not workspace_value.is_absolute():
        workspace_value = path.parent / workspace_value
    workspace = workspace_value.resolve()
    if require_inputs and not workspace.is_dir():
        raise MasterPipelineError(f"Workspace root does not exist: {workspace}")

    extractor_command = _resolve_command(
        workspace,
        raw["extractor"]["command"],
        require_exists=require_inputs,
    )
    extraction_output = _resolve_path(workspace, raw["extractor"]["output_root"])
    claim_output = _resolve_path(workspace, raw["claims"]["output_dir"])

    if raw["claims"]["backend"] == "openai" and not raw["data_handling"]["external_api_allowed"]:
        raise MasterPipelineError(
            "claims.backend is openai but data_handling.external_api_allowed is false; "
            "source passages must not be sent externally without explicit approval"
        )

    resolved_books: list[dict[str, Any]] = []
    for index, book in enumerate(raw["books"], start=1):
        resolved = dict(book)
        if "pdf" in book:
            resolved["pdf"] = str(_resolve_path(workspace, book["pdf"]))
            if require_inputs and not Path(resolved["pdf"]).is_file():
                raise MasterPipelineError(f"Book {index} PDF does not exist: {resolved['pdf']}")
        else:
            resolved["book_dir"] = str(_resolve_path(workspace, book["book_dir"]))
            if require_inputs:
                validate_extracted_book(Path(resolved["book_dir"]))
        resolved_books.append(resolved)

    return MasterConfig(
        path=path,
        raw=raw,
        workspace_root=workspace,
        extractor_command=extractor_command,
        extraction_output_root=extraction_output,
        claim_output_dir=claim_output,
        books=tuple(resolved_books),
    )


def validate_extracted_book(book_directory: Path) -> dict[str, Any]:
    directory = book_directory.expanduser().resolve()
    manifest_path = directory / "manifest.json"
    spans_path = directory / "extraction" / "spans.jsonl"
    if not manifest_path.is_file():
        raise MasterPipelineError(f"Extraction manifest is missing: {manifest_path}")
    if not spans_path.is_file():
        raise MasterPipelineError(f"Extraction spans are missing: {spans_path}")
    manifest = read_json(manifest_path)
    if not manifest.get("book_id"):
        raise MasterPipelineError(f"Extraction manifest has no book_id: {manifest_path}")
    source_hash = manifest.get("source", {}).get("sha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise MasterPipelineError(f"Extraction manifest has no valid source SHA-256: {manifest_path}")
    return manifest


def find_extraction_by_hash(output_root: Path, source_sha256: str) -> Path | None:
    if not output_root.is_dir():
        return None
    matches: list[Path] = []
    for manifest_path in output_root.glob("*/manifest.json"):
        try:
            manifest = read_json(manifest_path)
        except (OSError, json.JSONDecodeError, MasterPipelineError):
            continue
        if manifest.get("source", {}).get("sha256") == source_sha256:
            matches.append(manifest_path.parent.resolve())
    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches)
        raise MasterPipelineError(f"Multiple extraction directories have source hash {source_sha256}: {joined}")
    return matches[0] if matches else None


def build_extraction_command(config: MasterConfig, book: dict[str, Any]) -> list[str]:
    settings = config.raw["extractor"]
    command = [
        *config.extractor_command,
        "extract",
        book["pdf"],
        "--output",
        str(config.extraction_output_root),
        "--ocr",
        settings["ocr_mode"],
        "--ocr-language",
        settings["ocr_language"],
        "--ocr-dpi",
        str(settings["ocr_dpi"]),
        "--min-text-chars",
        str(settings["min_text_chars"]),
        "--min-image-bytes",
        str(settings["min_image_bytes"]),
    ]
    if not settings["include_blocks"]:
        command.append("--no-blocks")
    if not settings["include_images"]:
        command.append("--no-images")
    optional_flags = {
        "title": "--title",
        "author": "--author",
        "publication_year": "--publication-year",
        "language": "--language",
    }
    for key, flag in optional_flags.items():
        if key in book:
            command.extend([flag, str(book[key])])
    return command


def build_claim_command(config: MasterConfig, book_directories: Iterable[Path], *, resume: bool) -> list[str]:
    settings = config.raw["claims"]
    command = [
        sys.executable,
        "-m",
        "rnh.claims.cli",
        "--repository-root",
        str(REPOSITORY_ROOT),
        "run",
        "--output-dir",
        str(config.claim_output_dir),
        "--backend",
        settings["backend"],
        "--model",
        settings["model"],
        "--base-url",
        settings["base_url"],
        "--timeout-seconds",
        str(settings["timeout_seconds"]),
        "--context-length",
        str(settings["context_length"]),
        "--condition",
        settings["condition"],
        "--max-retries",
        str(settings["max_retries"]),
        "--workers",
        str(settings["workers"]),
        "--sample-size-per-book",
        str(settings["sample_size_per_book"]),
    ]
    for directory in book_directories:
        command.extend(["--book-dir", str(directory.resolve())])
    if settings.get("limit_units_per_book") is not None:
        command.extend(["--limit-units-per-book", str(settings["limit_units_per_book"])])
    if resume:
        command.append("--resume")
    return command


def build_extraction_validation_commands(config: MasterConfig, book_directory: Path) -> list[list[str]]:
    directory = str(book_directory.resolve())
    return [
        [*config.extractor_command, "verify", directory],
        [*config.extractor_command, "validate", directory],
    ]


def _validation_command(config: MasterConfig) -> list[str]:
    return [
        sys.executable,
        "-m",
        "rnh.claims.cli",
        "--repository-root",
        str(REPOSITORY_ROOT),
        "validate",
        "--run-dir",
        str(config.claim_output_dir),
    ]


def _report_command(config: MasterConfig) -> list[str]:
    return [
        sys.executable,
        "-m",
        "rnh.claims.cli",
        "--repository-root",
        str(REPOSITORY_ROOT),
        "report",
        "--run-dir",
        str(config.claim_output_dir),
        "--sample-size-per-book",
        str(config.raw["claims"]["sample_size_per_book"]),
    ]


def command_string(command: Iterable[str]) -> str:
    return shlex.join(list(command))


def run_logged(command: list[str], *, cwd: Path, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"$ {command_string(command)}", flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{utc_now()}] $ {command_string(command)}\n")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            return_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if return_code:
        raise MasterPipelineError(
            f"Command failed with exit code {return_code}; inspect {log_path}: {command_string(command)}"
        )


def resolve_book_directories(config: MasterConfig, *, execute: bool) -> tuple[list[Path], list[dict[str, Any]]]:
    directories: list[Path] = []
    plan: list[dict[str, Any]] = []
    for index, book in enumerate(config.books, start=1):
        if "book_dir" in book:
            directory = Path(book["book_dir"]).resolve()
            manifest = validate_extracted_book(directory)
            directories.append(directory)
            plan.append(
                {
                    "book_number": index,
                    "action": "reuse_declared_extraction",
                    "book_dir": str(directory),
                    "book_id": manifest.get("book_id"),
                }
            )
            continue

        pdf = Path(book["pdf"]).resolve()
        if not pdf.is_file():
            raise MasterPipelineError(f"PDF does not exist: {pdf}")
        source_hash = sha256_file(pdf)
        existing = find_extraction_by_hash(config.extraction_output_root, source_hash)
        if existing:
            validate_extracted_book(existing)
            directories.append(existing)
            plan.append(
                {
                    "book_number": index,
                    "action": "reuse_hash_matched_extraction",
                    "pdf": str(pdf),
                    "source_sha256": source_hash,
                    "book_dir": str(existing),
                }
            )
            continue

        extract_command = build_extraction_command(config, book)
        plan.append(
            {
                "book_number": index,
                "action": "extract_pdf",
                "pdf": str(pdf),
                "source_sha256": source_hash,
                "command": extract_command,
            }
        )
        if not execute:
            continue
        log_path = config.log_directory / f"01-extract-book-{index:03d}.log"
        run_logged(extract_command, cwd=config.workspace_root, log_path=log_path)
        extracted = find_extraction_by_hash(config.extraction_output_root, source_hash)
        if not extracted:
            raise MasterPipelineError(
                f"Extractor completed but no manifest with source hash {source_hash} was found under "
                f"{config.extraction_output_root}"
            )
        validate_extracted_book(extracted)
        directories.append(extracted)
        plan[-1]["book_dir"] = str(extracted)
    return directories, plan


def build_plan(config: MasterConfig) -> dict[str, Any]:
    book_directories, books = resolve_book_directories(config, execute=False)
    claim_command = None
    extraction_validation_commands: list[list[str]] = []
    if len(book_directories) == len(config.books):
        extraction_validation_commands = [
            command
            for directory in book_directories
            for command in build_extraction_validation_commands(config, directory)
        ]
        claim_command = build_claim_command(
            config,
            book_directories,
            resume=(config.claim_output_dir / "run.json").is_file(),
        )
    return {
        "schema_version": "1.0.0",
        "project_id": config.raw["project_id"],
        "configuration": str(config.path),
        "configuration_sha256": canonical_sha256(config.raw),
        "workspace_root": str(config.workspace_root),
        "books": books,
        "extraction_validation_commands": extraction_validation_commands,
        "claim_output_dir": str(config.claim_output_dir),
        "claim_command": claim_command,
        "note": (
            "Claim command is available only when every extraction directory already exists. "
            "The run command resolves newly created directories after extraction."
        ),
    }


def summarize_claim_progress(run_directory: Path) -> dict[str, Any] | None:
    run_path = run_directory / "run.json"
    if not run_path.is_file():
        return None
    run = read_json(run_path)
    statuses: Counter[str] = Counter()
    processed = claims = frames = rejected = 0
    last_unit_id: str | None = None
    units_path = run_directory / "units.jsonl"
    if units_path.is_file():
        with units_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    unit = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise MasterPipelineError(
                        f"Invalid JSON in {units_path} at line {line_number}: {exc}"
                    ) from exc
                processed += 1
                statuses[str(unit.get("status", "unknown"))] += 1
                claims += int(unit.get("claim_count", 0))
                frames += int(unit.get("frame_count", 0))
                rejected += int(unit.get("rejected_count", 0))
                last_unit_id = unit.get("unit_id")
    planned = run.get("planned_unit_count")
    progress_percent = round(processed * 100 / planned, 2) if isinstance(planned, int) and planned else None
    return {
        "run_status": run.get("status"),
        "planned_units": planned,
        "processed_units": processed,
        "progress_percent": progress_percent,
        "unit_statuses": dict(sorted(statuses.items())),
        "grounded_claim_candidates": claims,
        "frame_candidates": frames,
        "rejected_candidates": rejected,
        "last_unit_id": last_unit_id,
    }


def run_master(config: MasterConfig, *, resume: bool) -> dict[str, Any]:
    if config.claim_output_dir.exists() and not config.claim_output_dir.is_dir():
        raise MasterPipelineError(f"Claim output path is not a directory: {config.claim_output_dir}")
    if config.claim_output_dir.is_dir() and any(config.claim_output_dir.iterdir()):
        if not resume:
            raise MasterPipelineError(
                f"Claim output is not empty: {config.claim_output_dir}. Use --resume only for the same versioned run."
            )
        if not (config.claim_output_dir / "run.json").is_file():
            raise MasterPipelineError(
                f"Cannot resume because run.json is missing from non-empty output: {config.claim_output_dir}"
            )

    state: dict[str, Any] = {
        "schema_version": "1.0.0",
        "project_id": config.raw["project_id"],
        "configuration": str(config.path),
        "configuration_sha256": canonical_sha256(config.raw),
        "started_at": utc_now(),
        "status": "running",
        "resume_requested": resume,
        "data_handling": config.raw["data_handling"],
        "stages": [],
    }
    write_json(config.state_path, state)

    try:
        book_directories, extraction_plan = resolve_book_directories(config, execute=True)
        state["stages"].append(
            {
                "name": "extraction",
                "status": "complete",
                "finished_at": utc_now(),
                "books": extraction_plan,
            }
        )
        state["book_directories"] = [str(path) for path in book_directories]
        write_json(config.state_path, state)

        extraction_validation_commands: list[list[str]] = []
        for index, directory in enumerate(book_directories, start=1):
            for validation_index, command in enumerate(
                build_extraction_validation_commands(config, directory), start=1
            ):
                extraction_validation_commands.append(command)
                run_logged(
                    command,
                    cwd=config.workspace_root,
                    log_path=config.log_directory
                    / f"01b-validate-extraction-{index:03d}-{validation_index}.log",
                )
        state["stages"].append(
            {
                "name": "extraction_validation",
                "status": "complete",
                "finished_at": utc_now(),
                "commands": extraction_validation_commands,
            }
        )
        write_json(config.state_path, state)

        claim_command = build_claim_command(config, book_directories, resume=resume)
        state["stages"].append(
            {
                "name": "claim_extraction",
                "status": "running",
                "started_at": utc_now(),
                "command": claim_command,
            }
        )
        write_json(config.state_path, state)
        run_logged(claim_command, cwd=REPOSITORY_ROOT, log_path=config.log_directory / "02-claims.log")
        state["stages"][-1]["status"] = "complete"
        state["stages"][-1]["finished_at"] = utc_now()
        write_json(config.state_path, state)

        validation_command = _validation_command(config)
        run_logged(validation_command, cwd=REPOSITORY_ROOT, log_path=config.log_directory / "03-validation.log")
        state["stages"].append(
            {
                "name": "deterministic_validation",
                "status": "complete",
                "finished_at": utc_now(),
                "command": validation_command,
            }
        )
        write_json(config.state_path, state)

        report_command = _report_command(config)
        run_logged(report_command, cwd=REPOSITORY_ROOT, log_path=config.log_directory / "04-report.log")
        state["stages"].append(
            {
                "name": "review_artifacts",
                "status": "complete",
                "finished_at": utc_now(),
                "command": report_command,
            }
        )
        state["status"] = "machine_complete_human_review_pending"
        state["finished_at"] = utc_now()
        state["claim_output_dir"] = str(config.claim_output_dir)
        write_json(config.state_path, state)
        return state
    except BaseException as exc:
        state["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        state["finished_at"] = utc_now()
        state["error"] = f"{type(exc).__name__}: {exc}"
        write_json(config.state_path, state)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rnh-pipeline",
        description="End-to-end PDF extraction and grounded historical-claim orchestration",
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Validate configuration and show the intended stages")
    plan.add_argument("config", type=Path)

    run = subparsers.add_parser("run", help="Extract sources, generate claims, validate, and create review files")
    run.add_argument("config", type=Path)
    run.add_argument("--resume", action="store_true")

    status = subparsers.add_parser("status", help="Show the master state associated with a configuration")
    status.add_argument("config", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_master_config(
            args.config,
            schema_path=args.schema,
            require_inputs=args.command != "status",
        )
        if args.command == "plan":
            print(json.dumps(build_plan(config), ensure_ascii=False, indent=2))
        elif args.command == "run":
            result = run_master(config, resume=args.resume)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "status":
            if not config.state_path.is_file():
                raise MasterPipelineError(f"No master state exists yet: {config.state_path}")
            state = read_json(config.state_path)
            state["claim_progress"] = summarize_claim_progress(config.claim_output_dir)
            print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("Interrupted; completed claim units remain resumable with --resume.", file=sys.stderr)
        return 130
    except (OSError, json.JSONDecodeError, MasterPipelineError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
