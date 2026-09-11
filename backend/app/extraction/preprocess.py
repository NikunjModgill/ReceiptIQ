"""Turn an uploaded file (image or PDF) into a list of RGB numpy page images.

Everything here is free and local: Pillow for images, PyMuPDF for PDF rasterisation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS

# Longest side we feed the OCR model. Receipts photographed on phones are 3-4k px;
# PaddleOCR's detector works best around 1-2k and it keeps CPU inference fast.
MAX_SIDE = 2000
# Small images (screenshots, thumbnails) make the recogniser drop spaces between words
# ("1xSparklingWater", "Date:Feb 20,2026"). Upscaling to ~1600 px fixes that reliably.
MIN_SIDE = 1600
PDF_DPI = 200
MAX_PDF_PAGES = 5


def _to_rgb_array(img: Image.Image) -> np.ndarray:
    img = ImageOps.exif_transpose(img)  # honour phone camera orientation tags
    img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    scale = 1.0
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
    elif longest < MIN_SIDE:
        scale = MIN_SIDE / longest
    if scale != 1.0:
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    return np.asarray(img)


def load_image(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return _to_rgb_array(img)


def load_pdf(path: Path) -> list[np.ndarray]:
    import pymupdf  # imported lazily: only needed for PDFs

    pages: list[np.ndarray] = []
    with pymupdf.open(path) as doc:
        for page in list(doc)[:MAX_PDF_PAGES]:
            pix = page.get_pixmap(dpi=PDF_DPI, colorspace=pymupdf.csRGB, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(_to_rgb_array(img))
    return pages


def load_pages(path: Path) -> list[np.ndarray]:
    """Return one RGB array per page. Images are a single page."""
    ext = path.suffix.lower()
    if ext in PDF_EXTENSIONS:
        return load_pdf(path)
    if ext in IMAGE_EXTENSIONS:
        return [load_image(path)]
    raise ValueError(f"Unsupported file type: {ext}")


def sniff_kind(header: bytes) -> str | None:
    """Detect the real file type from magic bytes ('png' | 'jpeg' | 'pdf' | None)."""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.lstrip().startswith(b"%PDF"):
        return "pdf"
    return None
