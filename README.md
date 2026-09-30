# RNH: LLM vs Hypergraph

Research repository for building and evaluating reproducible pipelines that represent historical books as source-grounded text, claims, retrieval units, and hypergraphs.

> **Research status:** protocol and infrastructure design. Existing scripts and generated outputs are prototypes, not validated thesis results. The definitions, annotation policy, frame taxonomy, and evaluation design must be approved by the research team and supervisor before corpus-scale processing begins.

## Contents

- [Research Objective](#research-objective)
- [Core Principles](#core-principles)
- [Operational Definitions](#operational-definitions)
- [Proposed End-to-End Pipeline](#proposed-end-to-end-pipeline)
- [Canonical Data Model](#canonical-data-model)
- [LLM and Hypergraph Views](#llm-and-hypergraph-views)
- [Evaluation Plan](#evaluation-plan)
- [Planned Repository Layout](#planned-repository-layout)
- [Team Workflow](#team-workflow)
- [Reproducibility Requirements](#reproducibility-requirements)
- [Copyright, Privacy, and Security](#copyright-privacy-and-security)
- [Current Status](#current-status)
- [Research Roadmap](#research-roadmap)
- [Decisions Required From the Supervisor](#decisions-required-from-the-supervisor)

## Research Objective

This project studies how Large Language Model (LLM) and hypergraph-based methods can support the analysis of competing historical narratives. The intended comparison is not simply "LLM versus graph." Both approaches must receive records derived from the same books, under the same source-grounding and evaluation rules.

The project will investigate questions such as:

1. How accurately can multimodal historical books be converted into structured, traceable records?
2. How reliably can atomic claims and their attribution, participants, time, place, and evidence be extracted?
3. What is gained or lost when the same grounded evidence is represented for LLM retrieval and for hypergraph analysis?
4. How do the approaches differ in retrieval quality, traceability, contradiction discovery, narrative comparison, and human interpretability?
5. How should framing be operationalized and evaluated without treating model-generated labels as historical facts?

The final research questions and hypotheses are **not yet fixed**. They require supervisor approval before experimental claims are made.

## Core Principles

- **Preserve the source.** Every derived record must be traceable to a book, page, source span, and exact evidence quotation.
- **Separate representations.** Extraction records, claim records, frame annotations, and historical verification records are related but distinct.
- **Separate fidelity from truth.** A claim can faithfully represent what a book says while still being historically false, disputed, biased, or unverifiable.
- **Do not hide uncertainty.** OCR uncertainty, incomplete attribution, ambiguous dates, model confidence, and reviewer disagreement must be recorded.
- **Use one canonical logical model.** LLM and hypergraph exports are derived views of the same versioned source and claim records.
- **Evaluate, do not assume.** Structured output guarantees shape, not correctness. OCR confidence is not proof of transcription accuracy, and rule scores are feature scores rather than calibrated probabilities.
- **Keep humans in the protocol.** Automated checks reduce review effort; they do not establish 100% ground truth.
- **Make every run reproducible.** Record file hashes, software/model versions, prompts, parameters, schema versions, and run identifiers.

## Operational Definitions

These are working definitions to be refined with the supervisor and documented in an annotation guide.

They are **not universal definitions discovered by the software**. They are project-specific operational definitions synthesized from the research and standards listed below. This distinction matters because [Daxenberger et al. (2017)](https://doi.org/10.18653/v1/D17-1218) found substantially different conceptualizations of a claim across six argument-mining datasets, with harmful effects on cross-domain classification.

| Concept | Literature or standards basis | Project decision | Status |
| --- | --- | --- | --- |
| Book extraction | TEI document structure, IIIF canvases/regions, W3C annotation targets, and W3C provenance | Preserve content, structure, location, method, and lineage in one traceable representation | Draft synthesis |
| Source span | W3C Web Annotation selectors, especially text-position and fragment selectors | Use stable IDs plus page, offsets, and optional bounding boxes | Draft synthesis |
| Claim | Cross-domain claim research, atomic-fact evaluation, evidence-based fact verification, and attribution annotation | Represent one attributed proposition without deciding its external historical truth | Draft; requires annotation pilot |
| Frame | Entman's selection-and-salience formulation of framing | Keep frames separate from topics and claims; use only an approved codebook | Draft; taxonomy not selected |
| Grounding/fidelity/truth | Evidence-based verification plus project provenance requirements | Evaluate source location, faithful representation, and external truth separately | Draft synthesis |

These definitions become accepted for this thesis only after the team: (1) records the theoretical choice, (2) writes inclusion and exclusion rules with examples, (3) independently annotates a representative pilot sample, (4) measures agreement for each field, (5) adjudicates disagreements, and (6) freezes a versioned annotation guide with supervisor approval.

### Book extraction

**Book extraction** is the source-faithful conversion of a PDF into structured machine-readable records while preserving document hierarchy, page location, reading order, textual content, visual objects, and extraction provenance. This is a project synthesis informed by [TEI](https://tei-c.org/release/doc/tei-p5-doc/en/html/), [IIIF Presentation API](https://iiif.io/api/presentation/3.0/), [W3C Web Annotation](https://www.w3.org/TR/annotation-model/), and [W3C PROV-O](https://www.w3.org/TR/prov-o/); none of those standards alone defines this complete pipeline.

Extraction includes:

- bibliographic and file metadata;
- a cryptographic source-file hash;
- PDF page index and printed page label when available;
- native text, OCR text, or a recorded hybrid decision per page or region;
- blocks, lines, spans, reading order, and page coordinates where available;
- parts, chapters, sections, headings, footnotes, captions, tables, and references;
- embedded or rendered images with page and bounding-box provenance;
- quality measurements, warnings, and review status.

Extraction does **not** mean that the text has been historically verified. Native PDF text means characters already encoded in the PDF; OCR means text recognized from page pixels. Either can contain errors.

### Source span

A **source span** is an immutable, addressable piece of extracted source text. It has a stable identifier and locators such as book ID, page index, character offsets, and optionally a bounding box. Claims and retrieval chunks point to source spans rather than copying untraceable text. Its locator design is informed by the W3C Web Annotation model's [selectors](https://www.w3.org/TR/annotation-model/#selectors), including text-position and fragment selectors.

### Claim

A **claim** is an atomic proposition that an identifiable source presents as asserted, reported, remembered, interpreted, denied, disputed, or uncertain. It should express one main proposition and retain its attribution, polarity, modality, and uncertainty. Atomic decomposition is informed by [FActScore](https://doi.org/10.18653/v1/2023.emnlp-main.741); evidence-linked labels are informed by [FEVER](https://doi.org/10.18653/v1/N18-1074); and explicit source/content attribution is informed by [PARC 3.0](https://lrec.elra.info/proceedings/lrec2016/summaries/619.html). The broader historical-book definition remains our own operational choice.

A claim record must answer:

- Who presents the proposition?
- What is being claimed?
- Who or what participates in it?
- What action, state, or relation is described?
- When and where does it apply, if stated?
- Is it affirmed, negated, disputed, remembered, quoted, or uncertain?
- Which exact passage supports this representation?

Headings, isolated names, incomplete fragments, bibliography entries, and questions without an asserted answer are not claims. Claim extraction identifies **book claims**, not automatically true historical facts.

### Frame

A **frame** is a documented pattern of selection and emphasis through which a source defines a situation, attributes causes or responsibility, makes evaluations, or implies remedies. This is adapted from [Entman (1993)](https://doi.org/10.1111/j.1460-2466.1993.tb01304.x). Frames are annotations over claims or passages, not substitutes for claims.

Labels such as `political`, `military`, or `humanitarian` are topics or domains unless the annotation guide explicitly defines them as frames. A usable frame scheme requires:

- a theoretical basis;
- an explicit label inventory;
- inclusion and exclusion rules;
- positive, negative, and ambiguous examples;
- multi-label and uncertainty rules;
- independent annotation and inter-annotator agreement testing.

No final frame inventory has yet been approved for this project.

### Grounding, fidelity, and truth

| Term | Question answered | Minimum evidence |
| --- | --- | --- |
| Source grounding | Can this record be located in the supplied book? | Book hash, page, span/offsets, exact quote |
| Source fidelity | Does the record accurately preserve what the passage says and who says it? | Grounding checks plus semantic/human review |
| Historical truth | Is the proposition supported by evidence beyond this book? | Independent sources and a documented historical verification protocol |

This project currently prioritizes **source grounding and source fidelity**. Historical truth assessment is a separate research task and must never be inferred from an LLM confidence score.

## Proposed End-to-End Pipeline

```text
PDF acquisition and rights record
              |
              v
Source hashing and PDF diagnostics
              |
              v
Page classification: native / OCR / hybrid
              |
              v
Layout-aware text, table, caption, and image extraction
              |
              v
Reading-order reconstruction and conservative normalization
              |
              v
Part / chapter / section hierarchy mapping
              |
              v
Stable pages, blocks, spans, and retrieval chunks
              |
              v
Candidate claim extraction (rules and/or LLM)
              |
              v
Schema + exact-grounding + semantic validation
              |
              v
Human annotation and adjudication sample
              |
       +------+------+
       |             |
       v             v
  LLM / RAG view   Hypergraph view
       |             |
       +------+------+
              v
       Comparative evaluation
```

### 1. Ingest and diagnose

For every source PDF:

1. Assign a stable `book_id` and compute a SHA-256 hash.
2. Record filename, provenance, rights/access status, byte size, page count, and available PDF metadata.
3. Diagnose every page for selectable text, image coverage, font encoding, rotation, and likely OCR need.
4. Preserve the original file outside Git unless redistribution is legally permitted.

### 2. Extract multimodal content

- Prefer native text when its encoding, reading order, and quality pass documented checks.
- Apply OCR to image-only or defective regions/pages; do not OCR every page merely for consistency.
- For mixed pages, retain region-level method provenance.
- Detect columns, headings, paragraphs, notes, captions, tables, and figures before reconstructing reading order.
- Export visual assets with page, bounding box, caption association, checksum, and extraction method.
- Preserve raw output alongside normalized text so normalization is auditable.

The pipeline must be benchmarked on representative native, scanned, mixed-layout, multilingual, footnote-heavy, and image-heavy pages. A visual contact sheet is useful for audit, but manual review of a sample is still required.

### 3. Reconstruct document structure

Use PDF bookmarks, table-of-contents entries, heading detection, typography, and page ranges as evidence. Store both:

- the detected structural hierarchy; and
- how each assignment was produced and reviewed.

A page-to-chapter mapping is an inference unless explicitly encoded by the PDF. It must carry a method and review status. Retrieval chunks should be sentence-aware, remain within structural boundaries where possible, and overlap only under a documented policy. Arbitrary ten-page chunks are not suitable as the final claim-extraction unit.

### 4. Extract candidate claims

The research should compare at least these conditions on the same annotated sample:

- a transparent rule-based baseline;
- zero-shot structured LLM extraction;
- few-shot structured LLM extraction using approved examples;
- optionally, a hybrid pipeline in which rules propose or filter candidates and an LLM structures them.

The LLM receives bounded source spans, the claim definition, extraction rules, and a versioned JSON Schema. It returns candidate fields such as proposition, attribution, participants, predicate, time, place, modality, and evidence. The system then adds deterministic provenance fields; the LLM must not invent page numbers, hashes, offsets, or validation results.

Model confidence is not accepted as proof. If confidence is retained, its meaning and calibration method must be documented.

### 5. Validate and review

Validation occurs at three distinct levels:

1. **Structural validation:** valid JSON, required fields, controlled values, referential integrity, unique IDs, and schema version.
2. **Source validation:** evidence is an exact substring of the referenced span/page; offsets reproduce the quote; IDs resolve; chapter range is consistent; source hash matches.
3. **Semantic validation:** claim is entailed by the quotation, atomic, correctly attributed, and preserves negation, modality, temporality, and uncertainty.

A model-based judge may assist level 3, but it must use a separate prompt/run record and be evaluated against human judgments. It cannot replace the human gold sample. Historical verification, when required, is a fourth and separate layer based on external evidence.

## Canonical Data Model

The project will use one versioned logical model with separate record types. Canonical machine-readable data should be newline-delimited JSON (`.jsonl`) for streaming and reviewable JSON Schema files for validation. Human-facing Markdown, CSV, spreadsheets, and reports are generated views, not canonical sources.

### Core record types

| Record | Purpose | Required traceability |
| --- | --- | --- |
| `book` | Bibliographic, file, rights, and run-level metadata | `book_id`, source hash |
| `page` | Page geometry, labels, method, and quality | `book_id`, page index |
| `block` | Layout object such as paragraph, heading, table, figure, or caption | Page and bounding box |
| `span` | Addressable source text for evidence and annotation | Page, offsets, text hash |
| `chunk` | Derived retrieval/model input | Ordered source span IDs |
| `asset` | Extracted image, table, or other non-text object | Page, bounding box, checksum |
| `claim` | Atomic attributed proposition | One or more evidence span references |
| `frame_annotation` | Frame label applied under a versioned codebook | Claim/span, annotator or model run |
| `verification` | Result of a specific check or review | Target ID, method, reviewer/run, status |
| `run` | Reproducibility information | Code, model, prompt, parameters, timestamp |

### Minimum extraction provenance

Every page, span, and asset must retain enough information to answer:

```text
Which exact source file?
Which physical PDF page and printed page label?
Which part, chapter, and section, and how was that mapping obtained?
Which text/image region and reading-order position?
Was it native extraction, OCR, or hybrid?
Which tool, model, version, settings, schema, and run produced it?
Was it normalized, and can the raw representation still be recovered?
What checks passed, failed, or await review?
```

### Minimum claim fields

A claim schema should contain at least:

```json
{
  "schema_version": "0.1.0",
  "record_type": "claim",
  "claim_id": "claim:book-id:000001",
  "book_id": "book:example",
  "claim_text": "An atomic, source-faithful proposition.",
  "claim_type": "reported",
  "attribution": {
    "speaker_entity_id": "entity:example-person",
    "speaker_name_as_written": "Example Person",
    "source_role": "interviewee"
  },
  "participants": [
    {
      "entity_id": "entity:example-organization",
      "name_as_written": "Example Organization",
      "semantic_role": "actor"
    }
  ],
  "predicate": {
    "surface_form": "stated",
    "normalized_relation": "COMMUNICATED"
  },
  "time": [],
  "locations": [],
  "quantities": [],
  "polarity": "affirmed",
  "modality": "asserted",
  "certainty": "unspecified",
  "evidence": [
    {
      "span_id": "span:book-id:000123",
      "quote": "Exact text copied from the source span.",
      "page_index": 42,
      "printed_page_label": "27",
      "char_start": 120,
      "char_end": 163
    }
  ],
  "structure": {
    "part_id": null,
    "chapter_id": "chapter:book-id:03",
    "section_id": null
  },
  "extraction": {
    "method": "llm_zero_shot",
    "run_id": "run:example",
    "prompt_version": "claim-prompt-0.1.0",
    "model": "record-the-exact-model-version"
  },
  "verification": {
    "schema_valid": true,
    "exact_quote_match": true,
    "offset_match": true,
    "semantic_status": "pending",
    "human_review_status": "pending"
  }
}
```

This example is a design target, not a finalized schema. Entity normalization must preserve the original surface form. Unknown values should be `null` or empty arrays according to the schema; they must not be guessed.

## LLM and Hypergraph Views

### LLM / RAG view

RAG consumes source-faithful chunks and structured metadata. Each retrievable unit should include stable IDs, text, hierarchy, page range, book metadata, and links to source spans. Responses must cite those IDs and quotations.

LLM fine-tuning or post-training examples are derived from reviewed records, for example:

```json
{"messages":[{"role":"system","content":"Versioned extraction instruction"},{"role":"user","content":"Bounded source span"},{"role":"assistant","content":"Validated structured claim JSON"}],"metadata":{"book_id":"book:example","span_ids":["span:book-id:000123"],"schema_version":"0.1.0"}}
```

Training, validation, and test splits must be separated at the book or chapter level as required by the experiment, with leakage checks and documented licensing.

### Hypergraph view

A hypergraph can represent an n-ary claim connecting multiple participants, evidence, time, place, and concepts without reducing it prematurely to independent subject-predicate-object triples.

- **Nodes** represent entities, events, places, times, concepts, books, and source spans.
- **Hyperedges** represent claims or events.
- **Incidences** connect nodes to hyperedges with roles such as actor, affected entity, location, time, source, or witness.

At small scale these can be JSONL. At larger scale they should be exported as typed tables such as `nodes.parquet`, `hyperedges.parquet`, and `incidences.parquet`. Parquet is a compact analytical export; it does not replace the canonical grounded records.

Both RAG and hypergraph views must point back to the same `claim_id`, `span_id`, and `book_id` values. This permits a fair comparison and prevents two incompatible datasets from being mistaken for two methods.

## Evaluation Plan

Evaluation will use a versioned, double-annotated sample selected across books, chapters, page types, languages, extraction methods, and claim densities. Disagreements should be adjudicated and retained for analysis.

### Extraction evaluation

- character error rate (CER) and word error rate (WER) against manually transcribed pages;
- reading-order and block-type accuracy;
- heading and chapter-boundary precision, recall, and F1;
- figure/table/caption detection precision and recall;
- page completeness, empty-page errors, and duplicate-text rate;
- provenance and exact-offset validity.

### Claim extraction evaluation

- claim identification precision, recall, and F1;
- exact or partial evidence-span agreement;
- attribution and participant-role accuracy;
- relation, time, location, polarity, modality, and uncertainty accuracy;
- atomicity, completeness, and source-fidelity ratings;
- hallucination and unsupported-field rate;
- inter-annotator agreement and adjudication rate.

Matching criteria for claims must be declared in advance because semantically equivalent claims may use different wording.

### RAG evaluation

- Recall@k, precision@k, mean reciprocal rank, and nDCG where appropriate;
- citation correctness and evidence coverage;
- answer faithfulness to retrieved evidence;
- performance across single-book, cross-book, and conflicting-source questions;
- latency, token usage, and cost.

### Hypergraph evaluation

- entity-resolution and incidence-role accuracy;
- claim-to-hyperedge conversion validity;
- provenance path completeness;
- retrieval/query coverage for the same test questions used by RAG;
- contradiction or narrative-pattern discovery with human validation;
- construction time, storage, query latency, and interpretability.

No approach should be described as "better" without a predeclared task, baseline, metric, test set, and uncertainty analysis.

## Planned Repository Layout

```text
RNH-LLM-VS-HYPERGRAPH/
|-- README.md
|-- LICENSE
|-- CITATION.cff
|-- pyproject.toml
|-- .env.example
|-- configs/
|   |-- extraction/
|   |-- claims/
|   `-- evaluation/
|-- docs/
|   |-- research_protocol.md
|   |-- annotation_guide.md
|   |-- frame_codebook.md
|   |-- data_dictionary.md
|   `-- decisions/
|-- schemas/
|   |-- book.schema.json
|   |-- page.schema.json
|   |-- span.schema.json
|   |-- claim.schema.json
|   |-- frame_annotation.schema.json
|   `-- verification.schema.json
|-- src/rnh/
|   |-- ingest/
|   |-- extract/
|   |-- structure/
|   |-- claims/
|   |-- validate/
|   |-- rag/
|   |-- hypergraph/
|   `-- export/
|-- prompts/
|-- tests/
|   |-- fixtures/
|   |-- unit/
|   `-- integration/
|-- scripts/
|-- notebooks/
|-- reports/
`-- data/
    |-- README.md
    |-- raw/          # ignored; original PDFs
    |-- interim/      # ignored; extraction artifacts
    `-- processed/    # ignored or controlled release only
```

Only directories needed by implemented work should be added. Notebooks are for exploration; reusable pipeline logic belongs in `src/rnh/`.

## Team Workflow

`main` is the integration branch and should remain reproducible.

1. Create an issue describing the research or implementation change and its acceptance criteria.
2. Branch from current `main` using names such as `docs/claim-definition`, `feat/pdf-ingest`, or `experiment/zero-shot-baseline`.
3. Keep code, schema, prompt, config, and tests for one change together.
4. Open a pull request and request review from at least one teammate.
5. Record protocol/schema decisions in `docs/decisions/`; do not silently change field meaning.
6. Merge only after automated checks pass and generated data has not been accidentally committed.
7. Tag important dataset and experiment versions.

Changes to claim definitions, frame labels, schema semantics, gold annotations, or evaluation metrics require team review. Prompt changes require a new prompt version and experiment run rather than overwriting prior results.

## Reproducibility Requirements

Every experiment should record:

- Git commit and dirty/clean state;
- input book IDs and SHA-256 hashes;
- dataset and schema versions;
- extraction engines and OCR model/language packs;
- LLM provider, exact model/version, prompt version, temperature, seed where supported, and decoding settings;
- package and system versions;
- start/end timestamps and run ID;
- validation results, failures, retries, and human review status;
- metric implementation and evaluation-set version.

Randomness, model updates, and nondeterministic hosted APIs must be acknowledged in the analysis.

## Copyright, Privacy, and Security

Do not commit:

- copyrighted full-text PDFs or OCR/native-text reproductions without permission;
- large generated datasets that reproduce protected books;
- API keys, `.env` files, tokens, or credentials;
- private chats, supervisor correspondence, or personal information;
- interview material without the required consent and access controls.

The private status of a Git repository does not grant redistribution rights and does not make committed secrets safe. Store restricted sources and outputs in approved access-controlled storage. Git should contain code, schemas, prompts, small lawful fixtures, checksums, aggregate metrics, and documentation. Use `.gitignore`, secret scanning, and an explicit data-access record.

## Current Status

This repository is being re-established as the canonical research project. Previous experiments demonstrated native/OCR PDF extraction, page-level metadata, chapter mapping, rule-based candidates, structured LLM claim candidates, grounding checks, image audits, RAG preparation, and hypergraph exports across separate working repositories.

Those artifacts should be treated as **prototypes and demonstrations** until they are migrated selectively, tested against the agreed schemas, and evaluated on a human-annotated benchmark. No existing claim count, confidence score, chapter assignment, frame label, or verification label should be reported as a thesis result solely because a script produced it.

## Research Roadmap

- [ ] Confirm research question, unit of analysis, scope, and meaning of "debiasing" with the supervisor.
- [ ] Approve operational definitions for extraction, claim, frame, grounding, and truth.
- [ ] Write the annotation guide and adjudication procedure.
- [ ] Finalize version `1.0.0` of the canonical schemas and data dictionary.
- [ ] Add secure data handling, `.gitignore`, environment, and dependency setup.
- [ ] Build the PDF diagnostic and layout-aware extraction baseline.
- [ ] Construct and double-annotate a representative gold sample.
- [ ] Benchmark native extraction and OCR/layout alternatives.
- [ ] Implement rule, zero-shot, few-shot, and hybrid claim baselines.
- [ ] Validate grounding deterministically and semantic fidelity against humans.
- [ ] Build RAG and hypergraph exports from identical canonical records.
- [ ] Define shared comparison tasks and evaluate both representations.
- [ ] Run ablations, error analysis, reproducibility checks, and cost analysis.
- [ ] Freeze the evaluated dataset, code, prompts, configurations, and report.

## Decisions Required From the Supervisor

Before large-scale extraction or annotation, confirm:

1. What is the exact thesis objective: narrative comparison, bias detection, retrieval, claim verification, or another task?
2. Is the unit of analysis a sentence, proposition, event, passage, chapter, frame, or combination?
3. Which claim definition and claim types are theoretically justified?
4. What does "frame" mean in this research, and which codebook or theory will be used?
5. Is the target book-faithful representation, external historical verification, or both?
6. Which books, languages, editions, and modalities are in scope?
7. What constitutes the gold standard, and who will annotate and adjudicate it?
8. Which LLM and hypergraph tasks are comparable, and which metrics determine success?
9. What copyrighted source material and derived text may be stored or shared?

## Research Basis and Standards

The definitions above are supported as follows; the citations do not remove the need for a project-specific annotation guide:

- [Daxenberger et al. (2017), *What is the Essence of a Claim?*](https://doi.org/10.18653/v1/D17-1218) establishes that claim conceptualizations differ across datasets. It supports explicitly defining our task rather than claiming one universal definition.
- [Min et al. (2023), *FActScore*](https://doi.org/10.18653/v1/2023.emnlp-main.741) motivates decomposing complex text into atomic factual units, but our records additionally preserve historical-source attribution and uncertainty.
- [Thorne et al. (2018), *FEVER*](https://doi.org/10.18653/v1/N18-1074) demonstrates claim classification using recorded textual evidence. Its `Supported`, `Refuted`, and `NotEnoughInfo` task is not identical to book-faithful extraction.
- [Pareti (2016), *PARC 3.0: A Corpus of Attribution Relations*](https://lrec.elra.info/proceedings/lrec2016/summaries/619.html) motivates representing attribution source, cue, and content instead of treating every statement as the book author's own voice.
- [Entman (1993), *Framing: Toward Clarification of a Fractured Paradigm*](https://doi.org/10.1111/j.1460-2466.1993.tb01304.x) supplies the starting framing formulation. A specific frame codebook still has to be selected or developed and validated.

The implementation should reuse established data and document standards where they fit:

- [JSON Schema](https://json-schema.org/) for machine-validatable records;
- [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/) for annotation bodies, targets, and selectors;
- [W3C PROV-O](https://www.w3.org/TR/prov-o/) for entities, activities, agents, and derivation provenance;
- [IIIF Presentation API](https://iiif.io/api/presentation/3.0/) for page/canvas and media-region concepts;
- [TEI Guidelines](https://tei-c.org/release/doc/tei-p5-doc/en/html/) for scholarly document and text structure;
- [Apache Parquet](https://parquet.apache.org/) for large analytical tables;

These references were checked against their official DOI, ACL Anthology, W3C, IIIF, TEI, or project pages on **2026-09-30**. A citation verifies what influenced a definition; it does not prove that our operationalization is valid. Adoption of any standard must be documented in the data dictionary, including which parts are implemented and where local extensions are used.

## Citation

Until `CITATION.cff` and a release are added, cite the repository using its title, contributors, commit hash, and access date. Dataset and experiment reports must additionally cite the exact schema, prompt, configuration, model, and source-hash manifest used.

---

The aim is not a vaguely "perfect" pipeline. The aim is a documented, benchmarked, reproducible, and defensible research system whose outputs can always be traced back to evidence.
