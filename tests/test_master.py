from __future__ import annotations

import json
from pathlib import Path

import pytest

from rnh.master import (
    MasterPipelineError,
    build_claim_command,
    build_extraction_validation_commands,
    find_extraction_by_hash,
    load_master_config,
    summarize_claim_progress,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _book_directory(root: Path, digest: str = "a" * 64) -> Path:
    directory = root / "book-a"
    (directory / "extraction").mkdir(parents=True)
    _write_json(
        directory / "manifest.json",
        {
            "book_id": "book:test",
            "source": {"sha256": digest},
            "book": {"title": "Test Book"},
        },
    )
    (directory / "extraction" / "spans.jsonl").write_text("", encoding="utf-8")
    return directory


def _configuration(workspace: Path, book_directory: Path) -> dict:
    executable = workspace / "python-for-bookpipe"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return {
        "schema_version": "1.0.0",
        "project_id": "test-project",
        "workspace_root": str(workspace),
        "data_handling": {
            "external_api_allowed": False,
            "redistribution_allowed": False,
        },
        "extractor": {
            "command": [str(executable), "-m", "book_pipeline.cli"],
            "output_root": "extractions",
            "ocr_mode": "auto",
            "ocr_language": "eng",
            "ocr_dpi": 220,
            "min_text_chars": 80,
            "include_blocks": True,
            "include_images": True,
            "min_image_bytes": 512,
        },
        "books": [
            {
                "book_dir": str(book_directory),
                "rights_status": "private_research",
            }
        ],
        "claims": {
            "output_dir": "claims/run-one",
            "backend": "ollama",
            "model": "example:latest",
            "condition": "llm_few_shot",
            "base_url": "http://127.0.0.1:11434",
            "timeout_seconds": 900,
            "context_length": 16384,
            "max_retries": 2,
            "workers": 1,
            "sample_size_per_book": 20,
            "limit_units_per_book": None,
        },
    }


def test_master_config_resolves_paths_and_builds_claim_command(tmp_path: Path) -> None:
    book_directory = _book_directory(tmp_path / "books")
    config_path = tmp_path / "master.json"
    _write_json(config_path, _configuration(tmp_path, book_directory))

    config = load_master_config(config_path)
    command = build_claim_command(config, [book_directory], resume=True)

    assert config.claim_output_dir == (tmp_path / "claims" / "run-one").resolve()
    assert command[-1] == "--resume"
    assert "--book-dir" in command
    assert str(book_directory.resolve()) in command
    assert "example:latest" in command

    validation_commands = build_extraction_validation_commands(config, book_directory)
    assert validation_commands == [
        [
            str((tmp_path / "python-for-bookpipe").resolve()),
            "-m",
            "book_pipeline.cli",
            "verify",
            str(book_directory.resolve()),
        ],
        [
            str((tmp_path / "python-for-bookpipe").resolve()),
            "-m",
            "book_pipeline.cli",
            "validate",
            str(book_directory.resolve()),
        ],
    ]


def test_checked_example_uses_the_bundled_extractor() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = load_master_config(
        repository_root / "configs" / "master_pipeline.example.json",
        require_inputs=False,
    )

    assert config.extractor_command == (
        str(repository_root / ".venv" / "bin" / "rnh-bookpipe"),
    )


def test_openai_requires_explicit_external_api_approval(tmp_path: Path) -> None:
    book_directory = _book_directory(tmp_path / "books")
    raw = _configuration(tmp_path, book_directory)
    raw["claims"]["backend"] = "openai"
    raw["claims"]["model"] = "example-openai-model"
    config_path = tmp_path / "master.json"
    _write_json(config_path, raw)

    with pytest.raises(MasterPipelineError, match="external_api_allowed is false"):
        load_master_config(config_path)


def test_existing_extraction_is_selected_by_full_source_hash(tmp_path: Path) -> None:
    digest = "b" * 64
    expected = _book_directory(tmp_path, digest)

    assert find_extraction_by_hash(tmp_path, digest) == expected.resolve()
    assert find_extraction_by_hash(tmp_path, "c" * 64) is None


def test_book_source_must_be_pdf_or_extraction_not_both(tmp_path: Path) -> None:
    book_directory = _book_directory(tmp_path / "books")
    raw = _configuration(tmp_path, book_directory)
    raw["books"][0]["pdf"] = str(tmp_path / "also.pdf")
    config_path = tmp_path / "master.json"
    _write_json(config_path, raw)

    with pytest.raises(MasterPipelineError, match="Master configuration is invalid"):
        load_master_config(config_path, require_inputs=False)


def test_virtual_environment_python_symlink_is_not_resolved_away(tmp_path: Path) -> None:
    book_directory = _book_directory(tmp_path / "books")
    real_python = tmp_path / "real-python"
    real_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    real_python.chmod(0o755)
    linked_python = tmp_path / "venv-python"
    linked_python.symlink_to(real_python)

    raw = _configuration(tmp_path, book_directory)
    raw["extractor"]["command"][0] = str(linked_python)
    config_path = tmp_path / "master.json"
    _write_json(config_path, raw)

    config = load_master_config(config_path)

    assert config.extractor_command[0] == str(linked_python)


def test_live_claim_progress_is_summarized_from_unit_ledger(tmp_path: Path) -> None:
    run_directory = tmp_path / "run"
    _write_json(run_directory / "run.json", {"status": "running", "planned_unit_count": 4})
    units = [
        {"unit_id": "unit:1", "status": "complete", "claim_count": 3, "frame_count": 1, "rejected_count": 0},
        {"unit_id": "unit:2", "status": "failed", "claim_count": 0, "frame_count": 0, "rejected_count": 2},
    ]
    (run_directory / "units.jsonl").write_text(
        "".join(json.dumps(unit) + "\n" for unit in units), encoding="utf-8"
    )

    progress = summarize_claim_progress(run_directory)

    assert progress is not None
    assert progress["processed_units"] == 2
    assert progress["progress_percent"] == 50.0
    assert progress["unit_statuses"] == {"complete": 1, "failed": 1}
    assert progress["grounded_claim_candidates"] == 3
    assert progress["rejected_candidates"] == 2
