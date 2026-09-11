"""SQLite persistence (stdlib sqlite3, no ORM).

Schema follows the assessment exactly:
id, filename, merchant_name, date, total_amount, extracted_json, created_at
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .schemas import ExtractedReceipt, ReceiptRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    filename       TEXT    NOT NULL,
    merchant_name  TEXT,
    date           TEXT,
    total_amount   REAL,
    extracted_json TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receipts_created_at ON receipts (created_at DESC);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ writes
    def insert_receipt(self, filename: str, extracted: ExtractedReceipt) -> ReceiptRecord:
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO receipts (filename, merchant_name, date, total_amount, extracted_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    filename,
                    extracted.merchant_name,
                    extracted.date,
                    extracted.total_amount,
                    extracted.model_dump_json(),
                    created_at,
                ),
            )
            row_id = cur.lastrowid
        return ReceiptRecord(
            id=row_id,
            filename=filename,
            merchant_name=extracted.merchant_name,
            date=extracted.date,
            total_amount=extracted.total_amount,
            created_at=created_at,
            extracted=extracted,
        )

    def delete_receipt(self, receipt_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------- reads
    @staticmethod
    def _to_record(row: sqlite3.Row) -> ReceiptRecord:
        return ReceiptRecord(
            id=row["id"],
            filename=row["filename"],
            merchant_name=row["merchant_name"],
            date=row["date"],
            total_amount=row["total_amount"],
            created_at=row["created_at"],
            extracted=ExtractedReceipt.model_validate(json.loads(row["extracted_json"])),
        )

    def list_receipts(self, limit: int = 100, offset: int = 0) -> list[ReceiptRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM receipts ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [self._to_record(r) for r in rows]

    def get_receipt(self, receipt_id: int) -> ReceiptRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        return self._to_record(row) if row else None

    def count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
