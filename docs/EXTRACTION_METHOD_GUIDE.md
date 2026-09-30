# Extraction Method and Evaluation Guide

**Project:** RNH: LLM vs Hypergraph  
**Status:** Proposed thesis protocol, version 0.1  
**Last reviewed:** 2026-09-30

This guide explains what the team has already tested, what those tests actually establish, how detailed book extraction should be, and how to select an extraction method for this thesis.

It does not declare a universal best PDF tool. The defensible conclusion from the current work is:

> Use an adaptive, layout-aware hybrid pipeline: preserve valid native PDF text, apply OCR only to pages or regions that need it, retain images and document structure, and evaluate each route against manually created ground truth.

## 1. Why Extraction Matters to This Thesis

The thesis compares LLM and hypergraph methods for analyzing competing historical narratives. Both methods must start from the same source-faithful representation. Otherwise, an apparent difference between the LLM and hypergraph may actually be caused by:

- a missing page;
- an OCR error in a person's name, date, location, or number;
- incorrect column or footnote reading order;
- an interviewee's words being attributed to the book's author;
- a chapter boundary being assigned incorrectly;
- a photograph, map, caption, or table being omitted;
- different chunks being supplied to each method.

Extraction is therefore part of the experimental method, not merely preprocessing. It should preserve what each book contains and where it occurs. It should not decide whether the book is historically correct.

## 2. What "Best Extraction Method" Means

For this project, the best method is the method or routing policy that performs best on a declared benchmark while preserving traceability. It is not the method that produces the longest text or the highest self-reported OCR confidence.

The decision must consider:

| Dimension | Question |
| --- | --- |
| Text accuracy | Are characters, words, names, dates, and quantities transcribed correctly? |
| Layout accuracy | Are columns, paragraphs, quotations, footnotes, captions, and tables in the correct order? |
| Structural accuracy | Are parts, chapters, sections, and page labels mapped correctly? |
| Multimodal coverage | Are meaningful figures, photographs, maps, tables, and captions represented? |
| Provenance | Can every span and asset be located on the exact source PDF page? |
| Reproducibility | Are engine versions, models, languages, parameters, hashes, and failures recorded? |
| Downstream utility | Do claim extraction, RAG, and hypergraph construction improve when using this output? |
| Resource cost | What are the runtime, memory, GPU, storage, and manual-review costs? |

A single overall score can hide important failures. Results should also be reported by page type, language/script, book, layout type, and extraction route.

## 3. Tests and Prototype Runs Already Completed

This section is an audit of existing work, not a claim that the methods have been scientifically compared.

### 3.1 Local source-grounding prototype

The `local_book_extractor` prototype processed six PDF inputs, including two different files representing Srinath Raghavan's book:

| Recorded result | Value |
| --- | ---: |
| PDF pages | 1,577 |
| Pages routed to native extraction | 1,537 |
| Pages routed to Tesseract OCR | 40 |
| Paragraph spans | 4,149 |
| Sentence spans | 26,176 |
| Unique embedded-image files reported across inputs | 19 |
| Rule-based claim candidates | 901 |

The extraction reports recorded passing page-count, hash/link, and span-offset integrity for all six inputs. These passes mean that records were structurally consistent and their stored offsets reconstructed their stored extracted text. They do **not** mean that every extracted character matched the visible page.

Three books received generated visual-audit packages. Each package selected 40 pages and included every OCR/quality-flagged page plus a sample of other pages. The contact sheets and CSVs were created, and embedded-raster inventory checks reported no manifest mismatches. However, all 120 human-review rows were still blank when checked. Therefore, the audit preparation was completed, but the human visual audit was not completed.

### 3.2 Automated code tests

The local prototype's test suite was rerun on 2026-09-30 using its project virtual environment:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Result: **13 tests passed**. The tests covered:

- exact source-span offset reconstruction;
- exclusion of non-content sections;
- rejection of ungrounded or non-verbatim claim fields;
- whitespace-normalized quotation alignment;
- a two-page PDF extraction, overwrite, schema-validation, and verification flow;
- visual-audit generation;
- claim and hypergraph export smoke paths;
- basic RAG retrieval and evaluation behavior.

A separate run with the system Python produced 12 passes and one environment failure because `jsonschema` was not installed in that interpreter. This was not an extraction-quality failure, but it demonstrates why the canonical repository needs a locked environment and CI.

### 3.3 PaddleOCR/PP-Structure prototype

A second prototype used PyMuPDF's native text route and PaddleOCR PP-StructureV3 for pages that did not pass its native-text threshold. Six recorded book runs completed with no page-processing failures in their logs:

| Recorded result | Value |
| --- | ---: |
| PDF pages | 1,834 |
| Pages reported as native | 1,794 |
| Pages routed away from native | 40 |
| Runs reporting completion | 6 |

The same outputs reported 1,281 media items, but this number includes extraction occurrences and pipeline artifacts. It is **not** a verified count of meaningful photographs or figures. Some files also had missing or unreliable PDF title/author metadata, showing that embedded metadata cannot be trusted without bibliographic review.

The prototype's separate chunk script concatenated every ten page files. That proved that bulk chunks could be generated, but ten-page boundaries are not suitable for the final thesis pipeline because they can cross chapters, speakers, quotations, and unrelated events.

### 3.4 Earlier canonical batch attempt

The previous canonical history at commit `94d685a` contains a PaddleOCR-based batch attempt over seven PDFs. Logs show two complete runs:

- 146 pages, of which 109 used the native route;
- 189 pages, of which 179 used the native route.

Several other logs stop before completion, and one run records failures on pages 304 and 305. These logs are useful failure evidence, but incomplete runs must not be counted as successful extraction experiments.

### 3.5 What has not yet been tested

The current evidence does not include:

- manually transcribed page ground truth;
- CER or WER comparisons between PyMuPDF, Tesseract, PaddleOCR, and another layout system;
- measured reading-order or chapter-boundary accuracy;
- human-verified figure, map, table, and caption recall;
- accuracy broken down by names, dates, locations, and quantities;
- a controlled downstream comparison using identical claim/RAG inputs;
- statistical testing or confidence intervals;
- a completed double-annotation study.

Consequently, we can identify a strong candidate architecture, but we cannot yet state that Tesseract, PaddleOCR, Docling, or any other engine is empirically best for this corpus.

## 4. Recommended Extraction Architecture

### 4.1 Use a cascade, not one engine for every page

```text
Register source and hash PDF
            |
            v
Diagnose each page and region
            |
   +--------+---------+----------------+
   |                  |                |
   v                  v                v
valid native      image-only       mixed/complex
text + layout       page              layout
   |                  |                |
   v                  v                v
PyMuPDF blocks    OCR baseline     layout-aware parser
and characters    + challenger     + regional OCR
   |                  |                |
   +------------------+----------------+
                      v
        canonical page/block/span/asset records
                      |
                      v
       deterministic checks + sampled human audit
```

The initial candidate set should be:

| Route | Candidate | Role in the experiment |
| --- | --- | --- |
| Native baseline | PyMuPDF | Preserve existing character layer, coordinates, blocks, and PDF metadata |
| OCR baseline | Tesseract, preferably through a controlled OCRmyPDF or direct page-render path | Reproducible conventional OCR baseline |
| Layout-aware challenger | PaddleOCR PP-StructureV3 | OCR plus layout/table/reading-order candidate for scans and complex pages |
| Document-layout challenger | Docling | Alternative structured-document conversion and layout/table pipeline |

The team should benchmark these candidates on the same page images and gold annotations before fixing the production route. Tool defaults, versions, and downloaded model identifiers must be frozen.

### 4.2 Diagnose before extracting

For every page, collect at least:

- native character and word count;
- percentage of replacement/control characters;
- suspiciously long tokens or repeated text;
- page image coverage;
- number and geometry of native text blocks;
- rotation and page dimensions;
- likely number of columns;
- embedded-image and vector-drawing counts;
- detected language/script;
- whether the page appears blank, front matter, body text, bibliography, index, plate, map, or table.

The existing `80 characters` or `20 words` thresholds are useful baseline features, not sufficient quality decisions. A corrupt hidden text layer can exceed either threshold. Routing should combine text quality, image coverage, layout complexity, and sampled visual comparison.

### 4.3 Native-text route

Use native extraction when the PDF contains a usable character layer and the page passes quality checks.

Required behavior:

1. Extract raw characters, words, blocks, bounding boxes, font cues, and reading-order candidates.
2. Preserve the raw engine output.
3. Create a conservative normalized version without silently changing names, dates, punctuation, or spelling.
4. Detect headers, footers, page numbers, and footnotes as labeled blocks rather than deleting them irreversibly.
5. Visually sample the output because selectable text can still be out of order or incorrectly encoded.

Native extraction is normally preferable for clean born-digital pages because OCR would introduce recognition errors. It is not automatically correct merely because text is selectable.

### 4.4 OCR route

Use OCR when a page or region lacks a usable text layer. OCR should operate on a deterministic rendered image with recorded DPI, color mode, deskew/rotation, preprocessing, language model, page-segmentation mode, and engine version.

Recommended procedure:

1. Render from the original PDF at a controlled resolution; test 300 DPI as the baseline.
2. Correct orientation and deskew only when detected, recording the transformation.
3. Avoid destructive thresholding as the only stored input; preserve the original rendering.
4. Run Tesseract as the conventional baseline.
5. Run PaddleOCR PP-StructureV3 on the benchmark's scanned and complex-layout strata.
6. Run Docling as a structured-document challenger if its dependencies and license fit the project.
7. Compare outputs to human transcription using the same normalization policy.
8. Select the route by page stratum, not merely by global average.

For Bengali, Urdu, or other scripts, install and record the appropriate language models. Do not transliterate source text during canonical extraction. Transliteration, if needed, is a separate derived record linked to the original span.

### 4.5 Mixed and complex pages

A page can contain valid native body text plus a scanned quotation, map, table, or image caption. Such a page should use region-level provenance:

- preserve valid native regions;
- OCR only raster regions requiring recognition;
- use layout detection to establish reading order and containment;
- retain table cells and row/column relations when possible;
- link each caption to its visual asset without claiming the link is certain when ambiguous.

The page-level label can be `hybrid`, while every block records its own extraction method.

## 5. How Detailed Extraction Should Be

The canonical extraction should be detailed enough to reproduce evidence and support both RAG and hypergraph construction, but it should not store arbitrary duplicated views in one giant JSON document.

### 5.1 Required record levels

| Level | Required contents | Why the thesis needs it |
| --- | --- | --- |
| Source/book | Stable ID, SHA-256, filename, bibliographic fields, rights, edition, PDF metadata, pipeline run | Distinguishes editions and proves source identity |
| Structure | Part/chapter/section IDs, titles, hierarchy, page range, detection method, review status | Enables within- and cross-chapter narrative comparison |
| Page | PDF index, human page number, printed label, geometry, rotation, route, quality flags, text hashes | Supports citation and page-level auditing |
| Block/region | Type, bounding box, reading order, raw text, method, confidence/quality, parent page | Preserves columns, quotations, footnotes, captions, and tables |
| Source span | Paragraph/sentence ID, exact text, page offsets, block links, structure links, text hash | Grounds claims and RAG evidence precisely |
| Asset | Type, file hash/path, page, bounding box, caption links, method, review status | Prevents visual evidence from disappearing |
| Run/provenance | Code commit, schema, engine/model versions, config, timestamps, warnings, failures | Makes results reproducible |

Claims, frame labels, entity resolution, RAG chunks, and hypergraph edges are **derived records**. They should link to extraction IDs and should not be embedded as if they were original PDF content.

### 5.2 Conditional detail

Store line-, word-, or token-level boxes when they are needed for:

- OCR error analysis;
- exact visual highlighting;
- table reconstruction;
- quotations or footnotes with difficult layout;
- aligning normalized text back to page pixels.

It is not necessary to duplicate every OCR token indefinitely in every downstream dataset. Keep detailed OCR/layout output in the extraction layer and generate compact span/chunk views for LLM and hypergraph use.

### 5.3 Page identifiers must not be ambiguous

Keep three concepts separate:

- `pdf_page_index`: zero-based position used by PDF libraries;
- `pdf_page_number`: one-based physical order used in pipeline logs;
- `printed_page_label`: number or label printed or encoded by the book, such as `xii`, `1`, or an empty value.

A claim citation should show the printed label when known, but its machine locator must also retain the unambiguous PDF index.

### 5.4 Example minimum page record

```json
{
  "schema_version": "0.1.0",
  "record_type": "page",
  "book_id": "book:sha256-prefix",
  "page_id": "page:book-id:0042",
  "pdf_page_index": 41,
  "pdf_page_number": 42,
  "printed_page_label": "27",
  "geometry": {
    "width_points": 612.0,
    "height_points": 792.0,
    "rotation_degrees": 0
  },
  "structure": {
    "part_id": "part:book-id:01",
    "chapter_id": "chapter:book-id:03",
    "section_id": null,
    "assignment_method": "pdf_bookmark",
    "review_status": "pending"
  },
  "extraction": {
    "route": "hybrid",
    "native_engine": "PyMuPDF exact-version",
    "ocr_engine": "exact engine and model version",
    "ocr_languages": ["eng"],
    "render_dpi": 300,
    "run_id": "run:exact-id"
  },
  "text": {
    "raw_sha256": "full-hash",
    "normalized_sha256": "full-hash",
    "character_count": 2497,
    "word_count": 444
  },
  "block_ids": ["block:book-id:0042:001"],
  "asset_ids": [],
  "quality": {
    "flags": [],
    "automated_status": "pass",
    "human_review_status": "pending"
  }
}
```

The full text belongs in the canonical page/span store, not necessarily duplicated inside every index or human-facing report.

## 6. Normalization and Offset Policy

Normalization can improve search while destroying evidence coordinates if handled carelessly. Use two representations:

- `raw_text`: the selected engine output, unchanged;
- `normalized_text`: conservative text used for sentence splitting and retrieval.

The normalization function must be versioned. It may standardize line endings, Unicode normalization, and clearly defined whitespace behavior. Dehyphenation, header removal, spelling correction, and OCR correction should be explicit transformations with recoverable mappings or separate derived text.

Every source span must specify which representation its offsets address. Validation must reconstruct `text[start:end]` exactly and compare its hash. Where a claim quote is aligned after whitespace normalization, preserve both the submitted quote and the exact source substring.

## 7. Structure and Chunking Policy

### Structure

Use evidence in this order:

1. reliable PDF outline/bookmarks;
2. printed table of contents aligned to page headings;
3. typography and layout-based heading detection;
4. model-assisted proposals requiring review.

Every structure assignment records its method and review status. A bookmark is useful metadata, not guaranteed ground truth.

### Claim-extraction units

- Use a paragraph or a small coherent passage as the target evidence unit.
- Supply limited neighboring context for speaker and pronoun resolution.
- Mark context as ineligible evidence unless separately selected.
- Never cross a chapter boundary in one candidate unit.
- Split long paragraphs at sentence boundaries while preserving parent IDs.

### RAG units

Begin by benchmarking sentence-window and paragraph/chapter-aware chunks rather than selecting one size by intuition. A practical initial grid is approximately 300, 600, and 900 model tokens with 0%, 10%, and 20% overlap, constrained by section boundaries. Evaluate retrieval before fixing a value.

### Hypergraph units

Hyperedges should be created from reviewed atomic claims or events, not from arbitrary page chunks. Each incidence must preserve its semantic role and evidence span.

## 8. Images, Tables, Maps, and Other Visual Content

"Images extracted" can mean several different things:

1. embedded raster objects found in the PDF;
2. full-page scan images;
3. meaningful figures or photographs detected in the rendered page;
4. vector maps, charts, or drawings;
5. decorative logos, masks, backgrounds, or repeated artifacts.

The prototype's embedded-image count covers only some of these. A credible multimodal inventory should:

- enumerate embedded raster objects and deduplicate by content hash;
- inspect vector-drawing regions;
- detect meaningful regions from rendered pages;
- distinguish full-page scans from figures;
- link captions and nearby references;
- represent table structure as cells in addition to keeping a visual crop;
- store a page/bounding-box locator for every asset;
- flag maps and figures for human review;
- keep generated visual descriptions separate from source-authored captions.

No automated image count should be called 100% ground truth without reviewing every page under a written definition of "meaningful image."

## 9. Benchmark Needed to Select the Best Method

### 9.1 Freeze the evaluation sample first

Select a stratified pilot of at least 60 pages across the corpus, then determine the final sample size from pilot variance and available annotation resources. Include:

- clean born-digital prose;
- native text with suspicious encoding/order;
- clean scans;
- degraded, skewed, or low-resolution scans;
- multi-column and footnote-heavy pages;
- quotations/interviews with speaker changes;
- contents, index, bibliography, and front matter;
- image/caption, map, and table pages;
- every language/script relevant to the corpus.

Include all rare high-risk types even if proportional random sampling would miss them. Keep a held-out final test portion that is not used to tune routing thresholds or preprocessing.

### 9.2 Create human ground truth

For selected pages:

1. Store the exact source hash and rendered audit image.
2. Have one annotator transcribe text and mark blocks, reading order, headings, captions, and meaningful assets.
3. Have a second annotator independently verify or annotate the same page.
4. Preserve both annotations and adjudicate disagreements.
5. Record annotation time, uncertainty, and unreadable source regions.

Ground truth should preserve source spelling and punctuation. It should not silently modernize, translate, or historically correct the author.

### 9.3 Run controlled extraction conditions

Run the same frozen pages through:

| ID | Condition |
| --- | --- |
| E0 | PyMuPDF native text and blocks |
| E1 | Tesseract baseline at fixed rendering settings |
| E2 | PaddleOCR PP-StructureV3 at fixed settings |
| E3 | Docling at fixed settings |
| E4 | Proposed adaptive router choosing among validated routes |

Record failures rather than excluding them. Do not compare an OCR system on enhanced images against another on original images unless preprocessing is the declared independent variable.

### 9.4 Measure extraction quality

At minimum report:

- character error rate (CER);
- word error rate (WER);
- exact accuracy for person names, organizations, locations, dates, and quantities;
- block-type precision, recall, and F1;
- reading-order accuracy;
- heading and chapter-boundary precision, recall, and F1;
- table cell/structure accuracy where tables are in scope;
- meaningful asset and caption-link precision/recall;
- page failure and empty-text rates;
- exact provenance/offset pass rate;
- runtime, peak memory/GPU use, and output size.

Report macro results across books as well as micro results across characters/pages. One long clean book must not dominate the conclusion.

### 9.5 Measure downstream effect

Extraction quality should also be tested through the thesis tasks:

1. Run the same reviewed claim extractor on gold text and on each extraction condition.
2. Measure the loss in claim identification, attribution, entity, date, location, polarity, and evidence accuracy.
3. Build RAG indexes from identical content under each extraction condition and compare retrieval/citation metrics.
4. Build hypergraphs from the same reviewed claims and compare entity/incidence/provenance accuracy.

This reveals errors that CER alone can hide. Changing `1971` to `1977`, or confusing two names, may be rare at character level but severe for historical narrative analysis.

### 9.6 Selection rule

Before seeing final test results, agree on:

- mandatory hard gates: source hash, page coverage, unique IDs, referential integrity, and exact stored offsets should be 100%;
- accuracy thresholds for text, structure, and meaningful visual assets;
- maximum acceptable failure rate;
- how accuracy, resource cost, and manual-review burden are weighted;
- whether different page strata may use different winning engines.

Do not invent universal CER/WER thresholds after viewing results. Set provisional targets from the pilot, obtain supervisor approval, and report confidence intervals and failure cases.

## 10. Validation Stages for Every Production Book

### Automated checks

- source file hash matches the manifest;
- every PDF page has exactly one page record;
- every ID is unique and every reference resolves;
- raw and normalized text hashes reproduce;
- source-span offsets reconstruct exact stored text;
- page/block/span bounding boxes are valid and within page geometry;
- reading-order values are unique within their scope;
- chapter ranges do not overlap illegally or exceed the book;
- OCR and native routes have complete engine provenance;
- every asset file exists and matches its checksum;
- failures and empty pages are explicitly listed;
- records validate against the frozen JSON Schema.

### Human checks

- inspect all OCR failures, empty pages, low-quality flags, and structure ambiguities;
- inspect all map, table, photograph, and caption pages in the evaluation sample;
- compare text to page images, not merely one extractor to another;
- verify quotations, speaker transitions, footnotes, names, dates, and numbers;
- verify a random native-page sample because native text can also be defective;
- sign the review record with annotator ID, status, timestamp, and notes.

### Release gate

A book can be marked:

- `extracted_unreviewed`: processing completed, automated checks only;
- `sample_reviewed`: stratified human audit completed;
- `benchmark_validated`: evaluated against adjudicated ground truth;
- `production_accepted`: meets the predeclared release criteria.

The existing prototype outputs should currently be described as `extracted_unreviewed`, except where a completed human review can be demonstrated.

## 11. Extraction Bias Risks

Because the thesis concerns competing historical narratives, extraction errors can create or amplify apparent bias. The evaluation must explicitly inspect:

- lower OCR accuracy for Bengali, Urdu, diacritics, or transliterated names;
- different scan quality across publishers, countries, or viewpoints;
- omission of footnotes, testimony, captions, maps, or appendices;
- quotation and speaker-boundary errors;
- headers inserted into sentences;
- dehyphenation or punctuation changes that alter meaning;
- systematic loss of numbers, negation, hedging, or uncertainty;
- entity resolution that merges different people or splits one person's name;
- selective exclusion of pages because one engine failed.

Report extraction performance by book and relevant source group before interpreting narrative differences. A pipeline cannot be described as "debiasing" historical narratives if it measures one group of books less accurately than another.

## 12. Recommended Decision for the Team Now

1. Adopt the canonical page/block/span/asset detail described in this guide.
2. Keep extraction separate from claims and frames, linked through stable IDs.
3. Migrate the useful PyMuPDF/Tesseract provenance and validation components from `local_book_extractor`.
4. Migrate PaddleOCR PP-StructureV3 as a benchmarked layout/OCR candidate, not as an assumed winner.
5. Add Docling as one controlled challenger if setup is reproducible on the team's hardware.
6. Replace fixed ten-page chunks with section-aware paragraph and sentence spans.
7. Build and double-annotate the extraction benchmark before processing the entire thesis corpus again.
8. Select the production routing policy from benchmark results and freeze it before the LLM-versus-hypergraph comparison.

## 13. How to Report the Extraction Experiment

Use wording such as:

> We evaluated native text extraction and OCR/layout alternatives on a stratified, double-reviewed sample of historical-book pages. The selected adaptive pipeline retained validated native text and routed image-only or defective regions through the best-performing OCR/layout condition for their page type. All outputs preserved source hashes, page and region coordinates, document hierarchy, raw and normalized text, engine provenance, and exact source spans. Extraction accuracy was measured independently from downstream claim, RAG, and hypergraph performance.

Until the benchmark is complete, use:

> Our prototypes demonstrate extraction routing, provenance, offset validation, and audit generation. They have not yet established the most accurate engine because manually transcribed text and layout ground truth are still being prepared.

## 14. References and Tool Documentation

- [PyMuPDF text extraction recipes](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- [OCRmyPDF introduction and processing model](https://ocrmypdf.readthedocs.io/en/latest/introduction.html)
- [Tesseract documentation](https://tesseract-ocr.github.io/tessdoc/)
- [PaddleOCR PP-StructureV3 documentation](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PP-StructureV3.html)
- [Docling documentation](https://docling-project.github.io/docling/)
- [Docling technical report](https://arxiv.org/abs/2408.09869)
- [OCR-D quality-assurance and evaluation specification](https://ocr-d.de/en/spec/ocrd_eval.html)
- [W3C Web Annotation selectors](https://www.w3.org/TR/annotation-model/#selectors)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)
- [TEI Guidelines](https://tei-c.org/release/doc/tei-p5-doc/en/html/)
- [IIIF Presentation API 3.0](https://iiif.io/api/presentation/3.0/)

These references justify candidate methods and representation choices. Only the proposed corpus-specific benchmark can determine which extraction route is best for this thesis.
