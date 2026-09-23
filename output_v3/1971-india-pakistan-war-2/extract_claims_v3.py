#!/usr/bin/env python3
"""
extract_claims_v3.py

Runs the v3 claim-extraction prompt (see claim_extraction_prompt_v3.md) against a local
Ollama model, page by page, over a book_metadata.json produced by your extraction pipeline.

Fixes baked in vs. earlier scripts (see Claim_Extraction_Report):
  - actor-must-not-equal-event self-check (2.1 / 5.1)
  - no umbrella claims (2.2 / 5.3)
  - atomization of compound/list sentences (2.3)
  - perpetrator-not-victim as actor (2.4)
  - per-claim independent location/time/frame judgment (5.4)
  - fixed, correct source default pulled from --book-title/--author, not pdf_metadata (2.6)
  - repeated running-header/footer stripping BEFORE chunking (5.5)
  - resumable: re-running skips pages already extracted

Dependencies: none beyond the Python 3 standard library. Requires Ollama running locally
(default http://localhost:11434) with the model already pulled, e.g.:
    ollama pull deepseek-r1:7b

USAGE (PowerShell or bash):
    python extract_claims_v3.py ^
        --input book_metadata.json ^
        --output-dir claims_out ^
        --book-title "An Atlas of the 1971 India-Pakistan War: The Creation of Bangladesh" ^
        --author "John H. Gill"

Useful flags:
    --start-page 69 --end-page 76      only process a page range (e.g. one chapter)
    --limit 5                          only process the first N pages (smoke test)
    --model deepseek-r1:7b             Ollama model tag (default: deepseek-r1:7b)
    --resume                           default on; skip pages already in claims.jsonl
    --no-resume                        force re-extraction of every page

Outputs (in --output-dir):
    claims.jsonl        one JSON object per page: {"page_number", "chunk_id", "claims": [...]}
    claims_all.json      combined flat array of every claim, ready to paste into
                          book_dataset_v1.json's "claims" field
    claims_all.csv        flat CSV for quick spreadsheet review
    failed_chunks.log     raw model output for any chunk that failed to parse as JSON
    run.log               progress log
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

OLLAMA_URL_DEFAULT = "http://localhost:11434/api/chat"
MODEL_DEFAULT = "deepseek-r1:7b"
DELIMITER = "===FINAL_JSON==="

SYSTEM_PROMPT = """You are a historical claim-extraction engine. You are given ONE chunk of source text from a
nonfiction book about the 1971 Bangladesh Liberation War. Your job is to extract every distinct
ATOMIC CLAIM in that chunk as structured JSON. You must reason step by step first, then output
JSON. Follow every rule below exactly — they were written to fix specific, repeated failures
from earlier extraction runs on this exact task.

=== WHAT COUNTS AS ONE ATOMIC CLAIM ===
An atomic claim has exactly ONE actor (or "Unspecified"), ONE action/event, and can be stated as
one simple sentence. If a sentence in the source names multiple actors doing different things,
lists multiple items, or bundles multiple causes/events together, it is NOT one claim — split it
into one claim per actor/item/event before doing anything else. When in doubt, split further
rather than combining. A claim that needs "and" to join two different actors or two different
events is not atomic yet.

=== RULE 1 — ACTOR MUST NEVER EQUAL THE EVENT ===
The "actor" field names a person, group, institution, or country. It must never be the same
noun phrase as "event" or "frame", and it must never be an abstract restatement of the action
itself (e.g. the actor of "a war broke out" is not "the war"). If the source sentence does not
name a real actor, use "Unspecified" — do not invent one by repeating the event name.
Before finalizing each claim, explicitly compare actor and event as strings. If they are the
same entity under different wording, you have failed this rule — go back and either find the
real actor in the surrounding sentence or set actor to "Unspecified". This check is NOT
optional and must be done per claim, not once per chunk — a chunk can contain some claims that
pass and some that fail.

=== RULE 2 — NO UMBRELLA / TOPIC-SENTENCE CLAIMS ===
If a sentence introduces a list or group of specific claims that follow it (e.g. "Three
things happened: X, Y, Z"), do not also emit a claim for the topic sentence itself. Only emit
the specific claims (X, Y, Z). Before emitting any claim, check it against every other claim
you have already produced in this same chunk — if a new claim only restates information already
fully covered by two or more other claims combined, drop it.

=== RULE 3 — ATOMIZE COMPOUND AND LIST SENTENCES ===
When a single sentence lists several causes, actors, or factors joined by commas or "and", emit
one claim per item, each with its own specific actor drawn from that item — never a single claim
whose actor field is a comma-separated list of multiple entities.

=== RULE 4 — PERPETRATOR, NOT VICTIM, IS THE ACTOR ===
For sentences describing harm, violence, or an action done TO a group, the actor is whoever
performed the action, never the people it happened to. If the source does not name who did it,
actor = "Unspecified perpetrator" (not the victims' name). The victims belong in
"affected_entities", never in "actor".

=== RULE 5 — JUDGE EVERY FIELD INDEPENDENTLY, PER CLAIM ===
location, time, and frame must each be re-derived from THIS claim's own sentence/context. Never
copy a value forward from the previous claim in the chunk just because it was true there. If the
current claim's own text does not support a location, time, or frame, use "Unspecified" for that
field rather than reusing the last one you wrote.

=== RULE 6 — DO NOT SACRIFICE RECALL FOR PRECISION ===
Extract every distinct claim in the chunk, including minor ones: citations of other authors,
brief asides, single-sentence reflections, and claims embedded in quotations. A short or
low-confidence claim is still a claim — set its "confidence" field low rather than omitting it.
Only drop a claim under Rule 2 (true redundancy) — never because it seems minor.

=== RULE 7 — STRIP PAGE-HEADER / FOOTER NOISE ===
Source chunks may contain a running page header or footer (a short fragment, often in capital
letters, repeating the book or chapter title, sometimes with a page number) that is not part of
the author's actual sentence. Recognize these by: (a) they interrupt a sentence mid-word or
mid-clause, (b) they repeat text seen at the start/end of the chunk, (c) they are in different
casing or formatting from the surrounding prose. Exclude any such fragment from claim_text and
evidence.quote. Never treat a page header as an entity, actor, or event.

=== RULE 8 — FIXED SOURCE DEFAULT ===
Set "source" to exactly: "Book: {book_title}" for every claim, using the book_title given to you
in the user message. Only deviate from this default if the passage itself explicitly quotes or
cites a different named source (e.g. an interview, another book, a document) — in that case use
that named source instead, and still record the book itself in "location.chapter_title" /
metadata, not in "source".

=== SELF-CHECK (perform silently, per claim, before writing final JSON) ===
For each claim, verify in order:
1. actor != event and actor != frame (Rule 1)
2. this claim is not restating 2+ other claims already produced (Rule 2)
3. if the source sentence had multiple items/actors, this is only ONE of them (Rule 3)
4. actor is the doer, not the one harmed (Rule 4)
5. location/time/frame come from this claim's own text, not copied from the prior claim (Rule 5)
6. claim_text and evidence.quote contain no header/footer fragments (Rule 7)
If any check fails, silently fix the claim before including it in the output. Do not mention
this checklist in the final JSON.

=== CLAIM TYPES ===
Use one of: "factual" (a reported event/action), "interpretive" (author's analysis or
judgment), "quoted" (a claim made by someone else and quoted/cited by the author),
"statistical" (a number, count, or measurement).

=== OUTPUT FORMAT ===
Think through the chunk first in plain reasoning. Then output the delimiter line
"===FINAL_JSON===" on its own line, followed by ONLY a single JSON object (no prose, no
markdown fences) matching this shape:

{
  "claims": [
    {
      "claim_id": "",
      "claim_text": "",
      "claim_type": "factual|interpretive|quoted|statistical",
      "confidence": 0.0,
      "actor": "",
      "action": "",
      "event": "",
      "affected_entities": [],
      "named_entities": [{"text": "", "label": ""}],
      "location": "",
      "time": "",
      "frame": "",
      "themes": [],
      "source": "",
      "evidence": {"quote": ""}
    }
  ]
}

If the chunk contains no extractable claims, output {"claims": []} after the delimiter.
"""

USER_TEMPLATE = """Book: {book_title}
Author: {author}
Chapter: {chapter_title}
Page: {page_number}
Chunk ID: {chunk_id}

Source text (extract every atomic claim from this text only; do not use outside knowledge):
\"\"\"
{source_text}
\"\"\"
"""


def log(logfile, msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def find_repeated_header_lines(pages, min_len=6, max_len=90, freq_threshold=0.25):
    """
    Heuristic header/footer detector (Rule 7 support): finds short lines that repeat
    across a large fraction of pages, e.g. a running title or 'BOOK NAME 4'.
    Returns a set of exact line strings to strip from every page's text.
    """
    counts = Counter()
    for p in pages:
        text = p.get("text", "") or ""
        for line in text.splitlines():
            line = line.strip()
            if min_len <= len(line) <= max_len:
                counts[line] += 1
    n_pages = max(len(pages), 1)
    return {line for line, c in counts.items() if c / n_pages >= freq_threshold}


def strip_headers(text, header_lines):
    if not header_lines:
        return text
    kept = []
    for line in text.splitlines():
        if line.strip() in header_lines:
            continue
        kept.append(line)
    return "\n".join(kept)


def call_ollama(ollama_url, model, system_prompt, user_prompt, timeout=300):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ollama_url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("message", {}).get("content", "")


def parse_model_output(raw):
    if DELIMITER in raw:
        _, _, json_part = raw.partition(DELIMITER)
    else:
        # Model forgot the delimiter; try to find the first "{" as a fallback.
        idx = raw.find("{")
        json_part = raw[idx:] if idx != -1 else raw
    json_part = json_part.strip()
    # Strip accidental markdown fences.
    json_part = re.sub(r"^```(json)?", "", json_part.strip())
    json_part = re.sub(r"```$", "", json_part.strip())
    data = json.loads(json_part)
    return data.get("claims", [])


def already_done_pages(jsonl_path):
    done = set()
    if jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    done.add(row["page_number"])
                except Exception:
                    continue
    return done


def main():
    ap = argparse.ArgumentParser(description="Run v3 atomic claim extraction over book_metadata.json via Ollama")
    ap.add_argument("--input", required=True, help="Path to book_metadata.json")
    ap.add_argument("--output-dir", required=True, help="Directory to write outputs into")
    ap.add_argument("--book-title", required=True, help="Correct book title (do NOT trust pdf_metadata.title)")
    ap.add_argument("--author", default="Unspecified", help="Book author")
    ap.add_argument("--model", default=MODEL_DEFAULT, help="Ollama model tag")
    ap.add_argument("--ollama-url", default=OLLAMA_URL_DEFAULT, help="Ollama chat endpoint")
    ap.add_argument("--start-page", type=int, default=None, help="Only process pages >= this")
    ap.add_argument("--end-page", type=int, default=None, help="Only process pages <= this")
    ap.add_argument("--limit", type=int, default=None, help="Only process the first N eligible pages")
    ap.add_argument("--min-words", type=int, default=15, help="Skip pages with fewer words than this")
    ap.add_argument("--resume", dest="resume", action="store_true", default=True)
    ap.add_argument("--no-resume", dest="resume", action="store_false")
    ap.add_argument("--retries", type=int, default=2, help="Retries per page on JSON-parse failure")
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "claims.jsonl"
    failed_log = out_dir / "failed_chunks.log"
    run_log = out_dir / "run.log"

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    book_id = data.get("book", {}).get("book_id", "book")
    pages = data.get("pages", [])
    log(run_log, f"Loaded {len(pages)} pages from {args.input} (book_id={book_id})")

    header_lines = find_repeated_header_lines(pages)
    if header_lines:
        log(run_log, f"Detected {len(header_lines)} repeated header/footer line(s) to strip, e.g.: "
                      f"{list(header_lines)[:3]}")

    eligible = []
    for p in pages:
        pn = p.get("page_number")
        if args.start_page is not None and pn < args.start_page:
            continue
        if args.end_page is not None and pn > args.end_page:
            continue
        if (p.get("word_count") or 0) < args.min_words:
            continue
        eligible.append(p)

    done_pages = already_done_pages(jsonl_path) if args.resume else set()
    if done_pages:
        log(run_log, f"Resuming: {len(done_pages)} page(s) already extracted, will be skipped")

    to_process = [p for p in eligible if p.get("page_number") not in done_pages]
    if args.limit is not None:
        to_process = to_process[: args.limit]

    log(run_log, f"{len(to_process)} page(s) to process this run")

    claim_counter = 0
    for i, page in enumerate(to_process, 1):
        page_number = page.get("page_number")
        chapter_title = page.get("chapter_title") or "Unspecified"
        chunk_id = f"{book_id}-p{page_number}"
        raw_text = page.get("text", "") or ""
        clean_text = strip_headers(raw_text, header_lines)

        if not clean_text.strip():
            log(run_log, f"[{i}/{len(to_process)}] page {page_number}: empty after header-strip, skipping")
            continue

        user_prompt = USER_TEMPLATE.format(
            book_title=args.book_title,
            author=args.author,
            chapter_title=chapter_title,
            page_number=page_number,
            chunk_id=chunk_id,
            source_text=clean_text,
        )

        claims = None
        last_raw = ""
        for attempt in range(1, args.retries + 2):
            try:
                raw = call_ollama(args.ollama_url, args.model, SYSTEM_PROMPT, user_prompt)
                last_raw = raw
                claims = parse_model_output(raw)
                break
            except urllib.error.URLError as e:
                log(run_log, f"[{i}/{len(to_process)}] page {page_number}: Ollama connection error "
                              f"({e}); is `ollama serve` running?")
                time.sleep(2)
            except Exception as e:
                log(run_log, f"[{i}/{len(to_process)}] page {page_number}: parse failed on attempt "
                              f"{attempt} ({e})")
                time.sleep(1)

        if claims is None:
            log(run_log, f"[{i}/{len(to_process)}] page {page_number}: FAILED after retries, logging raw output")
            with open(failed_log, "a", encoding="utf-8") as f:
                f.write(f"\n--- page {page_number} ({chunk_id}) ---\n{last_raw}\n")
            claims = []

        # Assign clean sequential claim_ids and stamp page/chapter metadata.
        for c in claims:
            claim_counter += 1
            c["claim_id"] = f"claim-{book_id}-{claim_counter:04d}"
            c.setdefault("location", "Unspecified")
            c["page_number"] = page_number
            c["chapter_title"] = chapter_title
            c["chunk_id"] = chunk_id

        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"page_number": page_number, "chunk_id": chunk_id, "claims": claims}) + "\n")

        log(run_log, f"[{i}/{len(to_process)}] page {page_number}: {len(claims)} claim(s) extracted")

    # --- Build combined outputs from the full jsonl (covers this run + prior resumed runs) ---
    all_claims = []
    if jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                all_claims.extend(row.get("claims", []))

    with open(out_dir / "claims_all.json", "w", encoding="utf-8") as f:
        json.dump(all_claims, f, indent=2, ensure_ascii=False)

    if all_claims:
        fieldnames = ["claim_id", "page_number", "chapter_title", "claim_type", "confidence",
                      "actor", "action", "event", "location", "time", "frame", "source",
                      "affected_entities", "named_entities", "themes", "claim_text"]
        with open(out_dir / "claims_all.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for c in all_claims:
                row = dict(c)
                for k in ("affected_entities", "named_entities", "themes"):
                    if k in row and isinstance(row[k], (list, dict)):
                        row[k] = json.dumps(row[k], ensure_ascii=False)
                writer.writerow(row)

    log(run_log, f"Done. Total claims across all runs: {len(all_claims)}. "
                  f"Outputs in {out_dir}/ (claims_all.json, claims_all.csv, claims.jsonl)")


if __name__ == "__main__":
    sys.exit(main())
