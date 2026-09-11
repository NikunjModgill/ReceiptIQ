"""ReceiptIQ REST API.

    POST /upload          -> run extraction on an uploaded receipt, persist, return JSON
    GET  /receipts        -> list stored receipts (newest first)
    GET  /receipts/{id}   -> one receipt
    DELETE /receipts/{id} -> remove one receipt
    GET  /health          -> liveness + engine info
    GET  /                -> the frontend (static HTML/JS)
"""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Database
from .extraction import ocr
from .extraction.pipeline import ExtractionError, extract_receipt
from .extraction.preprocess import SUPPORTED_EXTENSIONS, sniff_kind
from .schemas import ErrorResponse, ReceiptListResponse, ReceiptRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("receiptiq")

_KIND_FOR_EXT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".pdf": "pdf"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    app.state.db = Database(settings.db_path)
    # Load the OCR models once at startup instead of on the first upload.
    await run_in_threadpool(ocr.get_engine)
    log.info("ReceiptIQ ready | db=%s | engine=%s | llm=%s", settings.db_path, settings.extraction_engine, settings.llm_enabled)
    yield


app = FastAPI(
    title="ReceiptIQ",
    description="End-to-end receipt extraction: upload -> free local OCR/LLM pipeline -> SQLite -> table.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def _db() -> Database:
    return app.state.db


def _safe_name(name: str) -> str:
    name = Path(name or "receipt").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


# ------------------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {
        "status": "ok",
        "extraction_engine": settings.extraction_engine,
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.openrouter_model if settings.llm_enabled else None,
        "receipts": _db().count(),
    }


@app.post(
    "/upload",
    response_model=ReceiptRecord,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def upload(file: UploadFile = File(...)):
    """Accept a receipt (png/jpg/jpeg/pdf), extract, persist, and return the record."""
    original = _safe_name(file.filename or "")
    ext = Path(original).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext or 'none'}'. Allowed: png, jpg, jpeg, pdf")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"File too large (max {settings.max_upload_bytes // (1024 * 1024)} MB)")
    kind = sniff_kind(content[:16])
    if kind != _KIND_FOR_EXT[ext]:
        raise HTTPException(400, f"File content does not look like a {ext[1:]} file")

    stored = settings.upload_dir / f"{uuid.uuid4().hex}_{original}"
    stored.write_bytes(content)

    try:
        extracted = await run_in_threadpool(extract_receipt, stored)
    except ExtractionError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:  # noqa: BLE001 - surface as a clean API error
        log.exception("extraction failed for %s", original)
        raise HTTPException(500, f"Extraction failed: {type(exc).__name__}: {exc}")

    return _db().insert_receipt(original, extracted)


@app.get("/receipts", response_model=ReceiptListResponse)
def list_receipts(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    receipts = _db().list_receipts(limit=limit, offset=offset)
    return ReceiptListResponse(count=_db().count(), receipts=receipts)


@app.get("/receipts/{receipt_id}", response_model=ReceiptRecord, responses={404: {"model": ErrorResponse}})
def get_receipt(receipt_id: int):
    rec = _db().get_receipt(receipt_id)
    if rec is None:
        raise HTTPException(404, "Receipt not found")
    return rec


@app.delete("/receipts/{receipt_id}", status_code=204, responses={404: {"model": ErrorResponse}})
def delete_receipt(receipt_id: int):
    if not _db().delete_receipt(receipt_id):
        raise HTTPException(404, "Receipt not found")


# ------------------------------------------------------------------- frontend

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(settings.frontend_dir / "index.html")


app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")
