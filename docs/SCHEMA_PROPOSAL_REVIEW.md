# Review of the Simplified Extraction and Claim Schemas

**Proposal date:** 2026-09-29  
**Review status:** Team discussion draft  
**Recommended name:** RNH Core Schema v0.2

## Executive Assessment

The proposed schemas are a useful simplification. They are readable, keep book extraction separate from claim extraction, and contain the basic information needed for a demonstration.

They are not yet sufficient as the canonical thesis format. In their current form:

- claims cannot be reliably joined to books in a multi-book corpus;
- an evidence quotation cannot be located or checked exactly;
- participants cannot be converted reliably into hypergraph roles;
- extraction and claim-generation runs cannot be reproduced;
- `frame` mixes several different kinds of labels;
- `review_flag: ["good"]` mixes review status with error flags;
- one page-level extraction method cannot represent mixed native/OCR pages;
- the format cannot distinguish source grounding, source fidelity, and historical truth.

The recommendation is **not** to return to the largest previous schema. Adopt a small required core plus optional extension fields. Keep extraction and claims in separate files connected by stable IDs.

## 1. Evaluation of the Proposed Text-Extraction Schema

### Proposed strengths

- The top-level `book` and `pages` separation is easy to understand.
- Book title, author, year, language, filename, and page count are useful minimum metadata.
- Page number, label, chapter, text, and extraction method support basic reading and inspection.
- One JSON object per book is convenient for a small human-readable demonstration.

### Problems that need correction

| Current field/design | Problem | Recommended correction |
| --- | --- | --- |
| `book_id` without a generation rule | Different team members may assign different IDs to the same file | Derive it from the source SHA-256 or use a controlled registry |
| `author` as one string | Books can have multiple authors, editors, translators, or interviewers | Use `authors: []`; add other creator roles later if needed |
| No source hash | Same filename can refer to different editions or files | Add `source_sha256` |
| `page_number` only | It may mean PDF index, one-based PDF order, or printed number | Define `pdf_page_number` and keep `printed_page_label` separately |
| No `page_id` | Claims cannot make an unambiguous page reference | Add a stable `page_id` |
| `chapter_title` only | Duplicate titles and uncertain mappings are possible | Add `chapter_id` and `structure_assignment_method` |
| One `text` string | Cleaning can destroy the original engine output | Keep raw and normalized text or document that they are identical |
| `extraction_method` as free text | Team members will produce incompatible values | Restrict to `native`, `ocr`, `hybrid`, or `none` |
| No engine/version | The run cannot be reproduced | Record engine/model and `run_id` |
| No quality state | Empty, low-quality, or suspicious pages look valid | Add `quality_flags` and review status |
| No text hash or offsets | Later evidence alignment cannot be checked deterministically | Add a normalized-text hash and source spans/offsets |
| No multimodal records | Images, maps, tables, and captions disappear | Keep assets in a separate linked file or optional `assets` collection |

### Naming

`extext` is short, but it is not self-explanatory and may be confused with a tool or file extension. Prefer:

- `book_extraction.json` for a small per-book package; or
- `books.jsonl`, `pages.jsonl`, `spans.jsonl`, and `assets.jsonl` for the canonical corpus.

The human-readable format and scalable format can implement the same logical schema.

## 2. Evaluation of the Proposed Claim Schema

### Proposed strengths

- `claim_text` distinguishes the structured proposition from the quotation.
- `evidence_quote` encourages source grounding.
- attribution, event, actors, location, and time begin to expose claim semantics.
- a multi-label list acknowledges that more than one narrative category may apply.
- review fields make uncertainty visible instead of hiding it.

### Problems that need correction

| Current field/design | Problem | Recommended correction |
| --- | --- | --- |
| No `book_id` | Claims from six books cannot be safely combined | Make `book_id` required |
| One `page_number` | A claim may use multiple quotations or span two pages | Use an `evidence` array containing page IDs and offsets |
| Quote without offsets | Exact grounding cannot be verified | Add `char_start`, `char_end`, and preferably `span_id` |
| `attribution` as a string | It cannot distinguish speaker name, role, or attribution cue | Use a small structured object |
| `actors: []` | Claims also contain affected people, objects, witnesses, institutions, and quoted sources | Replace with role-bearing `participants` |
| `event` as a string | Not every claim is an event; it may be causal, comparative, quantitative, or interpretive | Use `claim_kind` plus `predicate` |
| `location: []`, but `time` as a string | Cardinality and normalization are inconsistent | Make both arrays of structured mentions |
| No polarity/modality | Denial, uncertainty, memory, and dispute can be turned into false assertions | Add `epistemic_status` and preserve negation |
| `frame` as plain labels | No codebook version, assignment source, evidence, or review state | Rename provisionally to `narrative_labels`, or define a separate frame annotation record |
| `review_flag` never empty | `good` is a status, not an error flag | Add `review.status`; allow `review.flags: []` |
| No extraction provenance | Zero-shot, few-shot, rule-based, and human claims become indistinguishable | Record method, model, prompt version, and run ID |
| No verification distinction | Exact quote matching may be mistaken for historical verification | Record grounding, source fidelity, and historical truth separately |

## 3. The Proposed Nine-Value Frame List

The proposed list is:

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

These are potentially useful research labels, but they are not all the same kind of concept:

- `liberation_war`, `civil_war`, and `counter_insurgency` characterize the conflict;
- `foreign_intervention` describes involvement or causal attribution;
- `humanitarian_crisis` and `state_institutional_failure` describe problem definitions;
- `sexual_violence` is primarily a topic or event class;
- `genocide_massacre` may be a legal/historical characterization, event class, or narrative frame depending on its definition.

Calling the entire list `frame` before defining a codebook risks invalid analysis. For the first schema version, use:

```json
{
  "narrative_labels": []
}
```

Then decide with the supervisor whether these labels represent:

- topics;
- event characterizations;
- conflict naming;
- causal/responsibility frames;
- moral evaluations; or
- a deliberately mixed narrative taxonomy.

If the team intentionally keeps a mixed taxonomy, state that explicitly and do not report it as a validated framing theory. Every label needs a definition, inclusion rule, exclusion rule, positive example, difficult counterexample, multi-label rule, and `other` policy. The codebook must be piloted with at least two annotators.

## 4. Correct Review Design

The proposed rule that `review_flag` is never empty creates records such as:

```json
{
  "review_flag": ["good"]
}
```

This is difficult to query because `good` might accidentally coexist with an error. Separate status from flags:

```json
{
  "review": {
    "status": "pending",
    "flags": [],
    "reviewer_id": null,
    "reviewed_at": null,
    "note": null
  }
}
```

Recommended statuses:

```text
pending
accepted
needs_revision
rejected
```

Recommended issue flags:

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

An accepted record normally has an empty flag list. A record can remain accepted with a minor flag only if the annotation guide explicitly permits it.

## 5. Recommended Simple Extraction Schema

This is the recommended minimum per-book human-readable format. The scalable representation may place books, pages, and spans in separate JSONL files without changing field meanings.

```json
{
  "schema_version": "0.2.0",
  "book": {
    "book_id": "book:sha256-prefix",
    "title": "",
    "authors": [],
    "publication_year": null,
    "language": "",
    "source_file_name": "",
    "source_sha256": "",
    "page_count": 0
  },
  "pages": [
    {
      "page_id": "page:book-id:0001",
      "pdf_page_number": 1,
      "printed_page_label": "",
      "structure": {
        "part_title": null,
        "chapter_id": null,
        "chapter_title": null,
        "section_title": null,
        "assignment_method": "none",
        "review_status": "pending"
      },
      "text": {
        "raw": "",
        "normalized": "",
        "normalized_sha256": ""
      },
      "extraction": {
        "method": "native",
        "engine": "",
        "run_id": ""
      },
      "quality_flags": []
    }
  ]
}
```

Controlled `extraction.method` values:

```text
native
ocr
hybrid
none
```

For claim grounding, sentence or paragraph spans should be exported separately with `span_id`, `page_id`, text, and page-relative character offsets. This avoids making the page object difficult to read.

## 6. Recommended Simple Claim Schema

```json
{
  "schema_version": "0.2.0",
  "claim_id": "claim:book-id:000001",
  "book_id": "book:sha256-prefix",
  "claim_text": "One atomic, source-faithful proposition.",
  "claim_kind": "event",
  "epistemic_status": "asserted",
  "attribution": {
    "speaker": "",
    "speaker_role": "author",
    "cue": null
  },
  "predicate": "",
  "participants": [
    {
      "text": "",
      "role": "actor",
      "entity_id": null
    }
  ],
  "locations": [
    {
      "text": "",
      "normalized": null
    }
  ],
  "times": [
    {
      "text": "",
      "normalized": null
    }
  ],
  "evidence": [
    {
      "span_id": "span:book-id:000123",
      "page_id": "page:book-id:0042",
      "quote": "Exact quotation copied from extracted text.",
      "char_start": 120,
      "char_end": 167
    }
  ],
  "narrative_labels": [],
  "extraction": {
    "method": "llm_zero_shot",
    "model": "",
    "prompt_version": "",
    "run_id": ""
  },
  "verification": {
    "exact_quote_match": false,
    "offset_match": false,
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

### Recommended controlled values

`claim_kind`:

```text
event
state
causal
comparative
interpretive
quantitative
other
```

`epistemic_status`:

```text
asserted
reported
remembered
inferred
disputed
denied
uncertain
```

Participant roles may initially include:

```text
actor
affected_entity
object
beneficiary
witness
source
institution
other
```

The original surface text must always be retained. Normalized entity IDs can remain `null` until entity resolution is performed.

## 7. Why This Remains Usable for Both LLM and Hypergraph Work

### LLM/RAG

- `claim_text` supplies an atomic proposition.
- `evidence` supplies exact retrieval and citation targets.
- attribution and epistemic status prevent quoted or disputed statements from becoming unqualified facts.
- book, page, chapter, and span IDs support filtered retrieval.
- JSONL records can become reviewed fine-tuning examples later.

### Hypergraph

- each claim can become a hyperedge;
- participants become nodes joined through role-bearing incidences;
- time and location become linked nodes or attributes;
- attribution identifies who presents the claim;
- evidence links the hyperedge back to source-span and book nodes;
- narrative labels remain annotations rather than being mistaken for entities or truth labels.

The canonical claim should be created once. LLM-training rows and Parquet hypergraph tables should be generated from it rather than manually maintained as separate truths.

## 8. Required Versus Optional Fields

To keep team work manageable, use two profiles.

### Core fields required immediately

Extraction:

```text
schema_version
book_id
title
authors
source_file_name
source_sha256
page_count
page_id
pdf_page_number
printed_page_label
chapter_title
raw/normalized text
extraction method
engine/run ID
quality flags
```

Claims:

```text
schema_version
claim_id
book_id
claim_text
claim_kind
epistemic_status
attribution
predicate
participants with roles
evidence page/span/quote/offsets
verification states
review status and flags
```

### Extensions added when available

```text
publisher, edition, ISBN and other creator roles
block and token bounding boxes
table cells and caption associations
normalized entity IDs
normalized dates and gazetteer locations
narrative/frame annotations under an approved codebook
model-judge outputs
historical corroboration records
```

An unavailable optional value should be `null` or an empty array according to the schema. It must never be guessed merely to fill the field.

## 9. How the Schema Should Be Evaluated

Before adopting version 1.0:

1. Select at least two different chapters from at least three books.
2. Include native, OCR, quotation/interview, footnote, table/image, and ambiguous-attribution examples.
3. Have every team member independently encode the same pages and claims.
4. Validate all records with JSON Schema.
5. Run exact quote and offset reconstruction.
6. Compare whether team members chose the same claims, boundaries, speakers, participant roles, times, locations, and narrative labels.
7. Record fields that were misunderstood, repeatedly empty, or impossible to assign.
8. Revise the schema and annotation guide before processing the full corpus.
9. Freeze the schema version, codebook version, and migration rules.

Evaluation questions should include:

- Can a reviewer find the exact page and quotation in under one minute?
- Can code join every claim to exactly one known book and one or more valid spans?
- Can a claim be converted to a hyperedge without guessing participant roles?
- Can the record preserve denial, uncertainty, memory, and nested attribution?
- Can the same record become an LLM/RAG training or evaluation item?
- Do two annotators interpret each field consistently?
- Can a newer schema be migrated without destroying old provenance?

## 10. Recommended Team Decision

Approve the proposal with these modifications:

1. Keep extraction and claims as separate datasets.
2. Add `schema_version`, source hash, stable page/span IDs, and run provenance.
3. Add `book_id` and exact evidence offsets to every claim.
4. Replace actor strings with role-bearing participants.
5. Separate review status from issue flags.
6. Rename the current frame list to `narrative_labels` until a supervisor-approved frame codebook exists.
7. Keep detailed blocks/assets as linked extension records rather than crowding the core JSON.
8. Pilot v0.2 jointly before declaring it the final schema.

## 11. Short Reply for the Team Chat

> The simpler schema is a good direction, and extraction and claims should remain separate. I suggest keeping it as a core schema but adding a few fields we cannot recover later: schema version, source-file hash, stable page/span IDs, claim `book_id`, exact quote offsets, extraction/run provenance, and role-bearing participants. I would also separate `review_status` from `review_flags`; `good` should be a status and a good record can have an empty flag list. The proposed nine frame values currently mix conflict characterizations, topics, and causal/problem frames, so we should temporarily call them `narrative_labels` until we define and test a frame codebook with the supervisor. This remains compact but supports exact verification, LLM/RAG use, and hypergraph conversion.

## Final Verdict

The proposed format is **good for a demonstration but incomplete for thesis data**. The revised core schema above is the smallest version recommended for adoption. Removing any more provenance would make later verification and fair LLM-versus-hypergraph comparison unreliable.
