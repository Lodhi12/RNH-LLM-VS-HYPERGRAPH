from __future__ import annotations

import re
from typing import Any


NON_CONTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("contents", re.compile(r"\b(contents?|table of contents)\b", re.I)),
    ("copyright", re.compile(r"\b(copyright|all rights reserved)\b", re.I)),
    ("bibliography", re.compile(r"\b(bibliograph\w*|references|works cited)\b", re.I)),
    ("index", re.compile(r"\bindex\b", re.I)),
    ("notes", re.compile(r"\b(endnotes?|notes?)\b", re.I)),
    ("acknowledgements", re.compile(r"\backnowledg(e)?ments?\b", re.I)),
    ("promotional", re.compile(r"\b(follow (?:penguin|the publisher)|also by|praise for|about the author)\b", re.I)),
    ("title_page", re.compile(r"\b(title page|half title)\b", re.I)),
    ("dedication", re.compile(r"\bdedication\b", re.I)),
]


def classify_section(title: str, path: list[str], level: int) -> tuple[str, bool]:
    combined = " / ".join([*path, title]).strip()
    for kind, pattern in NON_CONTENT_PATTERNS:
        if pattern.search(combined):
            return kind, False
    if re.search(r"\b(front matter|publisher)\b", combined, re.I):
        return "front_matter", False
    if re.match(r"^\s*part\s+(?:[ivxlcdm]+|\d+)\b", title, re.I):
        return "part_header", False
    if re.search(r"\bappendix\b", combined, re.I):
        return "appendix", True
    if level == 0:
        return "front_matter", False
    return "body", True


def normalize_toc(raw_toc: list[list[Any]] | list[dict[str, Any]], page_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw_toc, start=1):
        if isinstance(item, dict):
            level = item.get("level")
            title = item.get("title")
            page = item.get("page") or item.get("page_start")
        else:
            try:
                level, title, page = item[:3]
            except (TypeError, ValueError):
                continue
        try:
            level = max(1, int(level))
            page = int(page)
        except (TypeError, ValueError):
            continue
        title = str(title or "").strip()
        if not title or not 1 <= page <= page_count:
            continue
        rows.append(
            {
                "section_id": f"section:{index:04d}",
                "toc_index": index,
                "level": level,
                "title": title,
                "page_start": page,
            }
        )

    rows.sort(key=lambda row: (row["page_start"], row["level"], row["toc_index"]))
    for index, row in enumerate(rows):
        next_page = rows[index + 1]["page_start"] if index + 1 < len(rows) else page_count + 1
        row["page_end"] = max(row["page_start"], next_page - 1)
    return rows


def context_for_page(page_number: int, toc: list[dict[str, Any]]) -> dict[str, Any]:
    if not toc:
        title = "Unstructured Body"
        return {
            "section_id": "section:unstructured-body",
            "section_title": title,
            "section_level": 0,
            "section_path": [title],
            "part_title": None,
            "chapter_title": title,
            "section_kind": "body_unstructured",
            "claim_eligible": True,
        }

    active = [row for row in toc if row["page_start"] <= page_number]
    if not active:
        title = "Front Matter"
        kind, eligible = classify_section(title, [title], 0)
        return {
            "section_id": "section:front-matter",
            "section_title": title,
            "section_level": 0,
            "section_path": [title],
            "part_title": None,
            "chapter_title": title,
            "section_kind": kind,
            "claim_eligible": eligible,
        }

    by_level: dict[int, dict[str, Any]] = {}
    for row in active:
        level = int(row["level"])
        by_level[level] = row
        for stale in list(by_level):
            if stale > level:
                del by_level[stale]

    path_rows = [by_level[level] for level in sorted(by_level)]
    current = path_rows[-1]
    path = [row["title"] for row in path_rows]
    part = next(
        (row["title"] for row in path_rows if re.match(r"^\s*part\b", row["title"], re.I)),
        None,
    )
    chapter = next(
        (row["title"] for row in reversed(path_rows) if not re.match(r"^\s*part\b", row["title"], re.I)),
        current["title"],
    )
    kind, eligible = classify_section(current["title"], path, int(current["level"]))
    return {
        "section_id": current["section_id"],
        "section_title": current["title"],
        "section_level": current["level"],
        "section_path": path,
        "part_title": part,
        "chapter_title": chapter,
        "section_kind": kind,
        "claim_eligible": eligible,
    }


def build_sections(toc: list[dict[str, Any]], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for page in pages:
        section = page["section"]
        key = section["section_id"]
        if key not in grouped:
            grouped[key] = {
                **section,
                "page_start": page["page_number"],
                "page_end": page["page_number"],
                "page_count": 0,
                "word_count": 0,
                "extraction_methods": {},
            }
        item = grouped[key]
        item["page_end"] = page["page_number"]
        item["page_count"] += 1
        item["word_count"] += page["counts"]["words"]
        method = page["extraction"]["method"]
        item["extraction_methods"][method] = item["extraction_methods"].get(method, 0) + 1
    return sorted(grouped.values(), key=lambda row: row["page_start"])
