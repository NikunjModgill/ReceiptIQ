"""End-to-end extraction: file path -> ExtractedReceipt.

    file (png/jpg/pdf) --preprocess--> page images --RapidOCR--> lines
         --rules parser--> draft --(optional free LLM)--> final
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, settings as default_settings
from ..schemas import ExtractedReceipt
from . import llm as llm_mod
from .ocr import ocr_lines
from .parser import parse_receipt
from .preprocess import load_pages

log = logging.getLogger(__name__)

MIN_LINE_CONFIDENCE = 0.30


class ExtractionError(Exception):
    """Raised when the file yields nothing we can work with."""


def extract_lines(path: Path) -> list[str]:
    """OCR every page and return reconstructed text lines (page order preserved)."""
    lines: list[str] = []
    for page in load_pages(path):
        for line in ocr_lines(page):
            if line.conf >= MIN_LINE_CONFIDENCE:
                lines.append(line.text)
    return lines


def extract_receipt(path: Path, cfg: Settings = default_settings) -> ExtractedReceipt:
    lines = extract_lines(path)
    if not lines:
        raise ExtractionError("No readable text found in the file")

    result = parse_receipt(lines)

    if cfg.llm_enabled:
        refined = llm_mod.refine_with_llm(lines, result, cfg)
        if refined is not None:
            result = refined
    elif cfg.extraction_engine == "llm":
        result.warnings.append("EXTRACTION_ENGINE=llm but OPENROUTER_API_KEY is not set; used rules")

    log.info(
        "extracted %s | merchant=%r date=%s total=%s items=%d engine=%s",
        path.name, result.merchant_name, result.date, result.total_amount, len(result.line_items), result.engine,
    )
    return result
