"""Optional refinement step using a *free-tier* OpenRouter model.

The local OCR + rules pipeline always runs first. When OPENROUTER_API_KEY is set we
hand the OCR lines and the rules result to a free text model (e.g.
`meta-llama/llama-3.3-70b-instruct:free`) and ask for a corrected JSON document.
Any failure (no key, HTTP error, timeout, malformed JSON, schema violation) makes
this function return None and the caller keeps the rules result. No paid APIs.
"""

from __future__ import annotations

import json
import logging
import re

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings, settings as default_settings
from ..schemas import ExtractedReceipt, LineItem
from .parser import consistency_warnings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a meticulous receipt-data extraction engine.
You receive the OCR text of ONE receipt (one physical line per input line) and a
draft extraction produced by a rule-based parser. Return the corrected extraction
as a single JSON object and nothing else. Rules:
- Use only information visible in the OCR text. Never invent items or amounts.
- Fix obvious OCR mistakes (0/O, 1/l, misplaced decimal points) when the arithmetic
  proves the correction (subtotal + tax + tip = total; items sum to subtotal).
- "date" must be ISO YYYY-MM-DD or null. Money fields are plain numbers or null.
- "line_items" excludes subtotal/tax/tip/total/payment lines.
- Keep the draft's values when you have no evidence they are wrong.
Schema:
{"merchant_name": str|null, "date": str|null,
 "line_items": [{"name": str, "quantity": number|null, "price": number|null}],
 "subtotal": number|null, "tax": number|null, "tip": number|null,
 "total_amount": number|null, "currency": str|null, "payment_method": str|null}"""


class _LLMReceipt(BaseModel):
    merchant_name: str | None = None
    date: str | None = None
    line_items: list[LineItem] = []
    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total_amount: float | None = None
    currency: str | None = None
    payment_method: str | None = None


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def build_messages(lines: list[str], draft: ExtractedReceipt) -> list[dict]:
    draft_json = draft.model_dump(exclude={"raw_text", "engine", "warnings"})
    user = (
        "OCR TEXT:\n" + "\n".join(lines) + "\n\nDRAFT EXTRACTION:\n" + json.dumps(draft_json, indent=1)
        + "\n\nReturn the corrected JSON object only."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def refine_with_llm(
    lines: list[str],
    draft: ExtractedReceipt,
    cfg: Settings = default_settings,
    client: httpx.Client | None = None,
) -> ExtractedReceipt | None:
    """Return an LLM-corrected receipt, or None if refinement is unavailable/failed."""
    if not cfg.openrouter_api_key:
        return None

    payload = {
        "model": cfg.openrouter_model,
        "messages": build_messages(lines, draft),
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {cfg.openrouter_api_key}",
        "HTTP-Referer": "https://github.com/receiptiq",  # OpenRouter attribution headers (optional)
        "X-Title": "ReceiptIQ",
    }
    own_client = client is None
    client = client or httpx.Client(timeout=cfg.openrouter_timeout_s)
    try:
        resp = client.post(f"{cfg.openrouter_base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _LLMReceipt.model_validate(_extract_json(content))
    except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
        log.warning("LLM refinement skipped (%s: %s); keeping rule-based result", type(exc).__name__, exc)
        return None
    finally:
        if own_client:
            client.close()

    merged = ExtractedReceipt(
        merchant_name=data.merchant_name or draft.merchant_name,
        date=data.date if data.date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.date) else draft.date,
        line_items=data.line_items or draft.line_items,
        subtotal=data.subtotal if data.subtotal is not None else draft.subtotal,
        tax=data.tax if data.tax is not None else draft.tax,
        tip=data.tip if data.tip is not None else draft.tip,
        total_amount=data.total_amount if data.total_amount is not None else draft.total_amount,
        currency=data.currency or draft.currency,
        payment_method=data.payment_method or draft.payment_method,
        engine=f"rapidocr+llm:{cfg.openrouter_model}",
        raw_text=draft.raw_text,
    )
    merged.warnings = consistency_warnings(merged)
    return merged
