# Claim Extraction Pipeline

This pipeline turns the already extracted, chapter-aware paragraph spans into
**model-generated claim candidates**. It represents what each book presents;
it does not determine objective historical truth.

## Method

1. Read each extraction's `manifest.json` and claim-eligible paragraph records
   from `extraction/spans.jsonl`.
2. Verify each paragraph's SHA-256 text hash.
3. Group consecutive paragraphs into units of at most five spans and about
   3,000 characters, without crossing a chapter boundary. The production local
   model receives no neighboring spans after pilot testing showed that it could
   incorrectly promote context-only statements to claims.
4. Send book metadata, target spans, context, the versioned instructions, and
   synthetic few-shot examples to a structured-output LLM.
5. Ask for atomic propositions with polarity, epistemic status, nested
   attribution, predicate, role-bearing participants, times, locations,
   quantities, topics, exact evidence, and optional Entman frame-function
   candidates.
6. Validate the raw response against
   `schemas/claim_candidate_response.schema.json`.
7. In deterministic Python, require every evidence quote to occur in its
   declared target span. Resolve exact, whitespace-only, or narrowly defined
   PDF typography/line-wrap normalization matches to source and page character
   offsets while preserving both the submitted and original quotation.
8. Check all model-proposed surface forms against evidence. Ungrounded evidence
   rejects the candidate; ungrounded semantic fields remain visible as review
   issues.
9. Store frame candidates separately because a framing annotation is an
   interpretation, not part of the historical proposition itself.
10. Validate final claims and frames, deduplicate exact repeats, checkpoint each
    completed unit, and create JSON, CSV, and Markdown review artifacts.

## What Automatic Verification Means

Automatic verification proves schema conformance and source traceability: the
quoted string and recorded offsets resolve to the extracted book text. It does
not prove that the claim paraphrase is faithful, that every possible claim was
found, that participant roles or frames are correct, or that the book's account
is historically true. Those questions require a human-coded evaluation sample.

## Recovery And Completeness Policy

- A rejected candidate remains in the rejection ledger; it is never silently
  rewritten into the canonical claim file.
- Safe PDF-only normalization (line wrapping, soft hyphens, typographic quote
  variants, and whitespace) is resolved deterministically while retaining the
  exact source substring and the model-submitted quotation.
- Candidates that omit, add, or paraphrase source words remain rejected. They
  are exported to `rejected_candidates_review.csv` for human adjudication or a
  separately identified second model pass.
- A failed model unit must be rerun. A unit marked `model_incomplete` must be
  split into smaller source units and rerun before corpus processing is called
  complete.
- Processing 100% of source units proves **input coverage**, not **claim
  recall**. Recall must be estimated against a manually annotated gold sample;
  no automated extractor can establish that it found every defensible claim.

## Commands

Create the environment:

```bash
git clone git@github.com:Lodhi12/RNH-LLM-VS-HYPERGRAPH.git
cd RNH-LLM-VS-HYPERGRAPH
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Inspect the planned workload before calling a model:

```bash
.venv/bin/rnh-claims inspect \
  --book-dir /path/to/book-one-extraction \
  --book-dir /path/to/book-two-extraction
```

Run a balanced pilot with a local Ollama model:

```bash
.venv/bin/rnh-claims run \
  --backend ollama \
  --model qwen3.5:4b \
  --workers 1 \
  --limit-units-per-book 5 \
  --book-dir /path/to/book-one-extraction \
  --book-dir /path/to/book-two-extraction \
  --output-dir data/private/claim_runs/pilot
```

Resume an interrupted run by repeating the command with `--resume`. The runner
skips every unit already recorded as complete.

Use one worker for the local `qwen3.5:4b` Ollama deployment used in this
project. This architecture currently exposes one inference slot; requesting
additional workers queues requests and does not improve throughput.

## Outputs

- `claims.jsonl`: canonical grounded claim records for programs and scaling
- `frames.jsonl`: provisional framing candidates linked by claim ID
- `claims.pretty.json`: the same claims in readable indented JSON
- `claims_review.csv`: all claims in spreadsheet form
- `human_review_sample.csv`: a deterministic per-book evaluation sample
- `rejected_candidates.pretty.json`: readable rejected-candidate records
- `rejected_candidates_review.csv`: rejected candidates with adjudication columns
- `unit_audit.csv`: unit-level coverage, status, counts, warnings, and timings
- `by_book/index.json`: per-book index pointing to readable JSON and CSV exports
- `by_book/<book-id>/claims.pretty.json`: readable claims for one book
- `by_book/<book-id>/frames.pretty.json`: readable frame candidates for one book
- `by_book/<book-id>/claims_review.csv`: spreadsheet export for one book
- `raw_responses.jsonl`: original LLM responses and request hashes
- `rejected_candidates.jsonl`: ungrounded or duplicate candidates
- `units.jsonl`: completion, timing, count, and warning audit by input unit
- `validation_report.json`: schema, unit coverage, source-reference, quote-hash,
  and offset integrity results
- `CLAIM_EXTRACTION_REPORT.md`: concise methodological and run summary
