# Code And Data Map

This guide traces the RNH pipeline from a command entered in a terminal to the
files written on disk. Paths are relative to the repository root unless an
absolute path is shown.

## 1. Three Installed Commands

The command names are registered in `pyproject.toml`:

| Command | Python entry point | Responsibility |
| --- | --- | --- |
| `rnh-bookpipe` | `rnh.extraction.cli:main` | PDF extraction and extraction validation |
| `rnh-claims` | `rnh.claims.cli:main` | Claim-unit planning, LLM calls, grounding, validation, and reports |
| `rnh-pipeline` | `rnh.master:main` | Runs the extractor and claim pipeline in the correct order |

`rnh-pipeline` is the normal command for a complete experiment. The other two
commands expose individual stages for testing and diagnosis.

## 2. End-To-End Call Path

```text
rnh-pipeline run CONFIG
  |
  `-- src/rnh/master.py: main()
        |
        |-- load_master_config()
        |     `-- validate CONFIG against master_pipeline_config.schema.json
        |
        |-- resolve_book_directories()
        |     |-- hash each source PDF
        |     |-- reuse extraction with the same full hash, if present
        |     `-- otherwise invoke:
        |           python -m rnh.extraction.cli extract PDF ...
        |
        |-- invoke rnh-bookpipe verify BOOK_DIR
        |-- invoke rnh-bookpipe validate BOOK_DIR
        |
        |-- invoke python -m rnh.claims.cli run ...
        |     |-- load manifest.json and extraction/spans.jsonl
        |     |-- build chapter-aware paragraph units
        |     |-- construct versioned prompts
        |     |-- POST each unit to local Ollama
        |     |-- parse schema-constrained JSON
        |     |-- ground quotations and semantic surface forms
        |     `-- checkpoint claims, frames, rejections, and units
        |
        |-- invoke rnh-claims validate
        `-- invoke rnh-claims report
```

Claims therefore happen only after extraction, extraction integrity checks,
and extraction schema validation.

## 3. Root Files

### `pyproject.toml`

Python package definition. It specifies:

- Python 3.11 or newer;
- runtime dependencies: PyMuPDF and JSON Schema;
- optional OpenAI and development dependencies; and
- the three terminal command entry points.

Input: package installation command.  
Output: an installed editable Python package and CLI launchers in `.venv`.

### `.gitignore`

Prevents private or generated material from being committed, including PDFs,
`data/private/`, model weights, local virtual environments, local configs, and
credentials.

### `README.md`

Project overview, quick-start commands, research definitions, evaluation
principles, and links to detailed protocols.

## 4. Configuration Files

### `configs/master_pipeline.example.json`

The user-facing template for one complete run.

It supplies:

- project/run name;
- data-sharing policy;
- PDF extraction settings;
- one or more PDF paths or existing extraction directories;
- reviewed book metadata;
- Ollama/OpenAI model settings;
- output location; and
- optional pilot unit limit.

It does not contain prompt text or source text. Copy it to a filename ending in
`.local.json`, then edit that ignored copy.

### `configs/claims/claim_pipeline_v1.json`

Controls claim-unit and model behavior:

- prompt and annotation-guide versions;
- paragraph span type;
- maximum target characters and spans per model unit;
- neighboring context counts;
- maximum claims per response;
- number of passes;
- temperature; and
- truth/frame policy labels.

This file is part of experiment provenance. Changing it creates a different
experimental condition.

### `configs/claims/entman_frame_functions_v0.1.json`

Stores the provisional framing functions and their definitions. It is not a
list of historically true events and it is not a final supervisor-approved
codebook. Frame candidates remain separate from claims.

## 5. Prompt Files

### `prompts/claim_extraction_v1.md`

The base system instruction sent to the claim model. It defines a claim,
atomicity, evidence restrictions, attribution, polarity, uncertainty,
participants, and exclusions.

### `prompts/claim_examples_v1.json`

Synthetic worked examples used in `llm_few_shot` and
`hybrid_rule_guided_few_shot` conditions. These demonstrate the required
input/output behavior without copying a target book.

The prompt and examples are loaded once per run. Their hashes and versions are
recorded in `run.json`.

## 6. Extraction Source Code

### `src/rnh/extraction/cli.py`

Command-line boundary for extraction.

Inputs:

- command: `extract`, `verify`, or `validate`;
- PDF or extracted-book directory;
- OCR, image, metadata, and output options.

Work:

- converts command-line values into `ExtractionConfig`;
- calls `extract_pdf()`;
- automatically calls integrity and schema validation after extraction; and
- returns a non-zero exit code when validation fails.

Output: generated book directory or a JSON validation report.

### `src/rnh/extraction/extraction.py`

The main PDF extraction engine.

Inputs:

- source PDF path;
- output root;
- `ExtractionConfig`;
- repository root containing schemas/Tesseract data; and
- overwrite policy.

Work:

1. Computes the full PDF SHA-256 and stable `book_id`.
2. Opens the PDF with PyMuPDF.
3. Reads PDF metadata and bookmarks.
4. Processes every physical page.
5. Reads selectable text with PyMuPDF.
6. Calls Tesseract when OCR mode requires it.
7. Records page geometry, method, counts, confidence, and quality flags.
8. Extracts native text blocks and bounding boxes.
9. Extracts and hashes embedded raster-image occurrences.
10. Builds paragraph and sentence spans with exact page offsets.
11. Maps bookmark-derived structure to pages and spans.
12. Writes the extraction dataset and summary.

Outputs:

```text
manifest.json
run_local.json
extraction/pages.jsonl
extraction/blocks.jsonl
extraction/spans.jsonl
extraction/structure.json
media/images.jsonl
media/images/*
reports/extraction_summary.json
```

### `src/rnh/extraction/text.py`

Deterministic text utilities:

- conservative whitespace/newline normalization;
- paragraph boundaries;
- sentence boundaries;
- offset trimming; and
- word counts.

It does not use an LLM. Offsets returned here must reproduce the stored span
text exactly from the normalized page text.

### `src/rnh/extraction/structure.py`

Normalizes PDF bookmarks, builds section ranges, and assigns structural context
to each page.

It also uses explicit title patterns to mark sections such as contents, index,
bibliography, notes, acknowledgements, promotional pages, title pages, and
dedications as non-content. Ordinary body chapters and appendices remain claim
eligible.

This is a deterministic baseline. If a PDF has missing or incorrect bookmarks,
its inferred chapter mapping needs human correction.

### `src/rnh/extraction/io_utils.py`

Shared extraction utilities for:

- SHA-256 hashing;
- stable IDs and safe directory names;
- JSON/JSONL reading;
- atomic file replacement; and
- timestamp generation.

Atomic writes prevent a partially written JSON file from appearing complete.

### `src/rnh/extraction/verification.py`

Reopens the generated extraction and checks referential integrity:

- page sequence and uniqueness;
- text hashes and counts;
- span text against page offsets;
- sentence-to-paragraph parent links;
- block-to-page links;
- image file hashes;
- section ranges; and
- original PDF hash when the source remains locally available.

It writes `reports/extraction_verification.json`.

### `src/rnh/extraction/schema_validation.py`

Loads extraction JSON Schemas and validates the manifest, every page, every
span, every block, document structure, and every image occurrence. It writes
`reports/schema_validation.json`.

## 7. Extraction Schemas

| Path | Record validated |
| --- | --- |
| `schemas/book_extraction_v2.schema.json` | Top-level `manifest.json` |
| `schemas/page_v2.schema.json` | One physical PDF page |
| `schemas/text_block_v2.schema.json` | One layout text block |
| `schemas/source_span_v2.schema.json` | One paragraph or sentence span |
| `schemas/book_structure_v2.schema.json` | TOC and section ranges |
| `schemas/image_occurrence_v2.schema.json` | One image occurrence on one page |

A schema checks shape, required fields, types, and controlled values. It does
not check historical truth or OCR accuracy.

## 8. Extraction Output Files

### `<book-dir>/manifest.json`

The identity and inventory of one extracted source:

- stable book ID;
- title, creators, year, language, page count, and original PDF metadata;
- source filename, size, MIME type, and SHA-256;
- extractor name/version and configuration; and
- relative paths to all generated artifacts.

This is the first file opened by the claim pipeline.

### `<book-dir>/run_local.json`

Local convenience information, including the original absolute PDF path. It is
private and should not be committed.

### `<book-dir>/extraction/pages.jsonl`

One JSON object per physical PDF page. Each line includes page identity,
geometry, structure, extraction method, raw/normalized text, hashes, counts,
OCR information, and quality flags.

### `<book-dir>/extraction/blocks.jsonl`

One JSON object per native PDF text block, including page, reading order,
bounding box, text, and text hash. It supports layout analysis and audit.

### `<book-dir>/extraction/spans.jsonl`

Paragraph and sentence records used as stable evidence targets. Each record
contains page/section provenance, offsets into normalized page text, exact text,
hash, parent relationship, and `claim_eligible` status.

The claim pipeline currently reads eligible **paragraph** records from this
file. It does not read arbitrary chunks or the original PDF directly.

### `<book-dir>/extraction/structure.json`

Normalized PDF table of contents and calculated section ranges. It records the
mapping method and its limitations.

### `<book-dir>/media/images.jsonl`

Inventory of image occurrences with page IDs, PDF object references, hashes,
dimensions, format, and relative file paths. The corresponding bytes are under
`media/images/`.

### `<book-dir>/reports/extraction_summary.json`

Counts pages, native/OCR methods, empty/short pages, spans, sections, images,
offset errors, and extraction failures.

### `<book-dir>/reports/extraction_verification.json`

Results of deterministic integrity checks across source PDF, pages, spans,
blocks, structure, and image files.

### `<book-dir>/reports/schema_validation.json`

Record counts and JSON-Schema errors for every extraction artifact.

## 9. Claim Source Code

### `src/rnh/claims/cli.py`

Command-line boundary for four operations:

- `inspect`: count eligible paragraphs and planned model units without calling
  a model;
- `run`: execute/resume claim generation and produce reports;
- `validate`: rerun claim schema and source-reference checks; and
- `report`: regenerate readable JSON, CSV, and Markdown views.

### `src/rnh/claims/io.py`

Loads `manifest.json` and `extraction/spans.jsonl` into typed `BookInput` and
`SourceSpan` objects. It rejects duplicate IDs and incorrect text hashes.

`build_claim_units()`:

- selects claim-eligible paragraphs only;
- groups consecutive paragraphs;
- never crosses a part/chapter boundary;
- limits a unit to configured spans and characters; and
- assigns a deterministic unit ID.

With the checked configuration, each unit has at most five target paragraphs
and approximately 3,000 target characters. A single larger paragraph remains
intact.

### `src/rnh/claims/prompting.py`

Builds the two messages sent to the LLM:

1. System message: claim rules, strict output contract, and optional synthetic
   few-shot examples.
2. User message: book metadata, target spans, optional context-only spans, and
   a warning that evidence must come from target spans.

The model receives records shaped like:

```json
{
  "book_metadata": {
    "book_id": "book:...",
    "title": "...",
    "authors": ["..."],
    "publication_year": 2011,
    "language": "en",
    "source_sha256": "..."
  },
  "target_source_spans": [
    {
      "span_id": "book:...:p0042:para:003:...",
      "pdf_page_number": 42,
      "printed_page_label": "27",
      "chapter_title": "Chapter title",
      "section_title": "Section title",
      "text": "Exact extracted paragraph"
    }
  ]
}
```

The full PDF, page images, and unrelated chapters are not sent to the model.

### `src/rnh/claims/providers.py`

Provider adapters hide transport differences.

`OllamaProvider`:

- calls local `POST /api/chat`;
- supplies the exact model name;
- disables streaming and model thinking;
- includes the response JSON Schema in `format`;
- uses temperature, seed, context size, and keep-alive settings; and
- queries `/api/tags` and `/api/show` for model provenance.

`OpenAIProvider` is optional and requires installation with the `openai` extra,
an API key, and explicit permission to send source passages externally.

`ReplayProvider` supplies deterministic fixture responses for automated tests;
it is not a research extraction model.

### `src/rnh/claims/grounding.py`

Maps model-submitted strings back to source characters. It attempts:

1. `exact`: byte-for-character equality;
2. `whitespace_normalized`: differences only in whitespace; and
3. `source_normalized`: narrow PDF conventions such as curly/straight quotes,
   non-breaking spaces, soft hyphens, and line-wrap hyphenation.

Every successful method maps back to the untouched stored source substring and
returns start/end offsets plus match count. A semantic paraphrase is not
accepted as an evidence quote.

### `src/rnh/claims/pipeline.py`

The claim-processing engine.

Inputs:

- validated `BookInput` objects;
- model provider;
- versioned prompt/config/schema assets;
- condition, retries, workers, pilot limit, and output path.

For every unit it:

1. builds system and user prompts;
2. calls the selected provider;
3. immediately records the unmodified model response;
4. parses JSON and performs only declared lossless normalization;
5. validates the candidate response schema;
6. retries malformed responses up to the configured limit;
7. grounds evidence quotes against target spans;
8. computes evidence, mention, candidate, claim, and frame IDs;
9. checks model-proposed surface forms against grounded evidence;
10. creates review flags for uncertain fields;
11. validates final claim/frame schemas;
12. rejects ungrounded/malformed/duplicate candidates separately; and
13. writes a unit checkpoint before continuing.

### `src/rnh/claims/review.py`

Performs final run-level checks and creates human-facing views. It verifies
claim/frame schemas, source references, evidence hashes and offsets, unit
coverage, and duplicate IDs. It then creates readable JSON, CSV review sheets,
a stratified sample, a unit audit, and a Markdown report.

### `src/rnh/claims/__init__.py`

Package marker and public package metadata. It performs no extraction itself.

## 10. Claim Schemas

### `schemas/claim_candidate_response.schema.json`

Shape the LLM must return. It covers unit completion, warnings, atomic claim
candidates, evidence proposals, semantic fields, and frame proposals.

### `schemas/claim.schema.json`

Shape of a final grounded claim after Python adds provenance, offsets, hashes,
IDs, validation statuses, and human-review placeholders.

### `schemas/frame_candidate.schema.json`

Shape of a separate provisional framing annotation linked to a claim and its
grounded cue.

### `schemas/master_pipeline_config.schema.json`

Shape of the end-to-end user configuration. This is checked before any model
work starts.

## 11. Claim Output Files

### `<claim-run>/run.json`

Run provenance: status, books and hashes, model and digest, condition, prompt
and schema hashes, settings, timestamps, planned unit count, and summary.

### `<claim-run>/raw_responses.jsonl`

One row per model attempt containing the original response text, request prompt
hash, timing, model/backend, unit ID, and provider metadata. This is the audit
trail before deterministic post-processing.

### `<claim-run>/claims.jsonl`

Canonical streaming claim records. Each line is one grounded candidate with:

- atomic normalized claim text;
- claim kind, polarity, and epistemic status;
- attribution chain;
- predicate and role-bearing participants;
- time, location, quantity, and topic annotations;
- exact evidence and source offsets;
- page/chapter/extraction context;
- model/prompt/run provenance;
- automated verification results; and
- pending human-review state.

### `<claim-run>/frames.jsonl`

Separate provisional frame candidates linked to claim IDs and exact cue text.
An empty file is valid when the model proposes no qualifying frame.

### `<claim-run>/rejected_candidates.jsonl`

Candidates that failed evidence grounding, final schema checks, or duplicate
checks. Rejections remain visible rather than disappearing silently.

### `<claim-run>/units.jsonl`

One checkpoint/audit record per model unit: span IDs, chapter, page range,
attempts, runtime, status, claim/frame/rejection counts, warnings, and errors.

### `<claim-run>/errors.jsonl`

Provider, malformed JSON, or schema failures by unit and retry attempt. It
appears only when such failures occur.

### `<claim-run>/validation_report.json`

Final machine validation result, including planned/covered units, eligible
spans, schema/reference/offset/hash errors, and overall validity.

### `<claim-run>/summary.json`

Aggregate counts and timing: units, claims, rejections, frame candidates,
claim kinds, epistemic statuses, flags, and field-grounding issues.

### Human-facing generated views

| File | Use |
| --- | --- |
| `claims.pretty.json` | Indented, readable version of all canonical claims |
| `claims_review.csv` | Spreadsheet review of every retained claim |
| `human_review_sample.csv` | Deterministic stratified evaluation sample |
| `rejected_candidates.pretty.json` | Readable rejected candidate details |
| `rejected_candidates_review.csv` | Manual adjudication of rejected items |
| `unit_audit.csv` | Coverage, timing, warnings, and failures by model unit |
| `CLAIM_EXTRACTION_REPORT.md` | Concise run scope, counts, checks, and limits |
| `by_book/` | Per-book readable outputs for a multi-book run |

## 12. Master Orchestration Code

### `src/rnh/master.py`

This is the coordinator behind `rnh-pipeline`.

- `load_master_config()` validates and resolves the configuration.
- `find_extraction_by_hash()` safely reuses matching source extraction.
- `build_extraction_command()` constructs the exact PDF command.
- `build_claim_command()` constructs the exact claim command.
- `run_logged()` captures each child command's console output.
- `resolve_book_directories()` extracts new books or reuses declared ones.
- `run_master()` enforces extraction -> extraction validation -> claims ->
  claim validation -> report ordering.
- `summarize_claim_progress()` reads unit checkpoints for the status command.

The default extractor command is `sys.executable -m rnh.extraction.cli`, so it
automatically uses the active virtual environment on Linux and Windows.

Master state and stage logs are written beside the claim output:

```text
data/private/claim_runs/.<run-name>.master-state.json
data/private/claim_runs/.<run-name>.master-logs/
```

## 13. Test Files

| Path | Coverage |
| --- | --- |
| `tests/test_extraction.py` | Miniature PDF through extraction, hashes, offsets, and schemas |
| `tests/test_grounding.py` | Exact and normalized quote-to-source alignment |
| `tests/test_pipeline.py` | Claim units, model response processing, provenance, rejection, and resume |
| `tests/test_master.py` | Master config, path resolution, orchestration commands, and status |
| `tests/test_review.py` | Pilot/full-corpus report labels |
| `.github/workflows/tests.yml` | Runs the test suite automatically on pushes and pull requests |

## 14. What Is Automatic And What Is Not

| Result | Automatic? | Meaning |
| --- | --- | --- |
| PDF hash matches | Yes | Same source bytes |
| Record follows JSON Schema | Yes | Correct data shape |
| Quote and offsets reproduce source | Yes | Source grounding passed |
| Proposed field wording occurs in evidence | Yes | Surface grounding passed |
| OCR wording is completely correct | No | Requires comparison with page image |
| Claim is atomic and semantically faithful | Not finally | Requires human evaluation |
| Attribution/entity roles are correct | Not finally | Requires human evaluation |
| Frame interpretation is correct | No | Requires codebook-based human review |
| Statement is historically true | No | Requires independent historical evidence |

The correct final description is **source-grounded model-generated claim
candidates awaiting human review**.

## 15. Paths On The Current Research Machine

The canonical repository is:

```text
/mnt/samsung_old/Github/RNH-THESISWORK/RNH-LLM-VS-HYPERGRAPH/
```

The reusable extractor in this repository is:

```text
src/rnh/extraction/
```

The three older book extractions currently referenced by the private
three-book configuration are under the sibling prototype repository:

```text
/mnt/samsung_old/Github/RNH-THESISWORK/local_book_extractor/data_v2/books/
  OceanofPDF.com_1971_-_Anam_Zakaria-717a062e027b/
  Dead.Reckoning_Memories.of.the.1971.Bangladesh.War_Sarmila.Bose._2011_.cs-e487e7f7703a/
  Srinath_Raghavan_-_1971__A_Global_History_of_the_Creation_of_Bangladesh-Harvard_University_Press_2013_1-415feb0c6010/
```

Their private orchestration file is:

```text
data/private/master_three_books.json
```

That file records a historical local run and still names the sibling
prototype extractor. It is not the cross-platform team template. New runs
should copy `configs/master_pipeline.example.json`; when its optional
`extractor.command` is omitted, `rnh-pipeline` invokes the bundled extractor
through the active Python environment.

The in-progress three-book claim run is under:

```text
data/private/claim_runs/three_books_qwen35_4b_fewshot_v3/
```

A separate one-book extraction produced inside this repository is under:

```text
data/private/pilots/books/
  The_Bangladesh_Liberation_War_the_Sheikh_Mujib_Regime_and_Contemporary_Controversies_PDFDrive-02978de0fe2e/
```

All paths under `data/private/` and all source PDFs are intentionally ignored
by Git. Code, schemas, prompts, configurations, and documentation are shared;
copyrighted source material and generated full-text datasets are not.
