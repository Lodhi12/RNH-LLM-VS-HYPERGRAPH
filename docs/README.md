# RNH Data Schema Guide

For the complete executable workflow, production prompt, validation gates, and
human-evaluation protocol, see the [Master End-to-End Pipeline](MASTER_PIPELINE.md).

This directory documents the canonical data format for the RNH historical-narrative research project. The format is designed to support source-faithful book extraction, claim extraction, human review, LLM/RAG experiments, and hypergraph construction from the same underlying records.

> **Status:** proposed core schema v1.0.0. The team and supervisor must approve the definitions and annotation rules before this becomes a frozen thesis protocol. The JSON examples in this document describe the logical data model; machine-enforced JSON Schema files still need to be implemented under `schemas/`.

## Contents

- [Design Goals](#design-goals)
- [What Is Canonical](#what-is-canonical)
- [Record Relationships](#record-relationships)
- [Extraction Schema](#extraction-schema)
- [Extraction Field Dictionary](#extraction-field-dictionary)
- [Claim Schema](#claim-schema)
- [Claim Field Dictionary](#claim-field-dictionary)
- [Controlled Values](#controlled-values)
- [Validation Rules](#validation-rules)
- [Review Workflow](#review-workflow)
- [LLM and Hypergraph Exports](#llm-and-hypergraph-exports)
- [Versioning and Migration](#versioning-and-migration)
- [Team Checklist](#team-checklist)

## Design Goals

The schema should be:

- **Source-grounded:** every claim resolves to exact text from an identified PDF.
- **Source-faithful:** attribution, negation, modality, uncertainty, and wording are preserved.
- **Readable:** a researcher can inspect a record without specialized software.
- **Machine-validatable:** types, required fields, enums, IDs, and references can be checked automatically.
- **Reproducible:** tools, models, prompts, settings, code versions, and runs are recorded.
- **Multimodal:** text, photographs, figures, maps, tables, captions, and page geometry can be represented.
- **Scalable:** the same logical records can be serialized as JSONL and Parquet-derived tables.
- **Method-neutral:** LLM and hypergraph experiments use the same source and claim records.

The schema represents what a book says. It does not automatically establish historical truth.

## What Is Canonical

The canonical dataset has two conceptual layers:

1. **Extraction layer:** books, pages, source spans, and assets obtained from a PDF.
2. **Interpretation layer:** claims and later frame annotations derived from source spans.

Claims must not be embedded inside page records. Updating a claim extractor should not require extracting the PDF again.

### Small human-readable package

For demonstrations, one book may be represented as:

```text
book-id/
|-- book_extraction.json
|-- claims.json
`-- review.csv
```

### Canonical scalable package

For corpus processing, use:

```text
book-id/
|-- manifest.json
|-- pages.jsonl
|-- spans.jsonl
|-- assets.jsonl
|-- claims.jsonl
|-- frame_annotations.jsonl
|-- verification.jsonl
`-- runs.jsonl
```

JSONL means one complete JSON object per line. It allows streaming, partial recovery, line-level inspection, and append-oriented processing. Pretty JSON, CSV, Markdown, spreadsheets, LLM training rows, and Parquet files are generated views rather than independent canonical datasets.

## Record Relationships

```text
book
  |
  +-- page
  |     |
  |     +-- span <----- evidence ----- claim
  |     |                              |
  |     +-- asset                      +-- participants
  |                                    +-- time/location
  |                                    +-- narrative labels
  |
  +-- extraction run             claim-extraction run
```

Required reference chain:

```text
claim_id
  -> book_id
  -> evidence[].span_id
  -> span.page_id
  -> page.book_id
  -> book.source_sha256
```

If any link is missing or inconsistent, the claim is not fully grounded.

## Extraction Schema

This is the minimum per-book logical structure. Arrays may be moved into separate JSONL files at scale.

```json
{
  "schema_version": "1.0.0",
  "offset_convention": "unicode_code_point_half_open",
  "book": {
    "book_id": "book:0123456789abcdef",
    "title": "Example Historical Book",
    "authors": ["Example Author"],
    "publication_year": 1971,
    "language": "en",
    "source_file_name": "example-book.pdf",
    "source_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "page_count": 200
  },
  "pages": [
    {
      "page_id": "page:0123456789abcdef:0042",
      "book_id": "book:0123456789abcdef",
      "pdf_page_number": 42,
      "printed_page_label": "27",
      "geometry": {
        "width_points": 612.0,
        "height_points": 792.0,
        "rotation_degrees": 0
      },
      "structure": {
        "part_title": null,
        "chapter_id": "chapter:0123456789abcdef:03",
        "chapter_title": "Chapter 3",
        "section_title": null,
        "assignment_method": "pdf_bookmark",
        "review_status": "pending"
      },
      "text": {
        "raw": "The witness reported that residents left the town in April 1971.",
        "normalized": "The witness reported that residents left the town in April 1971.",
        "normalized_sha256": "replace-with-real-sha256"
      },
      "extraction": {
        "method": "native",
        "engine": "PyMuPDF",
        "engine_version": "record-exact-version",
        "run_id": "run:extract:000001"
      },
      "quality_flags": [],
      "review_status": "pending"
    }
  ],
  "spans": [
    {
      "span_id": "span:0123456789abcdef:0042:0001",
      "book_id": "book:0123456789abcdef",
      "page_id": "page:0123456789abcdef:0042",
      "span_type": "paragraph",
      "page_char_start": 0,
      "page_char_end": 64,
      "text": "The witness reported that residents left the town in April 1971.",
      "text_sha256": "replace-with-real-sha256"
    }
  ],
  "assets": [
    {
      "asset_id": "asset:0123456789abcdef:0042:0001",
      "book_id": "book:0123456789abcdef",
      "page_id": "page:0123456789abcdef:0042",
      "asset_type": "photograph",
      "bbox_points": [72.0, 120.0, 540.0, 500.0],
      "file_path": "assets/asset-0042-0001.png",
      "file_sha256": "replace-with-real-sha256",
      "caption_span_id": null,
      "extraction_method": "embedded_raster",
      "review_status": "pending"
    }
  ],
  "run": {
    "run_id": "run:extract:000001",
    "code_commit": "full-git-commit",
    "started_at": "2026-09-30T12:00:00Z",
    "configuration_sha256": "replace-with-real-sha256"
  }
}
```

The example values are illustrative. A placeholder hash must never appear in production data.

## Extraction Field Dictionary

### Dataset fields

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | Yes | Semantic version of the record contract |
| `offset_convention` | Yes | Unit and interval rule used by all character offsets |
| `book` | Yes | Source identity and bibliographic record |
| `pages` | Yes | One record for every physical PDF page |
| `spans` | Yes | Addressable source passages used by claims and retrieval |
| `assets` | Yes | Visual/table records; an empty array means none were recorded |
| `run` | Yes | Reproducibility information for this extraction |

### Book fields

| Field | Required | Rule |
| --- | --- | --- |
| `book_id` | Yes | Stable project ID derived from or registered against the full source hash |
| `title` | Yes | Human-reviewed bibliographic title, not blindly trusted PDF metadata |
| `authors` | Yes | Array because a work may have multiple authors; empty only when genuinely unknown |
| `publication_year` | Yes | Integer or `null` when unknown |
| `language` | Yes | Prefer a documented BCP 47 language tag such as `en` or `bn` |
| `source_file_name` | Yes | Original local filename for audit; not the primary identity |
| `source_sha256` | Yes | Lowercase 64-character SHA-256 of the exact PDF bytes |
| `page_count` | Yes | Physical PDF page count |

Publisher, edition, ISBN, translator, editor, archive, and rights/access fields are recommended extensions. They should be added when the corpus requires edition-sensitive comparison.

### Page fields

| Field | Required | Rule |
| --- | --- | --- |
| `page_id` | Yes | Unique and stable within the dataset |
| `book_id` | Yes | Must equal the parent book ID |
| `pdf_page_number` | Yes | One-based physical page order |
| `printed_page_label` | Yes | Printed/encoded label such as `xii` or `27`; empty when absent |
| `geometry` | Yes | Dimensions in PDF points and clockwise rotation |
| `structure` | Yes | Part/chapter/section context plus assignment provenance |
| `text.raw` | Yes | Selected engine output before project normalization |
| `text.normalized` | Yes | Versioned conservative normalization used by source spans |
| `text.normalized_sha256` | Yes | Hash of the exact normalized Unicode text |
| `extraction.method` | Yes | Controlled route: native, OCR, hybrid, or none |
| `extraction.engine` | Yes | Main engine; hybrid detail belongs in block-level extensions |
| `extraction.engine_version` | Yes | Exact installed version or model identifier |
| `extraction.run_id` | Yes | Link to the run record |
| `quality_flags` | Yes | Empty array or controlled warnings; never hidden |
| `review_status` | Yes | Human page-review state |

The PDF page index used by software may be stored additionally as zero-based `pdf_page_index`. If both are present, `pdf_page_number` must equal `pdf_page_index + 1`.

### Structure fields

`assignment_method` should record how the chapter was obtained:

```text
pdf_bookmark
toc_alignment
layout_detection
model_proposed
manual
none
```

A chapter title produced by a bookmark or model is not automatically correct. Use `review_status` to distinguish proposed structure from reviewed structure.

### Span fields

| Field | Required | Rule |
| --- | --- | --- |
| `span_id` | Yes | Unique source-span identifier |
| `book_id` | Yes | Must resolve to the source book |
| `page_id` | Yes | Must resolve to exactly one page |
| `span_type` | Yes | Usually `paragraph` or `sentence` |
| `page_char_start` | Yes | Inclusive code-point offset in `page.text.normalized` |
| `page_char_end` | Yes | Exclusive code-point offset in `page.text.normalized` |
| `text` | Yes | Must equal `normalized[start:end]` exactly |
| `text_sha256` | Yes | Hash of the exact span text |

Offsets use the half-open interval `[start, end)`. This convention allows deterministic reconstruction and avoids uncertainty about whether the ending character is included.

Sentence spans may reference a parent paragraph in an extension field named `parent_span_id`. Multi-page paragraphs should be represented as ordered spans rather than pretending one page offset covers two pages.

### Asset fields

| Field | Required | Rule |
| --- | --- | --- |
| `asset_id` | Yes | Unique asset or occurrence identifier |
| `book_id` | Yes | Parent source book |
| `page_id` | Yes | Page on which the asset appears |
| `asset_type` | Yes | Photograph, map, figure, table, chart, diagram, or other |
| `bbox_points` | Conditional | `[x0, y0, x1, y1]` in the declared page coordinate system |
| `file_path` | Conditional | Relative path to an extracted/rendered asset |
| `file_sha256` | Conditional | Required whenever an asset file exists |
| `caption_span_id` | Yes | Linked caption span or `null` |
| `extraction_method` | Yes | Embedded raster, rendered region, vector, table parser, or manual |
| `review_status` | Yes | Human visual-review state |

An empty `assets` array means no assets were recorded. It does not prove that the book contains no meaningful visual content unless the visual audit was completed.

### Optional block extension

Complex layouts should add `blocks.jsonl`. Each block should contain `block_id`, `page_id`, `block_type`, bounding box, reading order, raw/normalized text, extraction method, and confidence or quality flags. Block records are strongly recommended for columns, quotations, footnotes, captions, and tables but are not required for the first core-schema pilot.

## Claim Schema

Claims are stored separately from extraction and point back to exact source spans.

```json
{
  "schema_version": "1.0.0",
  "claim_id": "claim:0123456789abcdef:000001",
  "book_id": "book:0123456789abcdef",
  "claim_text": "The witness reported that residents left the town in April 1971.",
  "claim_kind": "event",
  "polarity": "affirmed",
  "epistemic_status": "reported",
  "attribution_chain": [
    {
      "speaker": "Example Author",
      "speaker_role": "author",
      "cue": "writes"
    },
    {
      "speaker": "Example Witness",
      "speaker_role": "witness",
      "cue": "reported"
    }
  ],
  "predicate": "left",
  "participants": [
    {
      "text": "residents",
      "role": "actor",
      "entity_id": null
    },
    {
      "text": "the town",
      "role": "origin",
      "entity_id": null
    }
  ],
  "times": [
    {
      "text": "April 1971",
      "normalized": "1971-04"
    }
  ],
  "locations": [
    {
      "text": "the town",
      "normalized": null,
      "entity_id": null
    }
  ],
  "evidence": [
    {
      "span_id": "span:0123456789abcdef:0042:0001",
      "page_id": "page:0123456789abcdef:0042",
      "quote": "The witness reported that residents left the town in April 1971.",
      "span_char_start": 0,
      "span_char_end": 64
    }
  ],
  "narrative_labels": [],
  "extraction": {
    "method": "llm_zero_shot",
    "model": "record-exact-model-version",
    "prompt_version": "claim-prompt-1.0.0",
    "run_id": "run:claims:000001"
  },
  "verification": {
    "exact_quote_match": true,
    "offset_match": true,
    "source_fidelity": "pending",
    "historical_truth": "not_assessed"
  },
  "review": {
    "status": "pending",
    "flags": [],
    "reviewer_id": null,
    "reviewed_at": null,
    "note": null
  }
}
```

The sentence is illustrative and must not be interpreted as an actual historical assertion.

## Claim Field Dictionary

### Identity and proposition

| Field | Required | Rule |
| --- | --- | --- |
| `schema_version` | Yes | Claim-schema version |
| `claim_id` | Yes | Unique claim identifier |
| `book_id` | Yes | Exact source book |
| `claim_text` | Yes | One atomic source-faithful proposition |
| `claim_kind` | Yes | Semantic kind of proposition |
| `polarity` | Yes | Whether the proposition is affirmed or negated |
| `epistemic_status` | Yes | How the source presents the proposition |
| `predicate` | Yes | Main action, state, or relation in concise source-faithful wording |

`claim_text` may normalize a proposition for readability, but it must not add facts absent from the evidence. The exact original wording belongs in `evidence[].quote`.

### Attribution chain

`attribution_chain` records nested voices from outermost to innermost:

```text
book author -> quoted historian -> witness
```

The final entry is the immediate source of the proposition. A direct author assertion normally has one entry. Unknown speakers should use a documented unknown value rather than a guessed name.

Each entry records:

- `speaker`: source wording or reviewed name;
- `speaker_role`: author, narrator, interviewee, witness, official, organization, document, or other;
- `cue`: wording such as `writes`, `according to`, `recalled`, or `denied`, when present.

### Participants

`participants` stores entities mentioned in the proposition and their semantic roles. It replaces an unstructured `actors` list.

| Field | Required | Rule |
| --- | --- | --- |
| `text` | Yes | Exact or conservatively normalized source mention |
| `role` | Yes | Participant's role in this claim |
| `entity_id` | Yes | Canonical entity reference or `null` before entity resolution |

Do not force every participant to be an actor. Someone may be affected, observed, quoted, benefited, displaced, detained, or used as an object of comparison.

### Time and location

`times` and `locations` are arrays because one claim may mention multiple values. Each keeps source wording in `text`; normalization is optional and must never replace the source form.

Examples of valid uncertainty:

```json
{
  "times": [
    {
      "text": "in early 1971",
      "normalized": null
    }
  ],
  "locations": [
    {
      "text": "near the border",
      "normalized": null,
      "entity_id": null
    }
  ]
}
```

### Evidence

Each evidence entry must contain:

- a valid `span_id`;
- the span's valid `page_id`;
- an exact quotation copied from `span.text`;
- inclusive `span_char_start` and exclusive `span_char_end` offsets.

The validator must confirm:

```text
span.text[span_char_start:span_char_end] == quote
```

Evidence may contain multiple entries when a proposition genuinely requires multiple passages. Avoid combining separate propositions merely because they occur together.

### Narrative labels and frames

The current proposed labels are stored provisionally as `narrative_labels`, not validated frames:

```text
liberation_war
genocide_massacre
counter_insurgency
civil_war
foreign_intervention
humanitarian_crisis
sexual_violence
state_institutional_failure
other
```

These labels mix topics, conflict characterizations, and framing functions. Before thesis analysis, the team must either divide them into separate dimensions or approve a theoretically justified mixed codebook.

Once frames are formalized, prefer separate `frame_annotation` records containing target ID, label, codebook version, evidence/rationale, annotator or model run, confidence definition if any, and review status. This allows frames to change without rewriting canonical claims.

### Extraction provenance

| Field | Required | Rule |
| --- | --- | --- |
| `method` | Yes | Human, rule-based, zero-shot LLM, few-shot LLM, or hybrid |
| `model` | Conditional | Exact model/version for model-based extraction; otherwise `null` |
| `prompt_version` | Conditional | Required for LLM extraction |
| `run_id` | Yes | Link to configuration, timestamp, code commit, and failures |

The model may propose semantic fields. Deterministic code must attach book IDs, page IDs, hashes, offsets, schema results, and exact-match results.

### Verification

| Field | Question answered |
| --- | --- |
| `exact_quote_match` | Does the quotation occur exactly in the referenced span? |
| `offset_match` | Do the offsets reconstruct exactly that quotation? |
| `source_fidelity` | Does the claim faithfully represent the evidence, including attribution and uncertainty? |
| `historical_truth` | Has the proposition been evaluated against independent historical evidence? |

Exact matches are deterministic grounding checks. Source fidelity requires semantic evaluation and ultimately human review. Historical truth is separate and remains `not_assessed` unless the thesis adopts an external corroboration protocol.

### Human review

`review.status` and `review.flags` serve different purposes:

- status says what decision was made;
- flags explain problems requiring attention.

An accepted claim normally has `status: "accepted"` and `flags: []`. The value `good` must not be stored as an issue flag.

## Controlled Values

### Claim kind

```text
event
state
causal
comparative
interpretive
quantitative
other
```

### Polarity

```text
affirmed
negated
mixed
```

### Epistemic status

```text
asserted
reported
remembered
inferred
disputed
uncertain
```

Denial is normally represented as `polarity: negated` with the appropriate epistemic status. If the research needs to distinguish denying speech acts from ordinary negation, add a documented `denied` status in a later schema version.

### Participant role

Initial values:

```text
actor
affected_entity
object
beneficiary
witness
source
institution
origin
destination
other
```

Roles should be expanded only through a reviewed codebook change.

### Review status

```text
pending
accepted
needs_revision
rejected
```

### Review flags

```text
not_a_claim
not_atomic
unsupported_claim
quote_not_exact
quote_boundary_unclear
wrong_attribution
weak_actor
unresolved_pronoun
participant_role_uncertain
negation_or_modality_lost
time_unparseable
location_ambiguous
narrative_label_uncertain
possible_duplicate
ocr_suspected
chapter_uncertain
```

### Source fidelity

```text
pending
faithful
partially_faithful
not_faithful
```

### Historical truth

```text
not_assessed
corroborated
contradicted
mixed
insufficient_evidence
```

Only a separate, documented external-evidence process may assign a value other than `not_assessed`.

## Validation Rules

### Structural validation

- Every record validates against its versioned JSON Schema.
- Required fields exist even when their allowed value is `null` or `[]`.
- Enum fields contain only approved values.
- IDs are unique within their record type.
- Dates, hashes, timestamps, and numeric fields use one declared format.

### Referential validation

- Every page `book_id` resolves to one book.
- Every span resolves to one page in the same book.
- Every asset resolves to one page in the same book.
- Every claim resolves to its stated book.
- Every evidence span and page exist and belong to that claim's book.
- Every non-null entity, chapter, caption, model-run, and reviewer reference resolves.

### Exact grounding validation

- Page count equals the number of expected page records.
- Span page offsets are in bounds.
- Slicing normalized page text reproduces the span exactly.
- Slicing span text reproduces each evidence quotation exactly.
- Stored text and asset hashes reproduce.
- Offset and exact-quote results are computed by code, not accepted from the LLM.

### Semantic validation

Human reviewers should evaluate:

- whether the record is actually a claim;
- whether it contains one main proposition;
- whether evidence supports the claim wording;
- whether speaker and attribution chain are correct;
- whether negation, uncertainty, memory, and disagreement are retained;
- whether predicate and participant roles are correct;
- whether time and location are source-supported;
- whether narrative labels follow the approved codebook.

Schema validity and exact quotation matching do not prove semantic correctness.

## Review Workflow

1. Extract the PDF and produce source records.
2. Run structural, reference, hash, and offset validators.
3. Review all failed, OCR, empty, suspicious, and multimodal pages.
4. Draw a stratified random sample of apparently successful pages.
5. Generate candidate claims without assigning historical truth.
6. Run deterministic evidence checks.
7. Have reviewers label claimhood, atomicity, source fidelity, attribution, participants, and narrative labels.
8. Double-annotate the research benchmark and calculate agreement.
9. Adjudicate disagreements while preserving original annotations.
10. Export only accepted records as gold fine-tuning/evaluation data.

Suggested page states:

```text
extracted_unreviewed
sample_reviewed
benchmark_validated
production_accepted
```

These may become a separate extraction-release status rather than replacing the simpler per-record review status.

## LLM and Hypergraph Exports

### LLM and RAG

The LLM view may combine a claim with selected metadata, but it must retain `claim_id`, `book_id`, and evidence span IDs. Fine-tuning examples should be generated only from reviewed records.

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Versioned claim-extraction instruction"
    },
    {
      "role": "user",
      "content": "Bounded source passage"
    },
    {
      "role": "assistant",
      "content": "Validated structured claim record"
    }
  ],
  "metadata": {
    "claim_id": "claim:0123456789abcdef:000001",
    "book_id": "book:0123456789abcdef",
    "span_ids": ["span:0123456789abcdef:0042:0001"],
    "schema_version": "1.0.0"
  }
}
```

### Hypergraph

- A reviewed claim becomes a hyperedge.
- Participant entities become nodes.
- Participant roles become incidences between nodes and the claim hyperedge.
- Time, place, speaker, source span, and book may also be linked nodes.
- Claim-to-claim relations such as supports, contradicts, qualifies, or duplicates should be separate reviewed relation records.

At scale, derive:

```text
nodes.parquet
hyperedges.parquet
incidences.parquet
```

These files are optimized exports. They must preserve canonical IDs and must be regenerable from the reviewed JSONL records.

## Versioning and Migration

Use semantic versions:

- patch: clarification or validation change with no field meaning change;
- minor: backward-compatible optional field or enum addition;
- major: incompatible field removal, renaming, type change, or semantic change.

Rules:

- Never silently overwrite a schema or prompt version.
- Store migration scripts for breaking changes.
- Keep the original source records immutable for a released dataset version.
- Give corrected records a new dataset release and document the change.
- Record the schema version in every standalone record.
- Pin the code commit, environment, model, prompt, and configuration for every run.

## What Must Not Be Stored as Fact

- An LLM confidence score is not historical probability.
- OCR confidence is not transcription ground truth.
- Exact quotation matching is not semantic verification.
- Source fidelity is not external historical truth.
- PDF metadata is not automatically correct bibliographic metadata.
- A model-proposed chapter or frame is not human-approved annotation.
- Missing visual assets do not prove that a book contains no images.

## Team Checklist

Before schema v1.0.0 is frozen:

- [ ] Supervisor approves the definitions of claim, frame, source fidelity, and historical truth.
- [ ] Team approves all required fields and controlled values.
- [ ] JSON Schema files are implemented for every record type.
- [ ] ID-generation and offset conventions are documented and tested.
- [ ] Extraction and claim examples validate automatically.
- [ ] At least three books and multiple page types are included in a pilot.
- [ ] Every team member independently annotates the same pilot sample.
- [ ] Agreement and disagreements are reported field by field.
- [ ] Frame/narrative-label codebook is approved or labels are excluded from the core experiment.
- [ ] LLM and hypergraph exports are generated from identical accepted claims.
- [ ] Copyrighted PDFs, full extracted text, secrets, and private communication are excluded from Git.
- [ ] Schema, prompt, dataset, and experiment versions are frozen before final evaluation.

## Related Documents

- [Claim Extraction Pipeline](CLAIM_EXTRACTION_PIPELINE.md)
- [Proposed Thesis Methodology](THESIS_METHODOLOGY_PROPOSAL.md)
- [Extraction Method and Evaluation Guide](EXTRACTION_METHOD_GUIDE.md)
- [Review of the Simplified Extraction and Claim Schemas](SCHEMA_PROPOSAL_REVIEW.md)
- [Main research README](../README.md)

The governing principle is simple: retain only fields with a clear research purpose, but never remove the identity, evidence, attribution, and provenance needed to audit a result.
