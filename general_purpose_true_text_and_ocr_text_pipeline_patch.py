"""
ocr_book.py — scanned book OCR pipeline (merged + patched)
===========================================================

Extracts clean text from scanned or born-digital book PDFs using
PaddleOCR PP-StructureV3. Includes a visual pre-pass that identifies
photograph and map pages without needing OCR.

QUICK START
-----------
1. Install deps:
       pip install paddleocr paddlepaddle-gpu pymupdf pillow numpy tqdm
       (use paddlepaddle instead of paddlepaddle-gpu for CPU-only)

2. Find photo/plate pages before the main run:
       python ocr_book.py --probe BetrayalofEastPakistan.pdf

3. Run OCR, keeping only meaningful images:
       python ocr_book.py --pdf BetrayalofEastPakistan.pdf ^
           --output ./output ^
           --auto-detect-watermarks ^
           --save-page-images visual ^
           --keep-page 1 --keep-page 2 ^
           --target-ocr-dpi 300 ^
           --device gpu --lang en

4. On CPU replace --device gpu with --device cpu

OUTPUT
------
output/
  text/
    full_document.md / full_document.txt   <- complete book text
    page_0001.md / page_0001.txt           <- per-page text
  images/                                  <- kept full-page images only
  images/figures/                          <- cropped figures from every page
  book_metadata.json
  ocr_book.log
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import math
import re
import shutil
import sys
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
try:
    import pymupdf as fitz
except ImportError:
    sys.exit("Missing 'PyMuPDF'. Install: pip install pymupdf")

try:
    from PIL import Image, ImageFilter, ImageEnhance, ImageStat
except ImportError:
    sys.exit("Missing 'Pillow'. Install: pip install Pillow")

try:
    from tqdm import tqdm
except ImportError:
    sys.exit("Missing 'tqdm'. Install: pip install tqdm")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    from paddleocr import PPStructureV3
    HAS_PADDLE = True
except ImportError:
    HAS_PADDLE = False

SCRIPT_VERSION = "4.0.0"
LOG = logging.getLogger("ocr_book")


# ===========================================================================
# Configuration
# ===========================================================================
DEFAULT_CONFIG = {
    # --- Watermarks ---------------------------------------------------------
    "watermarks": [],

    # --- Book metadata overrides -------------------------------------------
    "book_title": "",
    "book_author": "",
    "book_publisher": "",

    # --- Gibberish filtering -----------------------------------------------
    "gibberish_alpha_threshold": 0.25,
    "gibberish_min_length": 10,
    "gibberish_symbol_run_check": True,

    # --- Page classification -----------------------------------------------
    "page_classification": "auto",
    "forced_page_types": {},
    "min_words_for_text": 15,
    "blank_variance_threshold": 200,

    # --- Native PDF text layer ---------------------------------------------
    "native_text_min_words": 20,

    # --- Date / chapter extraction -----------------------------------------
    "extract_dates": True,
    "extra_date_patterns": [],
    "detect_chapters": True,
    "extra_chapter_patterns": [],

    # --- Image preprocessing -----------------------------------------------
    # Absolute pixel density target for the image handed to OCR.
    # Replaces the old relative upscale_threshold approach.
    "target_ocr_dpi": 300,
    "max_upscale_factor": 4,
    "sharpen_after_upscale": True,
    "contrast_boost": 1.15,
    "grayscale_for_ocr": True,

    # --- Header / footer detection -----------------------------------------
    "detect_headers_footers": True,
    "header_footer_lines": 3,

    # --- Page image retention ----------------------------------------------
    # "all"    : keep every page image (original behaviour)
    # "visual" : keep only photo/map/cover pages (recommended)
    # "none"   : never keep full page images; figure crops still saved
    "save_page_images": "visual",
    "keep_page_types": ["map", "photo", "cover"],
    "page_image_min_visual_fraction": 0.20,
    "page_image_max_words_for_visual": 120,
    "forced_keep_page_images": [],
    "forced_drop_page_images": [],

    # --- Figure crop size filter -------------------------------------------
    "always_keep_figure_crops": True,
    "min_figure_pixels": 20000,
    "min_figure_edge_px": 80,

    # --- Visual probe thresholds -------------------------------------------
    "probe_working_width": 700,
    "probe_dark_threshold": 0.30,
    "probe_midtone_threshold": 0.12,
    "probe_map_review_count": 5,
}


def load_config(config_path: Optional[str]) -> dict:
    config = dict(DEFAULT_CONFIG)
    if config_path:
        p = Path(config_path)
        if not p.exists():
            sys.exit(f"Config file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            user = json.load(f)
        config.update(user)
    return config


def generate_config(path: str) -> None:
    doc_config = {
        "_comment": "ocr_book config. All fields optional.",
        **DEFAULT_CONFIG,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc_config, f, indent=2, ensure_ascii=False)
    print(f"Config written to {path}")


# ===========================================================================
# Language patterns
# ===========================================================================

def get_date_patterns(lang: str, extra: list[str]) -> list[re.Pattern]:
    patterns = []
    if lang in ("en", "latin", "french", "german", "es", "pt", "it"):
        months_en = (
            "January|February|March|April|May|June|July|August|"
            "September|October|November|December"
        )
        patterns.append(re.compile(
            rf"\b(\d{{1,2}})\s+({months_en})\s+(\d{{4}})\b", re.IGNORECASE))
        patterns.append(re.compile(
            rf"\b({months_en})\s+(\d{{4}})\b", re.IGNORECASE))
    patterns.append(re.compile(r"\b(1[5-9]\d{2}|20[0-9]\d)\b"))
    patterns.append(re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}\b"))
    patterns.append(re.compile(r"\b\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}\b"))
    for p in extra:
        try:
            patterns.append(re.compile(p, re.IGNORECASE))
        except re.error as e:
            LOG.warning("Bad extra date pattern %r: %s", p, e)
    return patterns


def get_chapter_patterns(extra: list[dict]) -> list[dict]:
    built_in = [
        {"pattern": re.compile(
            r"^(?:CHAPTER|Chapter|chapter)\s+(\w+)\s*[:\.\-—]?\s*(.*)",
            re.MULTILINE), "number_group": 1, "title_group": 2},
        {"pattern": re.compile(
            r"^(?:PART|Part|part)\s+(\w+)\s*[:\.\-—]?\s*(.*)",
            re.MULTILINE), "number_group": 1, "title_group": 2},
        {"pattern": re.compile(
            r"^(?:SECTION|Section|section)\s+([\d\.]+)\s*[:\.\-—]?\s*(.*)",
            re.MULTILINE), "number_group": 1, "title_group": 2},
        {"pattern": re.compile(
            r"^(?:PROLOGUE|Prologue|EPILOGUE|Epilogue|PREFACE|Preface|"
            r"INTRODUCTION|Introduction|FOREWORD|Foreword|CONCLUSION|Conclusion)"
            r"\s*(.*)", re.MULTILINE), "number_group": 0, "title_group": 1},
    ]
    for entry in extra:
        try:
            built_in.append({
                "pattern": re.compile(entry["pattern"], re.MULTILINE),
                "number_group": entry.get("number_group", 1),
                "title_group": entry.get("title_group", 2),
            })
        except (re.error, KeyError) as e:
            LOG.warning("Bad extra chapter pattern: %s", e)
    return built_in


# ===========================================================================
# Text utilities
# ===========================================================================

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_gibberish(text: str, alpha_threshold: float, min_length: int,
                 symbol_run_check: bool = True) -> bool:
    stripped = text.strip()
    if len(stripped) < min_length:
        return False
    if alpha_threshold <= 0:
        return False
    meaningful = sum(1 for c in stripped if c.isalpha() or c.isdigit())
    total = len(stripped)
    if total == 0:
        return True
    if meaningful / total < alpha_threshold:
        return True
    if symbol_run_check and re.search(r"[^\w\s.,;:!?'\"\-()]{5,}", stripped, re.UNICODE):
        return True
    return False


def clean_watermarks(text: str, watermarks: list[str]) -> str:
    if not watermarks:
        return text
    for wm in watermarks:
        text = re.sub(re.escape(wm), "", text, flags=re.IGNORECASE)
        chars = [c for c in wm if c.strip()]
        if len(chars) > 4:
            spaced = r"\s*".join(re.escape(c) for c in chars)
            text = re.sub(spaced, "", text, flags=re.IGNORECASE)
    return text


def clean_ocr_text(text: str, config: dict) -> str:
    text = clean_watermarks(text, config.get("watermarks", []))
    thresh = config.get("gibberish_alpha_threshold", 0.25)
    min_len = config.get("gibberish_min_length", 10)
    symbol_run_check = config.get("gibberish_symbol_run_check", True)
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            cleaned.append("")
            continue
        if is_gibberish(s, thresh, min_len, symbol_run_check):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def markdown_to_plain(md: str) -> str:
    t = md
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\|", " ", t)
    t = re.sub(r"^-{3,}$", "", t, flags=re.MULTILINE)
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", t)
    t = re.sub(r"\*(.*?)\*", r"\1", t)
    t = re.sub(r"!\[.*?\]\(.*?\)", "", t)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract_dates(text: str, patterns: list[re.Pattern]) -> list[dict]:
    results = []
    seen: set = set()
    for pattern in patterns:
        for m in pattern.finditer(text):
            date_str = m.group(0)
            if date_str in seen:
                continue
            seen.add(date_str)
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            context = text[start:end].replace("\n", " ").strip()
            results.append({"date": date_str, "context": context})
    return results


def detect_chapter(text: str, patterns: list[dict]) -> Optional[dict]:
    check = text[:500]
    for entry in patterns:
        m = entry["pattern"].search(check)
        if m:
            ng = entry["number_group"]
            tg = entry["title_group"]
            num = m.group(ng) if ng > 0 and ng <= len(m.groups()) else m.group(0).split()[0]
            title = ""
            if tg <= len(m.groups()) and m.group(tg):
                title = m.group(tg).strip()
            return {"number": num, "title": title,
                    "matched_text": m.group(0).strip()}
    return None


def detect_page_number(text: str, n_lines: int = 3) -> Optional[str]:
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if not lines:
        return None
    candidates = lines[:n_lines] + lines[-n_lines:]
    for line in candidates:
        if re.match(r"^\d{1,4}$", line):
            return line
        if re.match(r"^[ivxlcdmIVXLCDM]+$", line) and len(line) < 10:
            return line
    return None


def detect_header(text: str, n_lines: int = 3) -> Optional[str]:
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) < 4:
        return None
    for line in lines[:n_lines]:
        if re.match(r"^\d{1,4}$", line):
            continue
        if re.match(r"^[ivxlcdmIVXLCDM]+$", line):
            continue
        if 3 < len(line) < 100:
            return line
        break
    return None


# ===========================================================================
# Visual pre-pass (no OCR needed)
# ===========================================================================

def _probe_page_gray(doc, page_index: int, target_w: int):
    """Grayscale numpy array of a page at a working resolution."""
    page = doc[page_index]
    imgs = page.get_images(full=True)
    if len(imgs) == 1:
        base = doc.extract_image(imgs[0][0])
        im = Image.open(io.BytesIO(base["image"]))
    else:
        zoom = 150 / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        im = Image.open(io.BytesIO(pix.tobytes("png")))
    im = im.convert("L")
    w, h = im.size
    if w > target_w:
        im = im.resize((target_w, max(1, int(h * target_w / w))), Image.LANCZOS)
    arr = np.asarray(im, dtype=np.float32)
    im.close()
    return arr


def probe_page_tone(arr) -> dict:
    """
    Measures whether a page looks like a photograph vs printed text.

    dark_fraction   : share of pixels that are ink-dark.
                      High on covers and dark photographs.
    midtone_fraction: share of pixels in the grey middle.
                      This is the strongest photograph signal —
                      halftone printing fills the midtones; text does not.
    row_periodicity : how regularly the page alternates dark/light rows.
                      Set type is very periodic; pictures and maps are not.
    blank_row_fraction: share of near-white rows (interline gaps in text).
    """
    lo, hi = np.percentile(arr, 2), np.percentile(arr, 98)
    if hi - lo < 1:
        return {"dark_fraction": 0.0, "midtone_fraction": 0.0,
                "row_periodicity": 0.0, "blank_row_fraction": 1.0}

    n = np.clip((arr - lo) / (hi - lo), 0, 1)
    dark = float((n < 0.5).mean())
    mid = float(((n >= 0.35) & (n < 0.75)).mean())

    h_sz, w_sz = n.shape
    core = n[int(h_sz * 0.08):int(h_sz * 0.92),
              int(w_sz * 0.08):int(w_sz * 0.92)]
    row = 1.0 - core.mean(axis=1)
    if row.size == 0 or row.max() <= 0:
        return {"dark_fraction": round(dark, 4), "midtone_fraction": round(mid, 4),
                "row_periodicity": 0.0, "blank_row_fraction": 1.0}

    blank_row = float((row < 0.12 * row.max()).mean())
    r = row - row.mean()
    if r.std() == 0:
        band = 0.0
    else:
        ac = np.correlate(r, r, mode="full")[len(r) - 1:]
        ac = ac / ac[0]
        hi_lag = min(40, len(ac) - 1)
        band = float(ac[4:hi_lag].max()) if hi_lag > 4 else 0.0

    return {"dark_fraction": round(dark, 4), "midtone_fraction": round(mid, 4),
            "row_periodicity": round(band, 4), "blank_row_fraction": round(blank_row, 4)}


def probe_visual_pages(pdf_path, config: dict) -> dict:
    """
    Scan the PDF and classify each page as photo / map-candidate / text.
    Returns photo_pages (safe to auto-keep) and map_candidates (review list).
    """
    if not HAS_NUMPY:
        raise RuntimeError("Visual probe needs numpy: pip install numpy")

    working_w = int(config.get("probe_working_width", 700))
    dark_t = float(config.get("probe_dark_threshold", 0.30))
    mid_t = float(config.get("probe_midtone_threshold", 0.12))
    review_n = int(config.get("probe_map_review_count", 5))

    doc = fitz.open(str(pdf_path))
    rows = []
    for i in range(doc.page_count):
        try:
            m = probe_page_tone(_probe_page_gray(doc, i, working_w))
        except Exception as exc:
            LOG.warning("probe failed on page %d: %s", i + 1, exc)
            continue
        m["page"] = i + 1
        m["photo_like"] = (m["dark_fraction"] >= dark_t or
                           m["midtone_fraction"] >= mid_t)
        rows.append(m)
    doc.close()

    photo_pages = [r["page"] for r in rows if r["photo_like"]]
    non_photo = sorted([r for r in rows if not r["photo_like"]],
                       key=lambda r: r["row_periodicity"])
    map_candidates = [r["page"] for r in non_photo[:review_n]]

    return {"photo_pages": photo_pages, "map_candidates": map_candidates,
            "pages": rows}


def print_visual_probe(pdf_path: str, config: dict) -> None:
    print(f"\nScanning: {pdf_path}")
    res = probe_visual_pages(pdf_path, config)
    print(f"{'pg':>4} {'dark':>7} {'midtone':>8} {'periodic':>9} {'blank':>7}  verdict")
    for r in res["pages"]:
        verdict = "PHOTO" if r["photo_like"] else (
            "map?" if r["page"] in res["map_candidates"] else "")
        print(f"{r['page']:>4} {r['dark_fraction']:>7.3f} "
              f"{r['midtone_fraction']:>8.3f} {r['row_periodicity']:>9.3f} "
              f"{r['blank_row_fraction']:>7.3f}  {verdict}")
    keep = sorted(res["photo_pages"])
    print("\nauto-keep photos:  " +
          (" ".join(f"--keep-page {p}" for p in keep) or "(none found)"))
    print("review for maps:   " +
          (" ".join(str(p) for p in sorted(res["map_candidates"])) or "(none)"))
    print()


# ===========================================================================
# Layout analysis (runs on PP-Structure JSON output)
# ===========================================================================

VISUAL_LAYOUT_LABELS = {
    "image", "figure", "picture", "photo",
    "chart", "graph", "diagram", "seal",
}


def iter_layout_boxes(structured: Any) -> Iterator[tuple[str, list[float]]]:
    """Yield (label, [x1, y1, x2, y2]) from a PP-Structure JSON blob."""
    stack = [structured]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            label = (node.get("label") or node.get("cls_name") or
                     node.get("type") or "")
            coord = (node.get("coordinate") or node.get("bbox") or
                     node.get("box") or node.get("region_bbox"))
            if (isinstance(label, str) and
                    isinstance(coord, (list, tuple)) and len(coord) == 4 and
                    all(isinstance(v, (int, float)) for v in coord)):
                x1, y1, x2, y2 = (float(v) for v in coord)
                yield label.strip().lower(), [
                    min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


def visual_area_fraction(structured: Any, img_w: int, img_h: int) -> float:
    """Fraction of the OCR image covered by picture-type layout blocks."""
    page_area = float(img_w) * float(img_h)
    if page_area <= 0:
        return 0.0
    total = 0.0
    seen: set = set()
    for label, (x1, y1, x2, y2) in iter_layout_boxes(structured):
        if label not in VISUAL_LAYOUT_LABELS:
            continue
        key = (label, round(x1), round(y1), round(x2), round(y2))
        if key in seen:
            continue
        seen.add(key)
        total += max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return min(1.0, total / page_area)


def collect_ocr_confidence(structured: Any) -> Optional[float]:
    """Mean recognition score, found wherever the JSON happens to put it."""
    scores: list[float] = []
    stack = [structured]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in ("rec_scores", "rec_score", "scores", "score", "confidence"):
                val = node.get(key)
                if isinstance(val, (int, float)):
                    scores.append(float(val))
                elif isinstance(val, (list, tuple)):
                    scores.extend(float(v) for v in val
                                  if isinstance(v, (int, float)))
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    scores = [s for s in scores if 0.0 <= s <= 1.0]
    return round(sum(scores) / len(scores), 4) if scores else None


# ===========================================================================
# Page image keep/drop decision
# ===========================================================================

def should_keep_page_image(page_number: int, page_type: str,
                            visual_fraction: float, word_count: int,
                            figures_count: int, config: dict) -> tuple[bool, str]:
    mode = config.get("save_page_images", "visual")

    if page_number in set(config.get("forced_drop_page_images", [])):
        return False, "forced_drop"
    if page_number in set(config.get("forced_keep_page_images", [])):
        return True, "forced_keep"

    if mode == "all":
        return True, "save_page_images=all"
    if mode == "none":
        return False, "save_page_images=none"

    if page_type in set(config.get("keep_page_types", [])):
        return True, f"page_type={page_type}"

    min_frac = float(config.get("page_image_min_visual_fraction", 0.20))
    max_words = int(config.get("page_image_max_words_for_visual", 120))

    if visual_fraction >= min_frac and word_count <= max_words:
        return True, f"visual_area={visual_fraction:.2f}"
    if visual_fraction >= min_frac and word_count > max_words:
        return False, (f"figure present but page is prose "
                       f"({word_count} words) — crop kept, page dropped")
    if figures_count and word_count <= max_words:
        return True, f"figure_crops={figures_count}, sparse text"

    return False, f"text page (visual_area={visual_fraction:.2f})"


def promote_or_discard_page_image(staged_path: Optional[Path],
                                   images_dir: Path, keep: bool) -> Optional[str]:
    """Move staged page image to images/ or delete it."""
    if staged_path is None or not staged_path.exists():
        return None
    if not keep:
        try:
            staged_path.unlink()
        except OSError:
            pass
        return None
    images_dir.mkdir(parents=True, exist_ok=True)
    dest = images_dir / staged_path.name
    shutil.move(str(staged_path), str(dest))
    return dest.name


# ===========================================================================
# Image extraction and preprocessing
# ===========================================================================

def compute_image_stats(image_path: Path) -> dict:
    img = Image.open(image_path)
    gray = img.convert("L") if img.mode != "L" else img
    stat = ImageStat.Stat(gray)
    mean_val = stat.mean[0]
    variance = stat.var[0]
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_mean = ImageStat.Stat(edges).mean[0]
    color_diff = 0.0
    if img.mode in ("RGB", "RGBA", "CMYK") and HAS_NUMPY:
        channels = img.split()[:3]
        arrs = [np.array(c, dtype=float) for c in channels]
        color_diff = float(
            np.mean(np.abs(arrs[0] - arrs[1]) + np.abs(arrs[1] - arrs[2])) / 255.0)
    elif img.mode in ("RGB", "RGBA"):
        r_stat = ImageStat.Stat(img.split()[0])
        g_stat = ImageStat.Stat(img.split()[1])
        b_stat = ImageStat.Stat(img.split()[2])
        color_diff = (abs(r_stat.mean[0] - g_stat.mean[0]) +
                      abs(g_stat.mean[0] - b_stat.mean[0])) / 255.0
    w, h = img.size
    img.close()
    return {"width": w, "height": h,
            "mean_brightness": round(mean_val, 2),
            "variance": round(variance, 2),
            "edge_density": round(edge_mean, 2),
            "color_difference": round(color_diff, 4)}


def extract_page_image(doc, page_index: int, dest_dir: Path,
                       dpi: int, overwrite: bool) -> dict:
    """Extract or render a page image into dest_dir."""
    page = doc[page_index]
    page_number = page_index + 1
    page_rect = page.rect

    images = page.get_images(full=True)
    embedded = None
    if len(images) == 1:
        xref = images[0][0]
        rects = page.get_image_rects(xref)
        if rects:
            r = rects[0]
            page_area = page_rect.width * page_rect.height
            img_area = r.width * r.height
            if page_area > 0 and (img_area / page_area) > 0.80:
                embedded = xref

    dest_dir.mkdir(parents=True, exist_ok=True)

    if embedded is not None:
        base = doc.extract_image(embedded)
        ext = base["ext"]
        filename = f"page_{page_number:04d}.{ext}"
        out_path = dest_dir / filename
        if overwrite or not out_path.exists():
            out_path.write_bytes(base["image"])
        return {"path": out_path, "filename": filename, "method": "embedded",
                "width": base["width"], "height": base["height"],
                "page_width_points": page_rect.width}

    filename = f"page_{page_number:04d}.png"
    out_path = dest_dir / filename
    if overwrite or not out_path.exists():
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(str(out_path))
    img = Image.open(out_path)
    w, h = img.size
    img.close()
    return {"path": out_path, "filename": filename, "method": "rendered",
            "width": w, "height": h, "page_width_points": page_rect.width}


def compute_upscale_factor(image_width: int, page_width_points: float,
                            config: dict) -> int:
    """How much to upscale to reach target_ocr_dpi."""
    target_dpi = float(config.get("target_ocr_dpi", 300))
    max_factor = int(config.get("max_upscale_factor", 4))
    page_inches = (page_width_points or 595.276) / 72.0
    target_px = target_dpi * page_inches
    if image_width <= 0 or image_width >= target_px:
        return 1
    return max(1, min(max_factor, math.ceil(target_px / image_width)))


def preprocess_image(image_path: Path, work_dir: Path,
                     page_width_points: float, config: dict) -> dict:
    """Upscale and enhance an image for OCR. Returns info dict."""
    img = Image.open(image_path)
    w, h = img.size
    factor = compute_upscale_factor(w, page_width_points, config)

    if factor <= 1:
        img.close()
        return {"path": image_path, "upscaled": False,
                "factor": 1, "width": w, "height": h}

    img = img.resize((w * factor, h * factor), Image.LANCZOS)
    if config.get("sharpen_after_upscale", True):
        img = img.filter(ImageFilter.SHARPEN)
    contrast = config.get("contrast_boost", 1.15)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if config.get("grayscale_for_ocr", True) and img.mode not in ("L", "1"):
        img = img.convert("L")

    out_path = work_dir / f"{image_path.stem}_enhanced.png"
    out_w, out_h = img.size
    img.save(out_path, "PNG")
    img.close()
    return {"path": out_path, "upscaled": True,
            "factor": factor, "width": out_w, "height": out_h}


def extract_embedded_figures(doc, page_index: int,
                              figures_dir: Path, config: dict) -> list[dict]:
    """Pull photo objects from a born-digital page (no OCR)."""
    page = doc[page_index]
    page_number = page_index + 1
    min_pixels = int(config.get("min_figure_pixels", 20000))
    min_edge = int(config.get("min_figure_edge_px", 80))
    figures: list[dict] = []
    seen: set = set()
    for info in page.get_images(full=True):
        xref = info[0]
        if xref in seen:
            continue
        seen.add(xref)
        try:
            base = doc.extract_image(xref)
        except Exception as exc:
            LOG.debug("embedded image %s on page %d failed: %s",
                      xref, page_number, exc)
            continue
        fw, fh = base.get("width", 0), base.get("height", 0)
        if fw < min_edge or fh < min_edge or (fw * fh) < min_pixels:
            continue
        figures_dir.mkdir(parents=True, exist_ok=True)
        name = f"page_{page_number:04d}_embedded_{xref}.{base['ext']}"
        dest = figures_dir / name
        dest.write_bytes(base["image"])
        figures.append({"original_ref": f"xref:{xref}", "filename": name,
                         "path": str(dest), "source": "embedded",
                         "width": fw, "height": fh})
    return figures


# ===========================================================================
# Native (born-digital) PDF text extraction
# ===========================================================================

def extract_native_text(page) -> str:
    try:
        return page.get_text("text").strip()
    except Exception:
        return ""


def should_use_native_text(native_text: str, min_words: int) -> bool:
    if not native_text:
        return False
    return len(native_text.split()) >= min_words


def classify_native_text_page(page_number: int, config: dict) -> str:
    forced = config.get("forced_page_types", {})
    for key in (str(page_number), page_number):
        if key in forced:
            return forced[key]
    return "text"


# ===========================================================================
# Page classification
# ===========================================================================

def classify_page_content(img_stats: dict, text: str, page_number: int,
                           total_pages: int, config: dict) -> str:
    forced = config.get("forced_page_types", {})
    for key in (str(page_number), page_number):
        if key in forced:
            return forced[key]
    if config.get("page_classification") == "none":
        return "text"
    word_count = len(text.split()) if text else 0
    min_words = config.get("min_words_for_text", 15)
    blank_thresh = config.get("blank_variance_threshold", 200)
    if img_stats["variance"] < blank_thresh and word_count < 5:
        return "blank"
    if page_number <= 2 and word_count < min_words:
        return "cover"
    if page_number == total_pages and word_count < min_words:
        return "cover"
    if img_stats["color_difference"] > 0.05 and word_count < min_words:
        return "photo"
    if word_count < min_words and img_stats["edge_density"] > 15:
        return "map"
    if word_count < 5:
        return "blank"
    if word_count < min_words:
        return "photo"
    return "text"


# ===========================================================================
# Auto-detect watermarks
# ===========================================================================

def auto_detect_watermarks(doc, pipeline, images_dir: Path, work_dir: Path,
                            dpi: int, config: dict,
                            sample_size: int = 10) -> list[str]:
    import random
    total = doc.page_count
    start = min(5, total // 4)
    end_idx = max(total - 3, total * 3 // 4)
    pool = list(range(start, end_idx))
    indices = sorted(random.sample(pool, min(sample_size, len(pool))))
    LOG.info("Auto-detecting watermarks (sampling %d pages)...", len(indices))

    staging = work_dir / "wm_staging"
    staging.mkdir(parents=True, exist_ok=True)
    all_lines: list[list[str]] = []
    for idx in indices:
        try:
            img_info = extract_page_image(doc, idx, staging, dpi, overwrite=False)
            prep = preprocess_image(img_info["path"], work_dir,
                                    img_info["page_width_points"], config)
            result = run_ocr(pipeline, prep["path"], work_dir,
                             figures_dir=None, page_stem=f"wm_{idx}",
                             config=config)
            lines = [l.strip().lower()
                     for l in result["markdown"].split("\n") if l.strip()]
            all_lines.append(lines)
            if prep["path"] != img_info["path"] and prep["path"].exists():
                prep["path"].unlink()
        except Exception as e:
            LOG.debug("Watermark sample fail page %d: %s", idx + 1, e)

    shutil.rmtree(staging, ignore_errors=True)

    if len(all_lines) < 3:
        return []
    line_count: Counter = Counter()
    for page_lines in all_lines:
        for line in set(page_lines):
            if len(line) > 3:
                line_count[line] += 1
    threshold_count = len(all_lines) * 0.6
    watermarks = [line for line, count in line_count.items()
                  if count >= threshold_count and len(line) < 100]
    if watermarks:
        LOG.info("Detected watermarks: %s", watermarks)
    else:
        LOG.info("No watermarks detected.")
    return watermarks


# ===========================================================================
# OCR runner
# ===========================================================================

FIGURE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _json_default(obj: Any):
    if HAS_NUMPY:
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
    return str(obj)


def run_ocr(pipeline, image_path: Path, work_dir: Path,
            figures_dir: Optional[Path], page_stem: str,
            config: dict) -> dict:
    output = pipeline.predict(str(image_path))
    results = list(output)
    if not results:
        raise RuntimeError(f"PaddleOCR returned no result for {image_path}")
    res = results[0]

    structured = None
    try:
        structured = res.json
    except Exception:
        pass

    page_tmp = work_dir / page_stem
    page_tmp.mkdir(parents=True, exist_ok=True)

    try:
        if structured is None:
            res.save_to_json(save_path=str(page_tmp))
            json_files = sorted(page_tmp.glob("*.json"))
            if json_files:
                with open(json_files[0], "r", encoding="utf-8") as f:
                    structured = json.load(f)
            else:
                structured = {}
        structured = json.loads(json.dumps(structured, default=_json_default))

        markdown_text = ""
        figures: list[dict] = []
        try:
            res.save_to_markdown(save_path=str(page_tmp))
            md_files = sorted(page_tmp.glob("*.md"))
            if md_files:
                markdown_text = md_files[0].read_text(encoding="utf-8")

            if figures_dir is not None:
                min_pixels = int(config.get("min_figure_pixels", 20000))
                min_edge = int(config.get("min_figure_edge_px", 80))
                figure_files = sorted(
                    p for p in page_tmp.rglob("*")
                    if p.is_file() and p.suffix.lower() in FIGURE_EXTS)
                if figure_files:
                    figures_dir.mkdir(parents=True, exist_ok=True)
                    basename_map = {}
                    for fig_path in figure_files:
                        try:
                            with Image.open(fig_path) as fim:
                                fw, fh = fim.size
                        except Exception:
                            fw = fh = 0
                        if (fw and fh and
                                (fw < min_edge or fh < min_edge or
                                 fw * fh < min_pixels)):
                            continue
                        dest_name = f"{page_stem}_{fig_path.name}"
                        dest_path = figures_dir / dest_name
                        dest_path.write_bytes(fig_path.read_bytes())
                        figures.append({"original_ref": fig_path.name,
                                         "filename": dest_name,
                                         "path": str(dest_path)})
                        basename_map[fig_path.name] = dest_name

                    def _rewrite(m: re.Match) -> str:
                        alt, link = m.group(1), m.group(2)
                        bn = Path(link).name
                        if bn in basename_map:
                            return f"![{alt}](images/figures/{basename_map[bn]})"
                        return m.group(0)

                    markdown_text = re.sub(r"!\[(.*?)\]\((.*?)\)",
                                            _rewrite, markdown_text)
        except Exception as exc:
            LOG.warning("Markdown/figure issue %s: %s", page_stem, exc)

        conf_avg = collect_ocr_confidence(structured)

        return {"structured": structured, "markdown": markdown_text,
                "figures": figures, "confidence_avg": conf_avg}
    finally:
        shutil.rmtree(page_tmp, ignore_errors=True)


# ===========================================================================
# Main pipeline
# ===========================================================================

@dataclass
class RunStats:
    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    native_text_pages: int = 0
    page_images_kept: int = 0
    failures: list = field(default_factory=list)


def build_pipeline(args: argparse.Namespace):
    if not HAS_PADDLE:
        sys.exit("PaddleOCR not installed. Run: pip install paddleocr")
    LOG.info("Loading PP-StructureV3 (downloads models on first run)...")
    return PPStructureV3(
        lang=args.lang,
        device=args.device,
        use_doc_orientation_classify=not args.no_doc_orientation,
        use_doc_unwarping=not args.no_unwarping,
        use_textline_orientation=not args.no_textline_orientation,
        use_table_recognition=not args.no_tables,
        use_formula_recognition=args.formula_recognition,
        use_seal_recognition=args.seal_recognition,
        use_chart_recognition=args.chart_recognition,
    )


def process_pdf(args: argparse.Namespace) -> None:
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}")

    config = load_config(args.config)

    # CLI overrides
    if args.watermark:
        config["watermarks"] = list(set(config.get("watermarks", []) +
                                        args.watermark))
    if args.native_text_min_words is not None:
        config["native_text_min_words"] = args.native_text_min_words
    if args.save_page_images is not None:
        config["save_page_images"] = args.save_page_images
    if args.keep_page:
        config["forced_keep_page_images"] = sorted(
            set(config.get("forced_keep_page_images", [])) |
            set(args.keep_page))
    if args.target_ocr_dpi is not None:
        config["target_ocr_dpi"] = args.target_ocr_dpi

    out = Path(args.output).expanduser().resolve()
    images_dir = out / "images"
    figures_dir = out / "images" / "figures"
    text_dir = out / "text"
    work_dir = out / "_work"
    staging_dir = work_dir / "pages"
    for d in (images_dir, figures_dir, text_dir, work_dir, staging_dir):
        d.mkdir(parents=True, exist_ok=True)

    log_path = out / "ocr_book.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path),
                  logging.StreamHandler(sys.stdout)],
    )

    doc = fitz.open(str(pdf_path))
    total_pages = doc.page_count
    start = args.start_page or 1
    end = args.end_page or total_pages
    if start < 1 or end > total_pages or start > end:
        sys.exit(f"Invalid page range {start}-{end} for {total_pages}-page PDF")

    LOG.info("PDF: %s | %d pages | processing %d-%d",
             pdf_path.name, total_pages, start, end)
    LOG.info("save_page_images: %s | target_ocr_dpi: %s",
             config["save_page_images"], config["target_ocr_dpi"])
    LOG.info("forced_keep_page_images: %s",
             config.get("forced_keep_page_images", []))

    pipeline = build_pipeline(args)

    if args.auto_detect_watermarks:
        detected = auto_detect_watermarks(
            doc, pipeline, images_dir, work_dir, args.dpi, config)
        config["watermarks"] = list(set(config.get("watermarks", []) + detected))

    date_patterns = (get_date_patterns(args.lang,
                                        config.get("extra_date_patterns", []))
                     if config.get("extract_dates", True) else [])
    chapter_patterns = (get_chapter_patterns(
                            config.get("extra_chapter_patterns", []))
                         if config.get("detect_chapters", True) else [])

    stats = RunStats(total=end - start + 1)
    page_results: list[dict] = []
    all_dates: list[dict] = []
    chapters: list[dict] = []
    t0 = time.time()

    for page_idx in tqdm(range(start - 1, end), desc="OCR", unit="pg"):
        page_number = page_idx + 1
        page_md_path = text_dir / f"page_{page_number:04d}.md"

        # Resume: skip already-processed pages
        if not args.overwrite and page_md_path.exists():
            md_text = page_md_path.read_text(encoding="utf-8")
            plain = clean_ocr_text(markdown_to_plain(md_text), config)
            dates = extract_dates(plain, date_patterns) if date_patterns else []
            for d in dates:
                d["page"] = page_number
            all_dates.extend(dates)
            chap = detect_chapter(plain, chapter_patterns) if chapter_patterns else None
            if chap:
                chap["page"] = page_number
                chapters.append(chap)
            page_results.append({
                "page_number": page_number, "page_type": "text",
                "word_count": len(plain.split()), "char_count": len(plain),
                "image_file": None, "page_image_kept": False,
                "extraction_method": "skipped",
                "warnings": ["skipped - already processed"],
                "_text": plain,
            })
            stats.skipped += 1
            continue

        t_page = time.time()
        warnings: list[str] = []

        try:
            page = doc[page_idx]
            page_has_raster = bool(page.get_images(full=True))

            # Decide native text vs OCR
            use_native = False
            native_raw = ""
            native_word_count = 0
            if args.native_text_mode != "force-ocr":
                native_raw = extract_native_text(page)
                native_word_count = len(native_raw.split()) if native_raw else 0
                if args.native_text_mode == "force-native":
                    use_native = True
                elif should_use_native_text(
                        native_raw, config.get("native_text_min_words", 20)):
                    use_native = True

            figures: list[dict] = []
            was_upscaled = False
            ocr_confidence = None
            visual_fraction = 0.0
            img_info = None
            staged_path = None
            img_w = img_h = 0
            img_size = 0

            # Skip page render for pure native-text pages
            need_page_raster = (
                not use_native or page_has_raster or
                config.get("save_page_images") == "all"
            )

            if need_page_raster:
                img_info = extract_page_image(
                    doc, page_idx, staging_dir, args.dpi, overwrite=True)
                staged_path = img_info["path"]
                img_w, img_h = img_info["width"], img_info["height"]
                img_size = staged_path.stat().st_size

            if use_native:
                plain = clean_ocr_text(native_raw, config)
                md_text = plain
                extraction_method = "native_pdf_text"
                if page_has_raster:
                    figures = extract_embedded_figures(
                        doc, page_idx, figures_dir, config)
                if (args.native_text_mode == "force-native" and
                        native_word_count < config.get("native_text_min_words", 20)):
                    warnings.append(
                        f"forced native text but only {native_word_count} words "
                        "extracted (page may actually be a scanned image)")
            else:
                prep = preprocess_image(
                    staged_path, work_dir,
                    page_width_points=img_info["page_width_points"],
                    config=config)
                was_upscaled = prep["upscaled"]
                if prep["factor"] > 1:
                    warnings.append(
                        f"upscaled {prep['factor']}x to target "
                        f"{config.get('target_ocr_dpi', 300)} dpi — "
                        "accuracy capped by source scan resolution")

                ocr_result = run_ocr(
                    pipeline, prep["path"], work_dir,
                    figures_dir=figures_dir,
                    page_stem=f"page_{page_number:04d}",
                    config=config)

                md_text = clean_ocr_text(ocr_result["markdown"], config)
                plain = clean_ocr_text(markdown_to_plain(md_text), config)
                ocr_confidence = ocr_result["confidence_avg"]
                figures = ocr_result["figures"]
                extraction_method = img_info["method"]

                visual_fraction = visual_area_fraction(
                    ocr_result["structured"], prep["width"], prep["height"])

                if ocr_confidence is not None and ocr_confidence < 0.7:
                    warnings.append(f"low OCR confidence: {ocr_confidence:.2f}")

                if prep["path"] != staged_path and prep["path"].exists():
                    prep["path"].unlink()

            # Dates and chapters
            dates = extract_dates(plain, date_patterns) if date_patterns else []
            for d in dates:
                d["page"] = page_number
            all_dates.extend(dates)
            chap = detect_chapter(plain, chapter_patterns) if chapter_patterns else None
            if chap:
                chap["page"] = page_number
                chapters.append(chap)

            # Page type classification
            word_count = len(plain.split())
            if use_native and not page_has_raster:
                pg_type = classify_native_text_page(page_number, config)
            elif staged_path and staged_path.exists():
                img_stats = compute_image_stats(staged_path)
                pg_type = classify_page_content(
                    img_stats, plain, page_number, total_pages, config)
            else:
                pg_type = classify_native_text_page(page_number, config)

            # Keep or drop the page image
            keep_img, keep_reason = should_keep_page_image(
                page_number=page_number, page_type=pg_type,
                visual_fraction=visual_fraction, word_count=word_count,
                figures_count=len(figures), config=config)
            final_image_name = promote_or_discard_page_image(
                staged_path, images_dir, keep_img)
            if final_image_name:
                stats.page_images_kept += 1

            elapsed = round(time.time() - t_page, 2)
            detect_hf = config.get("detect_headers_footers", True)
            hf_lines = config.get("header_footer_lines", 3)

            pr = {
                "page_number": page_number,
                "page_label": page.get_label() or None,
                "page_type": pg_type,
                "printed_page_number": (detect_page_number(plain, hf_lines)
                                         if detect_hf else None),
                "header": (detect_header(plain, hf_lines) if detect_hf else None),
                "word_count": word_count,
                "char_count": len(plain),
                "image_file": final_image_name,
                "page_image_kept": bool(final_image_name),
                "page_image_decision": keep_reason,
                "visual_area_fraction": round(visual_fraction, 4),
                "image_size": f"{img_w}x{img_h}" if img_w else None,
                "image_size_bytes": img_size or None,
                "extraction_method": extraction_method,
                "was_upscaled": was_upscaled,
                "ocr_confidence": ocr_confidence,
                "ocr_time_seconds": elapsed,
                "dates_mentioned": [d["date"] for d in dates],
                "chapter_start": chap,
                "figures_count": len(figures),
                "figures": figures,
                "warnings": warnings,
                "_text": plain,
            }
            page_results.append(pr)

            page_md_path.write_text(md_text, encoding="utf-8")
            (text_dir / f"page_{page_number:04d}.txt").write_text(
                plain, encoding="utf-8")

            stats.processed += 1
            if use_native:
                stats.native_text_pages += 1

        except Exception as exc:
            LOG.error("FAILED page %d: %s", page_number, exc)
            LOG.debug(traceback.format_exc())
            stats.failed += 1
            stats.failures.append({"page": page_number, "error": str(exc)})

    # Assemble combined files
    LOG.info("Assembling combined text...")
    assemble_combined(text_dir, [pr["page_number"] for pr in page_results])

    # Write schema-compliant book_metadata.json
    LOG.info("Building book_metadata.json...")
    book_json = build_book_json(
        pdf_path, doc, page_results, chapters, config, stats, t0, args)
    with open(out / "book_metadata.json", "w", encoding="utf-8") as f:
        json.dump(book_json, f, ensure_ascii=False, indent=2)
    LOG.info(
        "book_metadata.json: %d pages | %d paragraphs | %d sentences | "
        "%d media items",
        len(book_json["pages"]),
        len(book_json["source_spans"]["paragraphs"]),
        len(book_json["source_spans"]["sentences"]),
        len(book_json["media"]["images"]),
    )

    doc.close()
    LOG.info(
        "Done. processed=%d (native=%d) skipped=%d failed=%d "
        "page_images_kept=%d | %s",
        stats.processed, stats.native_text_pages,
        stats.skipped, stats.failed, stats.page_images_kept, out)
    if stats.failed:
        LOG.warning("%d page(s) failed — check ocr_book.log", stats.failed)


def assemble_combined(text_dir: Path, page_numbers: list[int]) -> None:
    md_out = text_dir / "full_document.md"
    txt_out = text_dir / "full_document.txt"
    with open(md_out, "w", encoding="utf-8") as mf, \
         open(txt_out, "w", encoding="utf-8") as tf:
        for pn in sorted(set(page_numbers)):
            md_p = text_dir / f"page_{pn:04d}.md"
            txt_p = text_dir / f"page_{pn:04d}.txt"
            mf.write(f"\n\n<!-- ===== Page {pn} ===== -->\n\n")
            if md_p.exists():
                mf.write(md_p.read_text(encoding="utf-8"))
            tf.write(f"\n\n{'='*72}\nPAGE {pn}\n{'='*72}\n\n")
            if txt_p.exists():
                tf.write(txt_p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _make_book_id(title: str, author: str) -> str:
    """Derive a short slug: last word of author + first word of title."""
    surname = re.sub(r"[^a-z0-9]", "",
                     (author.split()[-1] if author else "unknown").lower())
    word = re.sub(r"[^a-z0-9]", "",
                  (title.split()[0] if title else "book").lower())
    return f"{surname}-{word}"


def _propagate_chapter_context(page_results: list[dict]) -> dict[int, dict]:
    """
    Walk pages in order and carry the current chapter/part forward
    so every page knows which chapter it belongs to.
    """
    starts: list[tuple[int, dict]] = []
    for pr in page_results:
        cs = pr.get("chapter_start")
        if cs:
            starts.append((pr["page_number"], cs))
    starts.sort(key=lambda x: x[0])

    ctx: dict[int, dict] = {}
    cur_chapter = cur_part = ""
    cur_path: list[str] = []
    ptr = 0

    for pn in sorted(pr["page_number"] for pr in page_results):
        while ptr < len(starts) and starts[ptr][0] <= pn:
            cs = starts[ptr][1]
            text = cs.get("matched_text", "")
            title = cs.get("title") or text
            if text.upper().startswith("PART"):
                cur_part = title
                cur_chapter = ""
                cur_path = [cur_part]
            else:
                cur_chapter = title
                cur_path = ([cur_part, cur_chapter] if cur_part
                             else [cur_chapter])
            ptr += 1
        ctx[pn] = {"chapter_title": cur_chapter,
                   "part_title": cur_part,
                   "section_path": list(cur_path)}
    return ctx


def _split_paragraphs(text: str, book_id: str,
                       page_number: int, chapter_title: str) -> list[dict]:
    """Split page text into paragraph spans with character offsets."""
    paras = []
    blocks = re.split(r"\n{2,}", text.strip())
    search_from = 0
    for idx, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        start = text.find(block, search_from)
        if start == -1:
            continue
        end = start + len(block)
        paras.append({
            "span_id": f"{book_id}-p{page_number}-para-{idx+1:03d}",
            "span_type": "paragraph",
            "page_number": page_number,
            "chapter_title": chapter_title,
            "page_char_start": start,
            "page_char_end": end,
            "text": block,
        })
        search_from = end
    return paras


def _split_sentences(para: dict, book_id: str) -> list[dict]:
    """Split a paragraph into sentence spans."""
    text = para["text"]
    base = para["page_char_start"]
    para_id = para["span_id"]
    pn = para["page_number"]
    ch = para["chapter_title"]

    # Split on sentence-ending punctuation followed by whitespace + capital.
    splitter = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\u2018\u201C])")
    raw_sents = splitter.split(text)

    sents = []
    offset = 0
    for idx, raw in enumerate(raw_sents):
        raw = raw.strip()
        if not raw:
            continue
        rel = text.find(raw, offset)
        if rel == -1:
            continue
        sents.append({
            "span_id": f"{para_id}-s{idx+1:03d}",
            "parent_span_id": para_id,
            "span_type": "sentence",
            "page_number": pn,
            "chapter_title": ch,
            "page_char_start": base + rel,
            "page_char_end": base + rel + len(raw),
            "text": raw,
        })
        offset = rel + len(raw)
    return sents


def _quality_flags(pr: dict) -> list[str]:
    flags = []
    conf = pr.get("ocr_confidence")
    if conf is not None and conf < 0.7:
        flags.append(f"low_ocr_confidence:{conf:.2f}")
    if pr.get("was_upscaled"):
        flags.append("upscaled_scan")
    if pr.get("extraction_method") == "skipped":
        flags.append("resumed_from_cache")
    if pr.get("word_count", 0) < 10:
        flags.append("sparse_text")
    for w in pr.get("warnings", []):
        flags.append(f"warn:{w[:80]}")
    return flags


# ---------------------------------------------------------------------------
# Main schema builder  →  book_metadata.json
# ---------------------------------------------------------------------------

def build_book_json(
    pdf_path: Path,
    doc,
    page_results: list[dict],
    chapters: list[dict],
    config: dict,
    stats: RunStats,
    t0: float,
    args: argparse.Namespace,
) -> dict:
    pdf_meta = dict(doc.metadata or {})

    # Book identity
    title = (getattr(args, "book_title", None) or
             config.get("book_title") or
             pdf_meta.get("title") or pdf_path.stem)
    author = (getattr(args, "book_author", None) or
              config.get("book_author") or
              pdf_meta.get("author") or "")
    book_id = (getattr(args, "book_id", None) or
               config.get("book_id") or
               _make_book_id(title, author))
    pub_year = getattr(args, "publication_year", None)
    language = (getattr(args, "book_language", None) or
                config.get("book_language") or "English")

    # -----------------------------------------------------------------------
    # extraction
    # -----------------------------------------------------------------------
    ocr_pages = sorted(
        pr["page_number"] for pr in page_results
        if pr.get("extraction_method") not in ("native_pdf_text", "skipped"))
    native_count = sum(1 for pr in page_results
                       if pr.get("extraction_method") == "native_pdf_text")
    empty_pages = [pr["page_number"] for pr in page_results
                   if pr.get("word_count", 0) < 5]
    by_method: dict[str, int] = {}
    for pr in page_results:
        m = pr.get("extraction_method", "unknown")
        by_method[m] = by_method.get(m, 0) + 1

    extraction = {
        "text_extraction_engine": "PyMuPDF",
        "ocr_engine": "PaddleOCR PP-StructureV3",
        "ocr_mode": getattr(args, "native_text_mode", "auto"),
        "ocr_language": getattr(args, "lang", "en"),
        "ocr_pages": ocr_pages,
        "native_pages": native_count,
        "empty_pages": empty_pages,
        "pages_by_method": by_method,
    }

    # -----------------------------------------------------------------------
    # structure
    # -----------------------------------------------------------------------
    toc_entries = []
    try:
        for level, toc_title, pnum, *_ in doc.get_toc(simple=False):
            toc_entries.append({"level": level, "title": toc_title,
                                 "page": pnum})
    except Exception:
        pass

    schema_chapters = []
    for i, ch in enumerate(chapters):
        nxt = chapters[i + 1] if i + 1 < len(chapters) else None
        schema_chapters.append({
            "chapter_title": ch.get("title") or ch.get("matched_text", ""),
            "part_title": "",
            "page_start": ch.get("page"),
            "page_end": (nxt.get("page", doc.page_count) - 1
                         if nxt else doc.page_count),
        })

    structure = {"toc_entries": toc_entries, "chapters": schema_chapters}

    # -----------------------------------------------------------------------
    # pages + source_spans
    # -----------------------------------------------------------------------
    ctx = _propagate_chapter_context(page_results)
    schema_pages = []
    all_paragraphs = []
    all_sentences = []

    for pr in sorted(page_results, key=lambda x: x["page_number"]):
        pn = pr["page_number"]
        pc = ctx.get(pn, {"chapter_title": "", "part_title": "",
                           "section_path": []})
        text = pr.get("_text", "")

        schema_pages.append({
            "page_id": f"{book_id}-p{pn}",
            "page_number": pn,
            "page_label": pr.get("page_label") or "",
            "chapter_title": pc["chapter_title"],
            "part_title": pc["part_title"],
            "section_path": pc["section_path"],
            "extraction_method": pr.get("extraction_method", ""),
            "word_count": pr.get("word_count", 0),
            "char_count": pr.get("char_count", 0),
            "text": text,
            "quality_flags": _quality_flags(pr),
        })

        if text:
            paras = _split_paragraphs(text, book_id, pn, pc["chapter_title"])
            all_paragraphs.extend(paras)
            for para in paras:
                all_sentences.extend(_split_sentences(para, book_id))

    source_spans = {"paragraphs": all_paragraphs, "sentences": all_sentences}

    # -----------------------------------------------------------------------
    # media
    # -----------------------------------------------------------------------
    images = []
    tables = []
    for pr in page_results:
        pn = pr["page_number"]
        pc = ctx.get(pn, {})
        if pr.get("image_file"):
            images.append({
                "image_id": f"{book_id}-p{pn}-page",
                "page_number": pn,
                "chapter_title": pc.get("chapter_title", ""),
                "filename": pr["image_file"],
                "image_type": "page_scan",
                "caption": "",
            })
        for fig in pr.get("figures", []):
            images.append({
                "image_id": f"{book_id}-p{pn}-{fig.get('filename', '')}",
                "page_number": pn,
                "chapter_title": pc.get("chapter_title", ""),
                "filename": fig.get("filename", ""),
                "image_type": "figure_crop",
                "caption": "",
            })

    media = {"images": images, "tables": tables}

    # -----------------------------------------------------------------------
    # Assemble
    # -----------------------------------------------------------------------
    return {
        "schema": "historical-book-dataset-v1",
        "schema_version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "book": {
            "book_id": book_id,
            "title": title,
            "author": author,
            "publication_year": pub_year,
            "language": language,
            "source_file_name": pdf_path.name,
            "source_sha256": sha256_file(pdf_path),
            "page_count": doc.page_count,
            "pdf_metadata": pdf_meta,
        },
        "extraction": extraction,
        "structure": structure,
        "pages": schema_pages,
        "source_spans": source_spans,
        "media": media,
        "verification": {
            "scope_note": (
                "Text grounding verified against source PDF. "
                "Historical accuracy not externally fact-checked."
            )
        },
        "provenance": {
            "pipeline": "ocr_book.py",
            "pipeline_version": SCRIPT_VERSION,
            "started_at": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.time() - t0, 1),
            "ocr_stats": {
                "total_pages": stats.total,
                "processed": stats.processed,
                "native_text_pages": stats.native_text_pages,
                "skipped": stats.skipped,
                "failed": stats.failed,
                "page_images_kept": stats.page_images_kept,
            },
            "failures": stats.failures,
        },
    }


# ===========================================================================
# CLI
# ===========================================================================

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scanned book OCR pipeline with selective image saving.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Probe mode
    p.add_argument(
        "--probe", metavar="PDF", nargs="+",
        help="Scan one or more PDFs and report which pages are photographs "
             "and which to review as possible maps. No OCR is run. "
             "Use the output to decide which --keep-page numbers to pass "
             "on the main OCR run.")

    # Core
    p.add_argument("--pdf", help="PDF to process")
    p.add_argument("--output", default="./ocr_output", help="Output directory")
    p.add_argument("--config", default=None, help="JSON config file")
    p.add_argument("--generate-config", metavar="PATH",
                   help="Write starter config and exit")

    # Book identity  (written into book_metadata.json)
    p.add_argument("--book-id", default=None,
                   help="Short unique slug, e.g. 'niazi-betrayal'. "
                        "Auto-derived from author/title if omitted.")
    p.add_argument("--book-title", default=None,
                   help="Book title (overrides PDF metadata)")
    p.add_argument("--book-author", default=None,
                   help="Author name (overrides PDF metadata)")
    p.add_argument("--publication-year", type=int, default=None,
                   help="Year published")
    p.add_argument("--book-language", default=None,
                   help="Language of the text, e.g. English (default: English)")

    # OCR engine
    p.add_argument("--lang", default="en",
                   help="OCR language (en, ch, ar, ur, fr, de, ...)")
    p.add_argument("--device", default="gpu", help="cpu | gpu | gpu:0")
    p.add_argument("--dpi", type=int, default=300,
                   help="Fallback render DPI (used only when a page has no "
                        "embedded image)")

    # Page range
    p.add_argument("--start-page", type=int, default=None)
    p.add_argument("--end-page", type=int, default=None)
    p.add_argument("--overwrite", action="store_true",
                   help="Reprocess pages that already have output files")

    # Native text
    p.add_argument(
        "--native-text-mode",
        choices=["auto", "force-native", "force-ocr"],
        default="auto",
        help="auto: use embedded text when it has enough words; "
             "force-native: always use it; force-ocr: always OCR")
    p.add_argument("--native-text-min-words", type=int, default=None)

    # Watermarks
    p.add_argument("--auto-detect-watermarks", action="store_true",
                   help="Sample pages to find repeated text and strip it")
    p.add_argument("--watermark", action="append", default=[],
                   help="Watermark string to strip (repeatable)")

    # Image saving
    p.add_argument(
        "--save-page-images",
        choices=["all", "visual", "none"],
        default=None,
        help="Which full-page images to keep on disk. "
             "'visual' keeps only photographs, maps and covers; "
             "figure crops are always kept regardless.")
    p.add_argument(
        "--keep-page", action="append", type=int, default=[],
        metavar="N",
        help="Force-keep the full page image for page N (1-indexed, "
             "repeatable). Get these numbers from --probe first.")
    p.add_argument(
        "--target-ocr-dpi", type=int, default=None,
        help="Upscale each page until it reaches this pixel density "
             "before OCR. Default 300. Useful for low-resolution scans.")

    # PP-Structure feature switches
    p.add_argument("--no-doc-orientation", action="store_true")
    p.add_argument("--no-unwarping", action="store_true")
    p.add_argument("--no-textline-orientation", action="store_true")
    p.add_argument("--no-tables", action="store_true")
    p.add_argument("--formula-recognition", action="store_true", default=False)
    p.add_argument("--seal-recognition", action="store_true", default=False)
    p.add_argument("--chart-recognition", action="store_true", default=False)

    args = p.parse_args(argv)

    if args.generate_config:
        generate_config(args.generate_config)
        sys.exit(0)

    if not args.probe and not args.pdf:
        p.error("Either --probe <pdf> or --pdf <pdf> is required.")

    return args


def main(argv=None):
    args = parse_args(argv)

    if args.probe:
        logging.basicConfig(level=logging.WARNING,
                            format="%(levelname)s: %(message)s")
        if not HAS_NUMPY:
            sys.exit("--probe needs numpy: pip install numpy")
        config = load_config(args.config if hasattr(args, "config") else None)
        for pdf_path in args.probe:
            print_visual_probe(pdf_path, config)
        return

    process_pdf(args)


if __name__ == "__main__":
    main()