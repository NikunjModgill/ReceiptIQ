"""Local OCR via RapidOCR (PaddleOCR models on ONNX Runtime, CPU only, no API keys).

RapidOCR returns *word/phrase boxes*, not lines. Receipts are two-column documents
("item ........ price"), so the important work here is rebuilding physical lines by
clustering boxes on their vertical centre and sorting left-to-right.
"""

from __future__ import annotations

import re
import statistics
import threading
from dataclasses import dataclass

import numpy as np

_engine = None
_engine_lock = threading.Lock()


def get_engine():
    """Lazily build the RapidOCR engine once (model load takes ~1s)."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR()
    return _engine


@dataclass
class OcrBox:
    text: str
    conf: float
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class OcrLine:
    text: str
    conf: float  # mean confidence of the boxes that formed the line
    boxes: list[OcrBox]


_ONLY_CURRENCY = re.compile(r"^[\s$€£₹]+$")


def run_ocr(image: np.ndarray) -> list[OcrBox]:
    """Run detection + recognition on one RGB image and return raw boxes."""
    engine = get_engine()
    bgr = image[:, :, ::-1]  # RapidOCR/OpenCV expect BGR
    result, _elapse = engine(bgr)
    boxes: list[OcrBox] = []
    for quad, text, conf in result or []:
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        text = str(text).strip()
        if not text:
            continue
        boxes.append(OcrBox(text, float(conf), min(xs), max(xs), min(ys), max(ys)))
    return boxes


def group_lines(boxes: list[OcrBox]) -> list[OcrLine]:
    """Cluster boxes into physical lines.

    Greedy pass over boxes sorted by vertical centre: a box joins the current line
    when its centre is within ~half a text height of the line's running mean centre,
    otherwise it starts a new line. Boxes inside a line are then sorted by x.
    """
    # Stray "$" glyphs are often detected as their own tall box spanning several
    # rows (the price column). They carry no information, so drop them first.
    boxes = [b for b in boxes if not _ONLY_CURRENCY.match(b.text)]
    if not boxes:
        return []

    median_h = statistics.median(b.height for b in boxes)
    threshold = 0.55 * median_h

    lines: list[list[OcrBox]] = []
    centres: list[float] = []
    for box in sorted(boxes, key=lambda b: b.yc):
        if lines and abs(box.yc - centres[-1]) <= threshold:
            lines[-1].append(box)
            centres[-1] = sum(b.yc for b in lines[-1]) / len(lines[-1])
        else:
            lines.append([box])
            centres.append(box.yc)

    out: list[OcrLine] = []
    for group in lines:
        group.sort(key=lambda b: b.x0)
        text = " ".join(b.text for b in group)
        text = re.sub(r"\s+", " ", text).strip()
        conf = sum(b.conf for b in group) / len(group)
        out.append(OcrLine(text=text, conf=conf, boxes=group))
    return out


def ocr_lines(image: np.ndarray) -> list[OcrLine]:
    return group_lines(run_ocr(image))
