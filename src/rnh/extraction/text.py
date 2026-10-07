from __future__ import annotations

import re
from typing import Iterable


def normalize_text(text: str) -> str:
    """Normalize extraction noise while keeping stable page-relative offsets."""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def trim_offsets(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def paragraph_offsets(text: str) -> Iterable[tuple[int, int]]:
    start = 0
    for match in re.finditer(r"\n\s*\n+", text):
        left, right = trim_offsets(text, start, match.start())
        if left < right:
            yield left, right
        start = match.end()
    left, right = trim_offsets(text, start, len(text))
    if left < right:
        yield left, right


_ABBREVIATIONS = {
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "prof.",
    "sr.",
    "jr.",
    "st.",
    "vs.",
    "etc.",
    "e.g.",
    "i.e.",
    "p.",
    "pp.",
    "vol.",
    "no.",
}


def sentence_offsets(text: str, base_start: int, base_end: int) -> Iterable[tuple[int, int]]:
    """Yield conservative sentence-like offsets inside a paragraph."""
    paragraph = text[base_start:base_end]
    boundaries = [0]
    for match in re.finditer(r"(?<=[.!?])\s+(?=[A-Z0-9'\"(\[])", paragraph):
        prefix = paragraph[max(0, match.start() - 8) : match.start()].lower().strip()
        if any(prefix.endswith(abbreviation) for abbreviation in _ABBREVIATIONS):
            continue
        boundaries.append(match.end())
    boundaries.append(len(paragraph))

    for left, right in zip(boundaries, boundaries[1:]):
        start, end = trim_offsets(paragraph, left, right)
        if start < end:
            yield base_start + start, base_start + end


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))
