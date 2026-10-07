# Proposed Thesis Methodology

**Working title:** Source-Grounded Comparative Analysis of Competing Historical Narratives: Evaluating LLM-RAG, Provenance-Aware Hypergraphs, and a Hybrid Approach on Accounts of the 1971 Bangladesh War

**Status:** proposal for team and supervisor approval
**Version:** 0.1.0
**Date:** 2026-09-30

## Executive Recommendation

The most defensible thesis is not a project that attempts to solve OCR, historical truth, bias removal, framing theory, claim extraction, fine-tuning, RAG, and hypergraphs as equal independent contributions.

The recommended thesis contribution is:

> Build one source-grounded corpus of claims from competing historical books, then evaluate how text-based LLM-RAG, provenance-aware hypergraph retrieval, and a hybrid system support cross-book historical narrative analysis.

Extraction remains essential, but it is evaluated as the data-production method. Claim and frame annotations remain book-faithful. External historical truth verification is explicitly outside the primary experiment unless the supervisor adds it as a separate task.

## 1. Why This Is Better Than the Current Direction

The current work contains useful extraction, OCR, claim, RAG, and hypergraph prototypes, but it risks becoming too broad. It also risks comparing unlike objects:

- an LLM is a model or inference component;
- RAG is a retrieval-plus-generation system;
- a hypergraph is a structured representation;
- claim extraction is a data-creation task;
- framing is a separate theoretical annotation task;
- historical verification requires external evidence.

Comparing a raw LLM directly with a raw hypergraph is a category error. A fair thesis compares complete systems that perform the same tasks using the same corpus and evaluation set.

The proposed comparison is:

| System | Representation and method | Main strength expected |
| --- | --- | --- |
| A: Text RAG | Source spans indexed with lexical/vector retrieval; LLM produces cited responses | Semantic flexibility and natural-language synthesis |
| B: Hypergraph | Reviewed claims, entities, roles, time, location, attribution, and evidence represented as nodes/hyperedges/incidences | Traceability and structured cross-book comparison |
| C: Hybrid | Hypergraph and text retrieval provide evidence to an LLM | Combined structured reasoning and readable synthesis |

The systems are evaluated on identical questions, books, evidence, splits, and source-fidelity rules.

## 2. Research Scope

### Primary scope

- English-language historical books concerning the 1971 Bangladesh War, subject to supervisor and rights approval.
- Native-text, scanned, and mixed PDF extraction.
- Atomic source-attributed book claims.
- Exact quotation and page/span grounding.
- Cross-book retrieval and comparison.
- LLM-RAG, hypergraph, and hybrid system evaluation.
- Human evaluation of source fidelity, attribution, and analytical usefulness.

### Secondary scope

- Narrative framing only after a codebook and annotation pilot are approved.
- Multimodal inventory and source linkage for photographs, maps, tables, and captions.
- Claim-relation candidates such as equivalent, conflicting, qualifying, or differently attributed.

### Outside the primary scope

- Declaring which book is objectively historically true.
- Automatically resolving historical controversies.
- Claiming that the system removes political or historical bias.
- Full semantic interpretation of every image.
- Fine-tuning before sufficient adjudicated training data exists.
- Treating model confidence, OCR confidence, or exact quote matching as truth.

The term **perspective-aware comparative analysis** is preferable to **historical debiasing** unless the supervisor defines bias, the target norm, and a measurable debiasing outcome.

## 3. Proposed Research Questions

### Main research question

How do source-grounded LLM-RAG, provenance-aware hypergraph retrieval, and a hybrid approach differ in their ability to retrieve, compare, and explain claims across competing historical narratives?

### Supporting questions

**RQ1:** How accurately can heterogeneous historical PDFs be transformed into source-grounded text, structure, and media records?

**RQ2:** How accurately can rule-based, zero-shot LLM, few-shot LLM, and hybrid methods identify atomic claims while preserving attribution, participants, time, place, polarity, uncertainty, and exact evidence?

**RQ3:** How do text RAG and hypergraph retrieval compare on evidence retrieval, citation correctness, cross-book claim alignment, provenance, and human interpretability?

**RQ4:** Does hypergraph-guided text retrieval improve an LLM's evidence coverage and citation fidelity compared with text-only RAG?

**RQ5, optional:** Can a supervisor-approved narrative-framing codebook be applied reliably across books and perspectives?

RQ1 and RQ2 support the main comparison. They should not each expand into an unrelated thesis.

## 4. Proposed Hypotheses

These hypotheses must be approved before final evaluation:

- **H1:** Text RAG retrieves semantically varied passages effectively but produces more unsupported synthesis or attribution errors than structured retrieval.
- **H2:** Hypergraph retrieval provides stronger provenance and role-based comparison but misses implicit or linguistically varied claims when entity and relation extraction is incomplete.
- **H3:** The hybrid system achieves better evidence coverage and citation fidelity than text-only RAG while retaining readable responses.
- **H4:** Extraction and attribution errors disproportionately harm cross-book comparison even when aggregate character accuracy appears high.

Null hypotheses and statistical tests should be declared with the final metric plan.

## 5. Units of Analysis

The study must not use one unit for every stage.

| Stage | Unit |
| --- | --- |
| PDF extraction | Page and layout block |
| Source grounding | Paragraph or sentence span |
| Claim annotation | Atomic attributed proposition |
| Frame annotation | Claim or bounded passage, declared explicitly |
| Hypergraph | Claim hyperedge plus role-bearing incidences |
| Retrieval evaluation | Question, relevant source spans, and relevant claims |
| System response evaluation | Answer plus cited evidence and provenance path |

Arbitrary ten-page chunks are not analytical units. Model inputs may contain bounded context, but every accepted claim must identify the exact target evidence span.

## 6. Canonical Data Principle

Create one versioned logical corpus. Do not manually maintain separate LLM and hypergraph truths.

Canonical records:

```text
books
pages
blocks
spans
assets
claims
entities and mentions
frame annotations, if approved
claim relations
verification and review
runs
```

Canonical serialization is JSONL validated by JSON Schema. Human reports are generated as Markdown or CSV. Hypergraph tables and LLM training examples are derived from reviewed canonical records.

The detailed contract is defined in [the data schema guide](README.md).

## 7. Phase A: Corpus and Governance

### Corpus selection

Select books using documented inclusion criteria:

- direct relevance to the 1971 conflict;
- historical, memoir, diplomatic, military, journalistic, or scholarly account;
- identifiable author/source and edition;
- sufficient legal access for research processing;
- diversity of author position, institutional affiliation, genre, and national perspective;
- usable English text or an approved multilingual protocol.

Do not call a corpus balanced merely because it contains an equal number of books. Record what perspectives and genres are represented and what remains absent.

### Source registry

For every PDF record:

- source SHA-256;
- stable book ID;
- title, creators, edition, publisher, year, language, and genre;
- source and access provenance;
- copyright and redistribution status;
- page count and PDF characteristics;
- inclusion rationale.

Restricted PDFs and full extracted text remain outside Git in access-controlled storage.

## 8. Phase B: Extraction Benchmark

### Candidate extraction conditions

| ID | Condition |
| --- | --- |
| E0 | PyMuPDF native text and block extraction |
| E1 | Tesseract/OCRmyPDF-style conventional OCR baseline |
| E2 | PaddleOCR PP-StructureV3 OCR and layout extraction |
| E3 | Docling structured-document extraction |
| E4 | Adaptive router selecting validated routes by page/region |

Existing code is useful evidence but does not establish a winner. The production route is selected only after a controlled benchmark.

### Gold extraction sample

Build a stratified sample containing:

- clean born-digital prose;
- suspicious native text layers;
- clean and degraded scans;
- multi-column, quotation-heavy, and footnote-heavy pages;
- contents, index, bibliography, and front matter;
- tables, maps, photographs, and captions;
- every relevant language/script and difficult typography type.

Two reviewers create or verify transcription, reading order, block types, headings, captions, and meaningful visual assets. Preserve unreadable regions as uncertainty rather than guessing.

### Extraction metrics

- character error rate and word error rate;
- person, organization, location, date, and quantity accuracy;
- reading-order accuracy;
- block-type and heading precision/recall/F1;
- chapter-boundary precision/recall/F1;
- meaningful asset/caption precision and recall;
- page coverage, empty-page, duplicate-text, and failure rates;
- exact offset and hash validity;
- runtime, hardware, memory, storage, and manual-review cost.

Report per-book and per-page-type results, not only one corpus-wide average.

### Recommended production extraction

Use an adaptive page/region pipeline after benchmarking:

1. Diagnose the native text layer, image coverage, encoding, layout, rotation, and script.
2. Preserve valid native text and coordinates.
3. Apply OCR only to defective or image-only pages/regions.
4. Use layout-aware extraction for columns, tables, footnotes, captions, and mixed pages.
5. Preserve raw and normalized text.
6. Produce stable page, block, span, and asset IDs.
7. Run deterministic schema, reference, hash, offset, and coverage checks.
8. Review all failures/flags plus a stratified sample of successful pages.

## 9. Phase C: Claim Annotation Benchmark

### Operational claim definition

A claim is one proposition that an identifiable source presents as asserted, reported, remembered, inferred, disputed, negated, or uncertain. It must preserve source attribution and stance and point to exact evidence.

Do not convert:

- questions;
- headings;
- isolated names/topics;
- bibliography entries;
- publisher text;
- incomplete fragments;
- unasserted background supplied only by the extraction model.

### Gold annotation

Select passages across books, chapters, genres, extraction routes, claim density, and attribution complexity. Two annotators independently mark:

- claim boundaries and atomicity;
- exact evidence boundaries;
- attribution chain;
- claim kind, polarity, and epistemic status;
- predicate and participant roles;
- time, location, and quantities;
- approved narrative/frame annotations, if in scope;
- source fidelity and uncertainty.

Adjudicate disagreements and retain pre-adjudication annotations for agreement analysis.

### Compared claim extractors

| ID | Method | Purpose |
| --- | --- | --- |
| C0 | Transparent deterministic rules | Reproducible lower baseline |
| C1 | Zero-shot LLM with strict structured output | General semantic baseline |
| C2 | Few-shot LLM using development examples | Tests benefit of approved examples |
| C3 | Hybrid rules plus LLM structuring/filtering | Tests complementary strengths |
| C4, optional | Fine-tuned model | Only if enough adjudicated training data exists |

The LLM receives a target paragraph or bounded passage plus clearly separated local context. It proposes semantic fields only. Code attaches source IDs and verifies quotations and offsets.

### Claim metrics

- claim detection precision, recall, and F1;
- exact and overlap-based evidence boundary scores;
- exact grounding pass rate;
- hallucination/unsupported-field rate;
- atomicity and duplicate rates;
- attribution-chain accuracy;
- predicate and participant-role accuracy;
- polarity and epistemic-status accuracy;
- time, location, quantity, and entity accuracy;
- source-fidelity human rating;
- performance by book, claim kind, speaker type, and extraction method.

Model self-confidence is not an evaluation metric unless calibrated against held-out human labels.

## 10. Phase D: Narrative Framing

Framing is optional until theoretically approved. The existing nine values should not immediately be treated as one validated frame enum because they mix topics, conflict characterizations, and causal/problem frames.

Recommended dimensions:

```text
topics
conflict_characterizations
frame_functions
```

Possible frame functions adapted from framing theory:

```text
problem_definition
causal_attribution
responsibility_attribution
moral_evaluation
treatment_recommendation
```

Use a hybrid codebook-development procedure:

1. Begin from approved theory and the research question.
2. Open-code a stratified development sample.
3. Merge synonyms and separate mixed abstraction levels.
4. Define every label with inclusion/exclusion rules and examples.
5. Continue sampling until the agreed saturation rule is met.
6. Double-annotate a pilot and measure agreement per label.
7. Revise, merge, or remove unreliable labels.
8. Freeze and version the codebook before final annotation.

Do not infer a narrative frame from one keyword. Frame annotations must identify their target and supporting passage.

## 11. Phase E: Entities, Claims, and Relations

### Entity representation

Preserve both:

- source mention, exactly or conservatively represented;
- optional canonical entity ID assigned during entity resolution.

Never overwrite source wording with normalization. Entity merges should record method, confidence meaning, review state, and alternatives.

### Claim relations

Potential cross-book relations:

```text
semantically_equivalent
supports
contradicts
qualifies
different_attribution
different_quantity
different_time
different_location
```

Automated systems should initially call these `relation_candidates`. Logical contradiction is difficult and must not be inferred simply because wording or emphasis differs.

Create an adjudicated relation sample for evaluation.

## 12. Phase F: Hypergraph Representation

Recommended model:

- a reviewed claim is a hyperedge;
- people, organizations, groups, places, times, events/concepts, books, and source spans are typed nodes;
- incidences connect nodes to claim hyperedges using roles;
- hyperedge attributes preserve claim text, polarity, epistemic status, attribution, and verification state.

Example incidence roles:

```text
actor
affected_entity
object
beneficiary
witness
asserted_by
reported_by
location
time
evidenced_by
contained_in_book
```

Canonical IDs must survive export to:

```text
nodes.parquet
hyperedges.parquet
incidences.parquet
claim_relations.parquet
```

The hypergraph is a derived representation. It must be regenerable from reviewed source and claim records.

## 13. Phase G: Retrieval Systems

### System A: Text RAG

Index source spans and optionally reviewed claim text using:

- lexical retrieval baseline such as BM25;
- embedding retrieval;
- hybrid lexical/vector retrieval;
- optional reranking.

Chunks remain section-aware and preserve source-span membership. Answers must cite book, page, and span IDs and distinguish sources rather than blending them into one unattributed narrative.

### System B: Hypergraph retrieval

Support structured queries such as:

- claims involving a given actor, event, place, or period;
- how different books attribute responsibility;
- claims sharing participants but differing in quantity or stance;
- provenance path from answer to claim, evidence, page, and book;
- candidate narrative differences across authors.

Responses may use templates so the system can be evaluated without an LLM confound.

### System C: Hybrid retrieval and generation

Retrieve both:

- relevant source passages;
- relevant hypergraph neighborhoods and provenance paths.

Provide these to an LLM under a strict citation and source-separation instruction. This tests whether structure improves grounded synthesis rather than assuming it does.

## 14. Shared Evaluation Tasks

Create a test set of questions with adjudicated relevant spans, claims, entities, and acceptable answer elements.

Question categories:

- single-source factual retrieval;
- source attribution;
- cross-book claim comparison;
- actor/responsibility comparison;
- time/place/quantity comparison;
- conflicting or qualifying account retrieval;
- narrative characterization or framing, if approved;
- questions with insufficient evidence.

Each question must specify whether it asks **what a book says** or requests **external historical truth**. The primary systems answer the former.

## 15. System Evaluation

### Retrieval metrics

- Recall@k and Precision@k;
- mean reciprocal rank;
- nDCG where graded relevance is available;
- claim and source-span coverage;
- perspective/source coverage;
- duplicate retrieval rate.

### Answer metrics

- citation correctness;
- citation completeness;
- source faithfulness;
- attribution correctness;
- unsupported statement rate;
- preservation of disagreement and uncertainty;
- answer completeness against gold elements;
- human usefulness and interpretability.

### Hypergraph-specific metrics

- node/entity resolution accuracy;
- incidence-role accuracy;
- claim-to-hyperedge conversion validity;
- provenance path completeness;
- structured query answer accuracy;
- candidate relation precision/recall.

### Operational metrics

- indexing/construction time;
- query latency;
- memory and storage;
- model tokens and monetary cost;
- manual-review time;
- failure and retry rates.

Do not combine all metrics into one score without a preregistered rationale.

## 16. Experimental Controls

- Use the same canonical corpus for all systems.
- Split by book, author, or chapter as required to prevent leakage; do not randomly split adjacent sentences across train and test.
- Freeze source files by SHA-256.
- Freeze schema, prompts, models, embedding models, code commits, and settings.
- Keep development and final test questions separate.
- Use identical query sets and relevance judgments.
- Record nondeterministic API/model behavior and rerun a stability sample.
- Report failed cases rather than silently removing them.
- Perform ablations for text-only, claim-only, graph-only, and hybrid evidence where feasible.

## 17. Required Human Evaluation

Automated validators can prove identity and exact substring relationships. They cannot prove that a claim preserves meaning or that a system fairly represents competing accounts.

Required human work:

- extraction gold pages;
- double-annotated claim benchmark;
- frame pilot if frames remain in scope;
- cross-book claim-relation sample;
- retrieval relevance judgments;
- response source-fidelity and usefulness judgments.

Report annotator instructions, training, independence, agreement, adjudication process, and conflicts of interest.

## 18. What to Reuse From Existing Work

### Reuse from `local_book_extractor`

- source hashing and stable source identity;
- page and span records with exact offsets;
- deterministic grounding and schema validation concepts;
- visual-audit package generation;
- claim review and RAG/hypergraph prototype components;
- separation of grounding, source fidelity, and historical truth.

### Reuse from Ammar's repository

- PaddleOCR PP-StructureV3 integration;
- orientation, unwarping, table/layout, and OCR configuration;
- native-versus-OCR routing concept;
- image preprocessing and visual-page probing;
- figure extraction and failure logging.

### Rewrite or replace

- fixed ten-page chunking;
- claims without evidence quotes and offsets;
- IDs not tied to source identity;
- resume behavior that loses extraction provenance;
- unvalidated chapter propagation;
- prose-only verification claims;
- free-text frame fields;
- hardcoded paths/models;
- unpinned environments and missing tests.

Migrate components selectively into the canonical repository instead of merging generated outputs and legacy scripts wholesale.

## 19. Recommended Repository Structure

```text
RNH-LLM-VS-HYPERGRAPH/
|-- README.md
|-- pyproject.toml
|-- configs/
|-- docs/
|   |-- README.md
|   |-- THESIS_METHODOLOGY_PROPOSAL.md
|   |-- EXTRACTION_METHOD_GUIDE.md
|   |-- annotation_guide.md
|   |-- frame_codebook.md
|   `-- decisions/
|-- schemas/
|-- prompts/
|-- src/rnh/
|   |-- ingest/
|   |-- extract/
|   |-- structure/
|   |-- claims/
|   |-- annotation/
|   |-- validate/
|   |-- entities/
|   |-- rag/
|   |-- hypergraph/
|   |-- evaluate/
|   `-- export/
|-- tests/
|-- data/
|   |-- README.md
|   |-- raw/          # ignored/restricted
|   |-- interim/      # ignored/restricted
|   `-- processed/    # ignored or controlled release
`-- reports/
```

## 20. Staged Implementation Plan

### Stage 1: Freeze protocol

- approve thesis objective and system comparison;
- approve claim definition and truth boundary;
- approve core schema v1 and annotation guide;
- decide whether framing remains in scope.

### Stage 2: Build benchmark infrastructure

- migrate source registry, schema validators, and run manifests;
- implement adaptive extraction candidates;
- create extraction gold sample and benchmark;
- select/freeze production extraction route.

### Stage 3: Build claim benchmark

- implement annotation/review interface or review sheets;
- double-annotate and adjudicate development/test passages;
- evaluate C0-C3 claim extractors;
- freeze accepted claims and evidence.

### Stage 4: Build representations

- resolve entities on the reviewed subset;
- create text/RAG index;
- create hypergraph export and query layer;
- create optional hybrid retriever.

### Stage 5: Evaluate systems

- freeze questions and relevance judgments;
- run systems A, B, and C;
- conduct automatic and human evaluation;
- perform error analysis and ablations;
- archive exact runs and reports.

### Stage 6: Thesis reporting

- report methods before results;
- separate prototype observations from evaluated findings;
- report uncertainty and negative results;
- publish lawful schemas, code, prompts, small fixtures, and aggregate metrics.

## 21. Suggested Team Responsibilities

With three researchers, assign primary ownership while requiring cross-review:

| Area | Primary responsibility | Required cross-review |
| --- | --- | --- |
| Corpus, extraction, provenance | Member A | Member B audits gold pages |
| Claims, annotation, LLM/RAG | Member B | Member C reviews schema and samples |
| Hypergraph, entity resolution, evaluation | Member C | Member A verifies provenance paths |

All members should annotate a shared calibration set. No member should be the sole creator and evaluator of the same gold labels.

## 22. Minimum Viable Thesis and Extensions

### Minimum viable thesis

- one approved English-language corpus;
- adaptive, validated extraction;
- reviewed atomic claims with exact evidence;
- text RAG and hypergraph systems;
- shared retrieval/comparison questions;
- source-grounding, retrieval, provenance, and human evaluation.

### Strong extension

- hybrid hypergraph-guided RAG;
- validated narrative-frame codebook;
- claim-relation classification;
- fine-tuning using adjudicated claim examples;
- multilingual extraction/analysis.

Complete the minimum thesis before adding extensions.

## 23. Decisions Required From the Supervisor

1. Is the primary objective retrieval/comparison of what books claim, or external historical verification?
2. Is the term `debiasing` theoretically and operationally justified, or should the study use `perspective-aware comparative analysis`?
3. Is framing central, optional, or outside the thesis?
4. Which books, languages, genres, and perspectives define the corpus?
5. What is the primary comparison task shared by text RAG and hypergraph systems?
6. What constitutes gold evidence and who may adjudicate it?
7. Which human and automatic metrics determine success?
8. What copyrighted text may be processed, retained, or shared?

## 24. Short Proposal for the Meeting

> We propose building one source-grounded corpus from competing historical accounts of the 1971 Bangladesh War. Every extracted claim will retain its speaker, participants, time, place, stance, exact quotation, page, and source-file identity. We will then compare three systems on identical historical-narrative questions: text-based LLM-RAG, provenance-aware hypergraph retrieval, and a hybrid system. The study will evaluate retrieval, citation fidelity, source coverage, structured comparison, provenance, cost, and human interpretability. It will represent what each book claims rather than automatically declaring historical truth. Extraction, claim extraction, and optional framing will each be benchmarked against human-reviewed samples before the final system comparison.

## Final Recommendation

Adopt this as the project direction:

```text
one corpus
one canonical schema
one human-reviewed benchmark
three comparable systems
shared tasks and metrics
explicit provenance and uncertainty
```

This is narrower than attempting every possible feature, but considerably stronger as a thesis: it is testable, reproducible, source-faithful, and capable of producing defensible findings.
