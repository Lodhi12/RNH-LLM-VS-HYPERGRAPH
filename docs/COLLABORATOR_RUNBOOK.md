# Collaborator Runbook: PDF to Grounded Claim Candidates

This is the practical operating guide for the RNH pipeline. It explains what
the software does, what the local LLM sees, where every output is written, and
how to run the same workflow on Linux, WSL, or native Windows.

## 1. What The Pipeline Produces

One run has two main transformations:

```text
local PDF
  -> structured source records
  -> chapter-aware model input units
  -> LLM claim candidates
  -> deterministic grounding checks
  -> human-review files
```

The extraction and claim datasets are deliberately separate:

- Extraction records describe what was recovered from the PDF and where it
  occurred.
- Claim records describe propositions presented by the book and point back to
  exact extraction spans.
- Frame candidates are separate interpretive annotations.
- Human decisions are separate from both model output and automatic checks.

The pipeline does not determine historical truth. It first establishes source
traceability and then prepares candidates for human evaluation.

## 2. Software Requirements

- Git
- Python 3.11 or newer
- Tesseract OCR plus the required language packs
- Ollama for local claim extraction
- Approximately 5 GB free disk space for the tested `qwen3.5:4b` model and
  additional space for PDFs and extraction outputs
- At least 8 GB system RAM recommended for the 4B model; more memory provides
  safer headroom

A GPU is optional. Ollama can use a supported GPU when available and otherwise
runs on CPU, usually much more slowly.

## 3. Linux Setup

On Ubuntu, Debian, or WSL Ubuntu:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv tesseract-ocr tesseract-ocr-eng

git clone git@github.com:Lodhi12/RNH-LLM-VS-HYPERGRAPH.git
cd RNH-LLM-VS-HYPERGRAPH

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Check the installation:

```bash
.venv/bin/rnh-bookpipe --version
.venv/bin/rnh-claims --help
.venv/bin/rnh-pipeline --help
.venv/bin/pytest -q
tesseract --version
tesseract --list-langs
```

Install Ollama using <https://ollama.com/download>. Start the server in one
terminal and pull the model in another:

```bash
ollama serve
```

```bash
ollama pull qwen3.5:4b
ollama list
curl http://127.0.0.1:11434/api/tags
```

If the installer already runs Ollama as a service, skip `ollama serve`.

## 4. Windows Setup

### Recommended: WSL 2

WSL gives every team member the same Linux commands and path behavior. In an
administrator PowerShell terminal:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if requested, open Ubuntu, and follow the Linux setup above.
Install and run Ollama inside WSL for the least ambiguous networking setup.

Windows drives are available in WSL under `/mnt`. For example:

```text
C:\Users\Ammar\Documents\book.pdf
```

becomes:

```text
/mnt/c/Users/Ammar/Documents/book.pdf
```

### Native PowerShell

Install Git, 64-bit Python 3.11 or newer, Tesseract OCR, and Ollama. Ensure both
`tesseract.exe` and `ollama.exe` are on `PATH`. Then run:

```powershell
git clone git@github.com:Lodhi12/RNH-LLM-VS-HYPERGRAPH.git
Set-Location RNH-LLM-VS-HYPERGRAPH

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

ollama pull qwen3.5:4b
ollama list
```

The Ollama Windows application normally starts its local server automatically.
Check it from PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

If OCR reports that language data is unavailable, point Tesseract at its
language directory for the current PowerShell session:

```powershell
$env:TESSDATA_PREFIX = "C:\Program Files\Tesseract-OCR\tessdata"
tesseract --list-langs
```

Use forward slashes in JSON paths to avoid escaping backslashes:

```json
{"pdf": "C:/Users/Ammar/Documents/book.pdf"}
```

## 5. Configure One Book

Create a local configuration beside the checked example. Files ending in
`.local.json` are ignored by Git:

Linux or WSL:

```bash
cp configs/master_pipeline.example.json configs/my-book.local.json
```

PowerShell:

```powershell
Copy-Item configs/master_pipeline.example.json configs/my-book.local.json
```

Edit these values:

```json
{
  "project_id": "dowlah-pilot-v1",
  "workspace_root": "..",
  "books": [
    {
      "pdf": "/absolute/path/to/book.pdf",
      "title": "Human-reviewed book title",
      "author": "Human-reviewed author",
      "publication_year": 2016,
      "language": "en",
      "rights_status": "private_research"
    }
  ],
  "claims": {
    "output_dir": "data/private/claim_runs/dowlah-pilot-v1",
    "backend": "ollama",
    "model": "qwen3.5:4b",
    "limit_units_per_book": 5
  }
}
```

Do not replace the complete checked example with this abbreviated fragment;
edit the corresponding values in the complete file.

Important settings:

| Setting | Meaning |
| --- | --- |
| `ocr_mode: auto` | Use native text when sufficient; OCR low-text pages |
| `ocr_dpi: 220` | Render OCR pages at 220 pixels per inch |
| `min_text_chars: 80` | OCR a page when native text is shorter than this |
| `include_blocks: true` | Preserve layout text blocks and coordinates |
| `include_images: true` | Extract embedded raster-image occurrences |
| `workers: 1` | Send one model request at a time |
| `limit_units_per_book: 5` | Small pilot over the first five planned units |
| `limit_units_per_book: null` | Process every eligible unit in the book |

Use a new `project_id` and output directory whenever the source, prompt, model,
schema, or important parameter changes.

## 6. Plan Before Running

Linux or WSL:

```bash
.venv/bin/rnh-pipeline plan configs/my-book.local.json
```

PowerShell:

```powershell
.\.venv\Scripts\rnh-pipeline.exe plan configs/my-book.local.json
```

`plan` validates the JSON configuration, checks the PDF and extractor, computes
the source SHA-256, and shows whether the extraction will be created or reused.
It does not call the LLM.

Read the displayed paths before continuing. In particular, confirm the source
PDF, output directory, model, and pilot limit.

## 7. Run The Pipeline

Linux or WSL:

```bash
.venv/bin/rnh-pipeline run configs/my-book.local.json
```

PowerShell:

```powershell
.\.venv\Scripts\rnh-pipeline.exe run configs/my-book.local.json
```

Use a second terminal to inspect progress:

```bash
.venv/bin/rnh-pipeline status configs/my-book.local.json
```

For PowerShell, replace `.venv/bin/rnh-pipeline` with
`.\.venv\Scripts\rnh-pipeline.exe`.

If interrupted, restart Ollama if needed and resume the unchanged run:

```bash
.venv/bin/rnh-pipeline run configs/my-book.local.json --resume
```

## 8. What Happens Internally

### Stage 1: configuration and policy checks

1. The master JSON is validated against
   `schemas/master_pipeline_config.schema.json`.
2. All relative paths are resolved from `workspace_root`.
3. A remote OpenAI run is rejected unless `external_api_allowed` is explicitly
   true. Local Ollama runs require no external-text permission.
4. The PDF must exist and the output path must be valid.

### Stage 2: source identity

1. Python reads the original PDF bytes.
2. It computes a full SHA-256 checksum.
3. The hash becomes the basis of the stable `book_id` and extraction folder.
4. An existing extraction is reused only when its manifest contains exactly
   the same source hash.

Changing the filename alone does not create a different source. Changing even
one PDF byte produces a different hash.

### Stage 3: page extraction

For every physical PDF page:

1. PyMuPDF reads embedded/selectable text in sorted reading order.
2. The text is conservatively normalized.
3. With `ocr_mode: auto`, fewer than `min_text_chars` usable native characters
   triggers OCR.
4. OCR pages are rendered at `ocr_dpi` and passed to Tesseract with the selected
   language and page-segmentation mode.
5. The chosen method is recorded as `native`, `ocr`, or
   `native_ocr_failed` rather than hidden.
6. Page geometry, printed label, rotation, text hashes, character/word counts,
   OCR confidence, quality flags, and errors are recorded.
7. Native layout blocks retain reading order and bounding boxes.
8. Embedded raster images are extracted, hashed, deduplicated as files, and
   recorded as page occurrences.

An embedded-image count is not automatically a count of meaningful historical
photographs. Logos, masks, repeated backgrounds, and page scans may also be
counted; a visual audit is still required.

### Stage 4: document structure and source spans

1. PDF bookmarks are normalized into a table of contents when available.
2. Each page receives its current part, chapter, section, and section kind.
3. Front matter, index, bibliography, notes, and promotional sections may be
   marked ineligible for claims.
4. Page text is split into paragraph and sentence spans.
5. Every span receives a stable ID, page number, section context, character
   offsets, text hash, extraction method, and eligibility flag.
6. Python checks that slicing page text at the stored offsets recreates the
   exact span text.

Bookmark-based chapter labels remain machine assignments until sampled human
review confirms them.

### Stage 5: extraction validation

The pipeline checks:

- every PDF page has exactly one page record;
- IDs are unique and belong to the expected book;
- span text, offsets, counts, and hashes agree;
- sentence spans point to valid parent paragraphs;
- blocks and image occurrences point to valid pages;
- extracted image files exist and match their hashes;
- section page ranges are valid;
- the local PDF still matches the recorded source hash; and
- every record conforms to its JSON Schema.

This establishes structural integrity and traceability, not OCR perfection.

### Stage 6: build model input units

1. Only claim-eligible paragraph spans are selected.
2. Each span's stored text hash is checked before use.
3. Consecutive spans are grouped without crossing a section boundary.
4. A default unit contains at most five paragraphs and approximately 3,000
   target characters.
5. Each unit stores its ordered target span IDs and page range.

The model therefore receives bounded text rather than the full PDF or an
untraceable whole-book string.

### Stage 7: construct the LLM request

The system prompt contains:

- the operational definition of a claim;
- inclusion, exclusion, atomicity, attribution, uncertainty, and framing rules;
- the strict output contract; and
- synthetic few-shot examples for the few-shot condition.

The user message contains:

- reviewed book metadata;
- target span IDs and exact text;
- page and chapter context; and
- an instruction that evidence must come only from target spans.

The complete prompt is versioned and hashed. Source text is explicitly treated
as data, so instructions appearing inside a book are not pipeline commands.

### Stage 8: call local Ollama

The `OllamaProvider` sends an HTTP `POST` request to:

```text
http://127.0.0.1:11434/api/chat
```

The request uses:

```text
model: qwen3.5:4b
stream: false
format: complete response JSON Schema
think: false
temperature: 0
seed: 17
num_ctx: 16384
keep_alive: 30m
```

Ollama may use GPU or CPU automatically. The pipeline records the model name,
digest, size, capabilities, prompt version, prompt hash, schema hashes, and run
configuration. Raw model responses are retained for audit.

### Stage 9: deterministic grounding

Python, not the LLM, supplies final provenance:

1. Parse and validate the returned JSON object.
2. Require every evidence `span_id` to belong to the current target unit.
3. Locate each submitted quote in that span.
4. Prefer an exact match; narrowly defined whitespace and PDF typography
   normalization may map the submitted quote back to the original substring.
5. Store exact span-relative and page-relative offsets.
6. Recompute the evidence hash.
7. Check proposed participant mentions, predicates, dates, locations,
   quantities, attribution cues, and frame cues against the evidence surface.
8. Deduplicate repeated candidates.
9. Put ungrounded or malformed records in the rejected-candidate ledger rather
   than silently repairing them.
10. Store frames separately from claims.

Exact grounding proves that evidence exists at the recorded source location.
It does not prove that the normalized proposition is semantically correct or
that the underlying historical statement is true.

### Stage 10: checkpoint and reporting

After each unit, the pipeline appends an audit record. Completed units can be
skipped during `--resume`. At the end it validates all cross-references and
creates readable JSON, spreadsheets, a stratified human-review sample, and a
Markdown report.

The final machine status is:

```text
machine_complete_human_review_pending
```

It should not be renamed `verified` or `ground_truth`.

## 9. Approximate Timing

Time depends on PDF quality, page count, CPU/GPU, model, context size, and claim
density. A 214-page test book was extracted into 214 pages, 3,451 spans, and
1,153 blocks. Its eight-unit local-model pilot generated 33 retained candidates
in approximately 5 minutes 40 seconds of unit processing on an RTX 3060, in
addition to model startup and extraction time.

Front-matter units with no claims completed in about 1-3 seconds. Dense prose
units took approximately 50-98 seconds each. A whole book may therefore take
hours. Always run five units first and estimate full-corpus time from
`unit_audit.csv`.

## 10. Output Map

One extraction directory contains:

```text
<book-directory>/
|-- manifest.json
|-- run_local.json
|-- extraction/
|   |-- pages.jsonl
|   |-- blocks.jsonl
|   |-- spans.jsonl
|   `-- structure.json
|-- media/
|   |-- images.jsonl
|   `-- images/
`-- reports/
    |-- extraction_summary.json
    |-- extraction_verification.json
    `-- schema_validation.json
```

One claim run contains:

```text
<claim-run>/
|-- run.json
|-- summary.json
|-- claims.jsonl
|-- claims.pretty.json
|-- claims_review.csv
|-- human_review_sample.csv
|-- frames.jsonl
|-- raw_responses.jsonl
|-- rejected_candidates.jsonl
|-- rejected_candidates_review.csv
|-- units.jsonl
|-- unit_audit.csv
|-- validation_report.json
`-- CLAIM_EXTRACTION_REPORT.md
```

Use `claims.jsonl` for software and `claims.pretty.json` or
`claims_review.csv` for reading. `raw_responses.jsonl` is evidence of what the
model originally returned; it is not the accepted dataset.

## 11. Human Review

Researchers review `human_review_sample.csv` against the source PDF and mark:

- whether the passage contains a claim;
- whether the candidate is atomic;
- whether it preserves source meaning;
- whether attribution, polarity, uncertainty, participants, time, and place
  are correct;
- whether the evidence boundary is appropriate; and
- whether a proposed frame follows the approved codebook.

At least two annotators should independently label the agreed evaluation
sample. Measure agreement, adjudicate disagreements, and freeze the reviewed
version before comparing RAG and hypergraph methods.

## 12. Common Problems

### `Cannot reach Ollama`

The server is not running or is not reachable at the configured URL:

```bash
ollama serve
curl http://127.0.0.1:11434/api/tags
```

### Model not found

```bash
ollama pull qwen3.5:4b
ollama list
```

The name in `ollama list` must match `claims.model` exactly.

### Tesseract or language unavailable

```bash
tesseract --version
tesseract --list-langs
```

Install the language pack or set `TESSDATA_PREFIX` to the `tessdata` directory.

### Output directory is not empty

Do not overwrite a different experiment. Either resume the unchanged run with
`--resume` or choose a new `claims.output_dir`.

### A pilot returns no claims

The first units may be a title page, contents, bibliography, or another
non-propositional section. Inspect `unit_audit.csv`, then increase the pilot
limit while retaining the same documented condition.

### Windows JSON path error

Use forward slashes such as `C:/Research/book.pdf`, or double every backslash
as `C:\\Research\\book.pdf`.

## 13. Git And Data-Sharing Rules

Commit:

- source code;
- JSON Schemas;
- versioned prompts and synthetic examples;
- non-sensitive example configurations;
- tests, documentation, and aggregate metrics.

Do not commit:

- copyrighted PDFs;
- full extracted book text;
- model weights;
- API keys or `.env` files;
- private chats or participant information; or
- local run configurations containing private paths.

Share restricted source material and full outputs through the team's approved
access-controlled storage. A private GitHub repository does not itself provide
copyright permission.

## 14. What To Say In A Meeting

> We first convert each PDF into page-, block-, and span-level records using
> native extraction where reliable and Tesseract OCR where required. Every
> record retains source hash, page, structure, extraction method, offsets, and
> text hash. We then send small chapter-aware source units to a locally hosted
> Qwen model through Ollama using a versioned few-shot prompt and strict JSON
> Schema. Python independently validates the response, maps evidence back to
> exact source offsets, records rejected candidates, and produces a human-review
> sample. Therefore the present output is source-grounded model-generated claim
> candidates, not historical ground truth or final human-verified data.
