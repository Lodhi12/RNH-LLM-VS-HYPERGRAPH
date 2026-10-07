"""Deterministic alignment of model-proposed strings to extracted source text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Alignment:
    start: int
    end: int
    match_count: int
    method: str
    source_text: str


def _all_starts(haystack: str, needle: str) -> list[int]:
    if not needle:
        return []
    starts: list[int] = []
    cursor = 0
    while True:
        index = haystack.find(needle, cursor)
        if index < 0:
            return starts
        starts.append(index)
        cursor = index + 1


def _normalize_whitespace_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    normalized: list[str] = []
    mapping: list[tuple[int, int]] = []
    runs = list(re.finditer(r"\S+", text, flags=re.UNICODE))
    for run_index, run in enumerate(runs):
        if run_index:
            prior = runs[run_index - 1]
            normalized.append(" ")
            mapping.append((prior.end(), run.start()))
        token = run.group(0)
        for offset, character in enumerate(token):
            normalized.append(character)
            mapping.append((run.start() + offset, run.start() + offset + 1))
    return "".join(normalized), mapping


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


_TYPOGRAPHY_EQUIVALENTS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "\u00ad": "-",
        "\u00a0": " ",
    }
)


def _normalize_source_conventions_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize typographic quotes and PDF line-wrap hyphenation with a map."""

    normalized: list[str] = []
    mapping: list[tuple[int, int]] = []
    runs = list(re.finditer(r"\S+", text, flags=re.UNICODE))
    for run_index, run in enumerate(runs):
        if run_index:
            prior = runs[run_index - 1]
            gap = text[prior.end() : run.start()]
            line_wrapped_hyphen = normalized and normalized[-1] == "-" and ("\n" in gap or "\r" in gap)
            punctuation_continuation = run.group(0)[0] in ",.;:!?)]}’”\"—–"
            if not line_wrapped_hyphen and not punctuation_continuation:
                normalized.append(" ")
                mapping.append((prior.end(), run.start()))
        token = run.group(0)
        for offset, character in enumerate(token):
            translated = character.translate(_TYPOGRAPHY_EQUIVALENTS)
            normalized.append(translated)
            mapping.append((run.start() + offset, run.start() + offset + 1))
    return "".join(normalized), mapping


def align_text(source: str, submitted: str) -> Alignment | None:
    """Resolve exact text first, then whitespace-only differences.

    Character offsets always point into the original source string.
    """

    if not submitted:
        return None
    exact_starts = _all_starts(source, submitted)
    if exact_starts:
        start = exact_starts[0]
        return Alignment(start, start + len(submitted), len(exact_starts), "exact", source[start : start + len(submitted)])

    normalized_source, mapping = _normalize_whitespace_with_map(source)
    normalized_submitted = normalize_whitespace(submitted)
    if not normalized_submitted or not mapping:
        return None
    normalized_starts = _all_starts(normalized_source, normalized_submitted)
    if not normalized_starts:
        convention_source, convention_mapping = _normalize_source_conventions_with_map(source)
        convention_submitted, _ = _normalize_source_conventions_with_map(submitted)
        convention_starts = _all_starts(convention_source, convention_submitted)
        if not convention_starts:
            return None
        convention_start = convention_starts[0]
        convention_end = convention_start + len(convention_submitted)
        source_start = convention_mapping[convention_start][0]
        source_end = convention_mapping[convention_end - 1][1]
        return Alignment(
            source_start,
            source_end,
            len(convention_starts),
            "source_normalized",
            source[source_start:source_end],
        )
    normalized_start = normalized_starts[0]
    normalized_end = normalized_start + len(normalized_submitted)
    source_start = mapping[normalized_start][0]
    source_end = mapping[normalized_end - 1][1]
    return Alignment(source_start, source_end, len(normalized_starts), "whitespace_normalized", source[source_start:source_end])


def ground_surface(surface: str | None, evidence: Iterable[dict]) -> dict | None:
    if not surface:
        return None
    for item in evidence:
        alignment = align_text(item["quote"], surface)
        if alignment:
            return {
                "evidence_id": item["evidence_id"],
                "quote_char_start": alignment.start,
                "quote_char_end": alignment.end,
                "match_count": alignment.match_count,
            }
    return None
