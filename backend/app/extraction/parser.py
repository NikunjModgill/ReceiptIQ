"""Rule-based receipt parser: OCR lines -> ExtractedReceipt.

This is a pure function over text so it is fast to unit-test and independent of the
OCR backend. It is deliberately conservative: it never raises on odd input, and it
records anything suspicious in `warnings` instead of guessing silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..schemas import ExtractedReceipt, LineItem

# --------------------------------------------------------------------------- regexes

# A money token: optional currency, optional thousands separators, exactly 2 decimals.
# Negative lookahead stops "8.25%" (a tax rate) and "3.25/GAL" digit-runs from matching.
MONEY_RE = re.compile(
    r"(?<![\d.])(?P<cur>[$€£₹])?\s?(?P<neg>-)?\s?(?P<num>(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?![\d%])"
)
# What may legally follow the *line amount* at the end of a line (tax-code letters etc.)
TRAILING_JUNK_RE = re.compile(r"^[\s*]*(?:[A-Z]{1,2})?[\s*]*$")

DECORATION_RE = re.compile(r"^[\s=\-_*#~.·:|]+$")

# Lines that are never merchants / line items.
META_RE = re.compile(
    r"\b(ORDER|TABLE|STATION|TEL|PHONE|FAX|DATE|TIME|RECEIPT|INVOICE|SERVER|CASHIER|"
    r"CLERK|REGISTER|REG|TERMINAL|TRANS(ACTION)?|AUTH|APPROVAL|REF|WWW\.|HTTP|\.COM|THANK|"
    r"WELCOME|VISIT|CUSTOMER|GUEST|CHECK|TICKET|MEMBER|LOYALTY)\b",
    re.I,
)
ADDRESS_RE = re.compile(r"^\d{1,6}\s+\w+.*\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|DR|DRIVE|LN|LANE|WAY|CA|NY|TX)\b", re.I)
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
HEADER_RE = re.compile(r"(ITEMS?\s*PURCHASED|DESCRIPTION|QTY|QUANTITY|PRICE|AMOUNT|ITEM)\s*:?\s*$", re.I)

SUBTOTAL_RE = re.compile(r"\bSUB[\s\-]?TOTAL\b", re.I)
TIP_RE = re.compile(r"\b(TIP|GRATUITY|SERVICE\s*CHARGE|SVC\s*CHG)\b", re.I)
TAX_RE = re.compile(r"\b(TAX(ES)?|VAT|GST|HST|PST|CGST|SGST|IGST)\b", re.I)
TOTAL_STRONG_RE = re.compile(
    r"\b(GRAND\s*TOTAL|TOTAL\s*(DUE|PAID|AMOUNT)|AMOUNT\s*(DUE|PAID)|BALANCE\s*DUE|NET\s*TOTAL)\b", re.I
)
TOTAL_RE = re.compile(r"\bTOTAL\b", re.I)
PAYMENT_RE = re.compile(
    r"\b(CHANGE|CASH\s*TENDERED|TENDERED|TENDER|VISA|MASTERCARD|MASTER\s*CARD|AMEX|AMERICAN\s*EXPRESS|"
    r"DISCOVER|DEBIT|CREDIT|CARD|PAYMENT|PAID\s*BY|AUTH|APPROVED|BALANCE|ROUNDING|CASH)\b",
    re.I,
)
PAYMENT_METHOD_RE = re.compile(
    r"\b(VISA|MASTERCARD|MASTER\s*CARD|AMEX|AMERICAN\s*EXPRESS|DISCOVER|DEBIT|CREDIT|CASH|UPI|"
    r"PAYPAL|APPLE\s*PAY|GOOGLE\s*PAY|GPAY)\b",
    re.I,
)
LAST4_RE = re.compile(r"(?:ENDING\s*(?:IN)?\s*|[xX*#]{2,}\s?)(\d{4})\b", re.I)

# "2x Caesar Salad" (space after x) or, when OCR drops the space, "1xSparklingWater" —
# in the no-space form the name must start with an upper-case letter so "3xl shirt" survives.
QTY_PREFIX_RE = re.compile(r"^(?P<qty>\d+(?:\.\d+)?)\s*[xX×](?:\s+(?P<name>.+)|(?P<name2>[A-Z0-9].+))$")
CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z]{2})(?=[A-Z])")  # "SparklingWater" -> "Sparkling Water"
QTY_SUFFIX_RE = re.compile(r"^(?P<name>.+?)\s+[xX×]\s*(?P<qty>\d+(?:\.\d+)?)$")
QTY_AT_RE = re.compile(r"^(?P<qty>\d+(?:\.\d+)?)\s*(?P<name>.*?@\s*[$€£₹]?\s?\d+(?:\.\d+)?.*)$")
INDEX_PREFIX_RE = re.compile(r"^\d{1,3}[.)]\s+(?=\S)")

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
DATE_PATTERNS = [
    # 2026-02-25 / 2026/02/25
    (re.compile(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b"), "ymd"),
    # 02/18/2026, 02-25-2026, 18/02/26
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})\b"), "mdy_or_dmy"),
    # 20.02.2026
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"), "dmy"),
    # Feb 20, 2026 / February 20 2026
    # "\s*" after the comma: low-res OCR yields "Feb 20,2026"
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s*(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})\b"), "mon_d_y"),
    # 20 Feb 2026 / 20-Feb-2026
    (re.compile(r"\b(\d{1,2})[\s\-]+([A-Za-z]{3,9})\.?[\s\-,]+(\d{4})\b"), "d_mon_y"),
]

# 180-degree-rotated read of a price, e.g. "86'9 $" for "$ 6.98".
UPSIDE_DOWN_MONEY_RE = re.compile(r"(\d{2})['.,](\d)\s*\$")
_ROT180 = str.maketrans({"6": "9", "9": "6", "'": ".", ",": "."})


# ------------------------------------------------------------------- normalisation

def _fix_ocr_token(tok: str) -> str:
    """Repair the two classic OCR confusions, only where the context is unambiguous."""
    core = tok.strip("$€£₹,.()%:")
    if not core:
        return tok
    letters = sum(c.isalpha() for c in core)
    digits = sum(c.isdigit() for c in core)
    # Numeric token with O/o/l/I inside digits: "O4" -> "04", "4O.3O" -> "40.30"
    if digits and all(c.isdigit() or c in "Ool.,I" for c in core) and letters <= digits:
        return tok.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"}))
    # "Gri1led" -> "Grilled": a lone '1' between lower-case letters is an 'l'
    if letters >= 2 and re.search(r"[a-z]1[a-z]", core) and not any(c.isdigit() and c != "1" for c in core):
        return tok.replace(core, re.sub(r"(?<=[a-z])1(?=[a-z])", "l", core))
    # "0rder" -> "Order": leading zero followed by letters
    if re.match(r"^0[a-z]{2}", core):
        return tok.replace(core, "O" + core[1:], 1)
    # Word with a stray zero and no real digits: "STATI0N" -> "STATION", "Espress0" -> "Espresso"
    if letters >= 2 and "0" in core and not any(c.isdigit() and c != "0" for c in core):
        fixed = []
        for i, c in enumerate(core):
            if c == "0":
                fixed.append("o" if (i > 0 and core[i - 1].islower()) else "O")
            else:
                fixed.append(c)
        return tok.replace(core, "".join(fixed))
    return tok


def normalise_line(line: str) -> str:
    line = line.strip()
    m = UPSIDE_DOWN_MONEY_RE.search(line)
    if m and not MONEY_RE.search(line):
        rotated = m.group(0).replace(" ", "")[::-1].translate(_ROT180)  # "86'9$" -> "$6.98"
        line = line[: m.start()] + rotated + line[m.end():]
    line = " ".join(_fix_ocr_token(t) for t in line.split())
    return line


def clean_lines(lines: list[str]) -> list[str]:
    out = []
    for raw in lines:
        line = normalise_line(raw)
        if not line or DECORATION_RE.match(line):
            continue
        out.append(line)
    return out


# ------------------------------------------------------------------- helpers

def parse_amount(text: str) -> float | None:
    m = MONEY_RE.search(text)
    if not m:
        return None
    value = float(m.group("num").replace(",", ""))
    return -value if m.group("neg") else value


def line_amount(line: str) -> float | None:
    """The amount at the END of a line (the price column), or None."""
    matches = list(MONEY_RE.finditer(line))
    if not matches:
        return None
    last = matches[-1]
    if not TRAILING_JUNK_RE.match(line[last.end():]):
        return None
    value = float(last.group("num").replace(",", ""))
    return -value if last.group("neg") else value


def strip_amount(line: str) -> str:
    matches = list(MONEY_RE.finditer(line))
    if not matches:
        return line.strip()
    last = matches[-1]
    return (line[: last.start()]).strip(" $€£₹:-*")


def _valid(y: int, m: int, d: int) -> str | None:
    try:
        if y < 100:
            y += 2000
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_date(text: str) -> str | None:
    for regex, kind in DATE_PATTERNS:
        for m in regex.finditer(text):
            a, b, c = m.groups()
            if kind == "ymd":
                iso = _valid(int(a), int(b), int(c))
            elif kind == "mdy_or_dmy":
                first, second = int(a), int(b)
                iso = _valid(int(c), first, second) if first <= 12 else _valid(int(c), second, first)
            elif kind == "dmy":
                iso = _valid(int(c), int(b), int(a))
            elif kind == "mon_d_y":
                mon = MONTHS.get(a[:3].lower())
                iso = _valid(int(c), mon, int(b)) if mon else None
            else:  # d_mon_y
                mon = MONTHS.get(b[:3].lower())
                iso = _valid(int(c), mon, int(a)) if mon else None
            if iso:
                return iso
    return None


def _is_decorated_words(line: str) -> str:
    return line.strip(" *=-_#~|·").strip()


def _letters(s: str) -> int:
    return sum(c.isalpha() for c in s)


# ------------------------------------------------------------------- parsing

@dataclass
class _Classified:
    idx: int
    text: str
    amount: float | None
    kind: str  # merchant | date | item | subtotal | tax | tip | total | payment | meta | header | other
    tags: set[str] = field(default_factory=set)


def _classify(idx: int, line: str) -> _Classified:
    upper = line.upper()
    amount = line_amount(line)
    name = strip_amount(line)
    kind = "other"
    if SUBTOTAL_RE.search(upper):
        kind = "subtotal"
    elif TIP_RE.search(upper):
        kind = "tip"
    elif TAX_RE.search(upper) and not TOTAL_STRONG_RE.search(upper) and not re.search(r"\bTOTAL\b", upper.replace("TAX", "")):
        kind = "tax"
    elif TOTAL_STRONG_RE.search(upper) or TOTAL_RE.search(upper):
        kind = "total"
    elif PAYMENT_RE.search(upper):
        kind = "payment"
    elif HEADER_RE.search(upper) or upper.endswith(":"):
        kind = "header"
    elif parse_date(line) or re.search(r"\b\d{1,2}:\d{2}\b", line):
        kind = "date"
    elif META_RE.search(upper) or ADDRESS_RE.search(line) or PHONE_RE.search(line):
        kind = "meta"
    elif amount is not None:
        kind = "item"
    tags = set()
    if TOTAL_STRONG_RE.search(upper):
        tags.add("strong_total")
    if kind in {"subtotal", "tax", "tip", "total"} and amount is None:
        kind = "other"  # e.g. "TAX INCLUDED IN FUEL" carries no number
    return _Classified(idx, name if kind == "item" else line, amount, kind, tags)


def _split_quantity(text: str) -> tuple[float | None, str]:
    """Pull a quantity out of an item description ("2x Salad", "Salad x2", "12.4 GAL @ 3.25")."""
    text = INDEX_PREFIX_RE.sub("", text.strip())
    m = QTY_PREFIX_RE.match(text)
    if m:
        return float(m.group("qty")), m.group("name") or m.group("name2")
    m = QTY_SUFFIX_RE.match(text)
    if m:
        return float(m.group("qty")), m.group("name")
    m = QTY_AT_RE.match(text)
    if m:  # keep the "12.4 GALLONS @ $3.25/GAL" wording: it is informative
        return float(m.group("qty")), text
    return None, text


def _parse_item(text: str, amount: float | None, prefix: str | None = None) -> LineItem:
    qty, name = _split_quantity(text)
    name = CAMEL_SPLIT_RE.sub(" ", name)  # repair OCR-dropped spaces
    if prefix:
        name = f"{prefix.strip()} - {name}"
    return LineItem(name=name.strip(" -:*"), quantity=qty, price=amount)


def _pick_merchant(classified: list[_Classified]) -> tuple[str | None, int]:
    for c in classified[:8]:  # merchant is always in the header block
        words = _is_decorated_words(c.text)
        if c.kind in {"date", "meta", "header", "payment"} or c.amount is not None:
            continue
        if _letters(words) < 2 or PHONE_RE.search(words) or ADDRESS_RE.search(words):
            continue
        return words, c.idx
    return None, -1


def parse_receipt(lines: list[str]) -> ExtractedReceipt:
    cleaned = clean_lines(lines)
    raw_text = "\n".join(cleaned)
    warnings: list[str] = []
    if not cleaned:
        return ExtractedReceipt(warnings=["No text found on the receipt"], raw_text=raw_text)

    classified = [_classify(i, ln) for i, ln in enumerate(cleaned)]

    merchant, merchant_idx = _pick_merchant(classified)

    # Date: first parseable date anywhere on the receipt.
    date_iso = next((d for d in (parse_date(c.text) for c in classified) if d), None)

    # Summary section: totals block starts at the first subtotal/tax/tip/total line.
    summary_kinds = {"subtotal", "tax", "tip", "total"}
    summary_start = next((c.idx for c in classified if c.kind in summary_kinds), len(classified))

    subtotal = next((c.amount for c in classified if c.kind == "subtotal"), None)
    tax_lines = [c.amount for c in classified if c.kind == "tax" and c.amount is not None]
    tip_lines = [c.amount for c in classified if c.kind == "tip" and c.amount is not None]
    tax = round(sum(tax_lines), 2) if tax_lines else None
    tip = round(sum(tip_lines), 2) if tip_lines else None

    totals = [c for c in classified if c.kind == "total" and c.amount is not None]
    strong = [c for c in totals if "strong_total" in c.tags]
    if strong:
        total = strong[-1].amount
    elif totals:
        total = totals[-1].amount
    else:
        amounts = [c.amount for c in classified if c.amount is not None]
        total = max(amounts) if amounts else None
        if total is not None:
            warnings.append("No TOTAL keyword found; used the largest amount on the receipt")

    # Line items: amount-bearing lines between the merchant block and the summary block.
    items: list[LineItem] = []
    prev: _Classified | None = None
    for c in classified:
        if c.idx <= merchant_idx or c.idx >= summary_start:
            prev = c
            continue
        if c.kind == "item":
            prefix = None
            # Wrapped description: previous line had no amount and is plain text
            # ("PUMP 04 REGULAR UNLEADED" / "12.4 GALLONS @ $3.25/GAL   40.30").
            if (
                prev is not None
                and prev.kind == "other"
                and prev.amount is None
                and prev.idx > merchant_idx
                and _letters(prev.text) >= 3
            ):
                prefix = prev.text
            items.append(_parse_item(c.text, c.amount, prefix))
        prev = c

    # Currency & payment method.
    currency = None
    if "$" in raw_text:
        currency = "USD"
    elif "₹" in raw_text or re.search(r"\b(RS\.?|INR)\b", raw_text.upper()):
        currency = "INR"
    elif "€" in raw_text:
        currency = "EUR"
    elif "£" in raw_text:
        currency = "GBP"

    payment_method = None
    for c in classified:
        m = PAYMENT_METHOD_RE.search(c.text)
        if m:
            payment_method = m.group(1).upper()
            last4 = LAST4_RE.search(c.text)
            if last4:
                payment_method += f" ****{last4.group(1)}"
            break

    receipt = ExtractedReceipt(
        merchant_name=merchant,
        date=date_iso,
        line_items=items,
        subtotal=subtotal,
        tax=tax,
        tip=tip,
        total_amount=total,
        currency=currency,
        payment_method=payment_method,
        engine="rapidocr+rules",
        warnings=warnings,
        raw_text=raw_text,
    )
    receipt.warnings.extend(consistency_warnings(receipt))
    return receipt


def consistency_warnings(r: ExtractedReceipt) -> list[str]:
    """Sanity checks shared by the rules parser and the LLM refiner. Warnings only."""

    def close(a: float, b: float) -> bool:
        return abs(a - b) <= 0.02

    out: list[str] = []
    if r.merchant_name is None:
        out.append("Merchant name not found")
    if r.date is None:
        out.append("Date not found")
    if r.total_amount is None:
        out.append("Total amount not found")
    tax, tip = r.tax or 0, r.tip or 0
    if r.subtotal is not None and r.total_amount is not None:
        expected = r.subtotal + tax + tip
        if not close(expected, r.total_amount):
            out.append(f"subtotal+tax+tip = {expected:.2f} does not match total {r.total_amount:.2f}")
    item_sum = round(sum(i.price for i in r.line_items if i.price is not None), 2)
    if r.line_items and r.subtotal is not None and not close(item_sum, r.subtotal):
        out.append(f"Line items sum to {item_sum:.2f} but subtotal is {r.subtotal:.2f}")
    elif r.line_items and r.subtotal is None and r.total_amount is not None:
        if not close(item_sum + tax + tip, r.total_amount):
            out.append(f"Line items + tax + tip = {item_sum + tax + tip:.2f} does not match total {r.total_amount:.2f}")
    return out
