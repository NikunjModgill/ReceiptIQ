"""Pydantic models shared by the extraction engine, the API and the tests."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class LineItem(BaseModel):
    name: str
    quantity: float | None = None
    price: float | None = Field(default=None, description="Line total for this item")

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())


class ExtractedReceipt(BaseModel):
    """The structured payload stored in receipts.extracted_json."""

    merchant_name: str | None = None
    date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when parsed")
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total_amount: float | None = None
    currency: str | None = None
    payment_method: str | None = None
    engine: str = "rapidocr+rules"
    warnings: list[str] = Field(default_factory=list)
    raw_text: str = ""


class ReceiptRecord(BaseModel):
    """One row of the receipts table, as returned by the API."""

    id: int
    filename: str
    merchant_name: str | None
    date: str | None
    total_amount: float | None
    created_at: str
    extracted: ExtractedReceipt


class ReceiptListResponse(BaseModel):
    count: int
    receipts: list[ReceiptRecord]


class ErrorResponse(BaseModel):
    detail: Any
