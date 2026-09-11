"""Pure-text tests for the rule-based parser (no OCR, run in milliseconds)."""

from backend.app.extraction.parser import (
    line_amount,
    normalise_line,
    parse_date,
    parse_receipt,
)

# Lines exactly as RapidOCR reconstructs them for the three sample receipts.
CORNER_BISTRO = [
    "================================",
    "THE CORNER BISTRO",
    "Order #849 - Table 12",
    "================================",
    "Date: Feb 20, 2026 Time: 19:45",
    "1x Sparkling Water $ 4.00",
    "2x Caesar Salad 22.00",
    "2x Grilled Salmon 48.00",
    "1x Espress0 $ 3.50",
    "--------------------------------",
    "SUBTOTAL $ 77.50",
    "TAX 86'9 $",  # upside-down OCR read of "$ 6.98"
    "GRATUITY / TIP $ 15.00",
    "TOTAL DUE $ 99.48",
    "Server: Sarah M.",
]

TARGET = [
    "TARGET STORES",
    "1234 Main Street, CA",
    "Tel: (555) 019-2831",
    "Date: 02/18/2026",
    "Time: 14:22",
    "ITEMS PURCHASED:",
    "1. Wireless Mouse 24.99",
    "2. USB-C Cable 6ft 12.50",
    "3. Notebook 3-Pack 8.99",
    "SUBTOTAL 46.48",
    "TAX (8.25%) 3.83",
    "TOTAL $ 50.31",
    "Payment Method: Visa ending in 4012",
    "Thank you for shopping at Target!",
]

QUICKMART = [
    "*** QUICK-MART FUEL & MORE ***",
    "STATI0N #0491 - GURUGRAM",
    "02-25-2026 08:12 AM",
    "PUMP O4 REGULAR UNLEADED",
    "12.4 GALL0NS @ $3.25/GAL 40.30",
    "MONSTER ENERGY DRINK 160Z 3.49",
    "TAX INCLUDED O IN FUEL",
    "NON-FUEL TAX 0.28",
    "TOTAL PAID 44.07",
    "AUTH C0DE: 994182 CASH",
    "AUTH # 029101",
]


def test_corner_bistro():
    r = parse_receipt(CORNER_BISTRO)
    assert r.merchant_name == "THE CORNER BISTRO"
    assert r.date == "2026-02-20"
    assert r.subtotal == 77.50
    assert r.tax == 6.98
    assert r.tip == 15.00
    assert r.total_amount == 99.48
    assert [i.name for i in r.line_items] == ["Sparkling Water", "Caesar Salad", "Grilled Salmon", "Espresso"]
    assert [i.quantity for i in r.line_items] == [1, 2, 2, 1]
    assert [i.price for i in r.line_items] == [4.00, 22.00, 48.00, 3.50]
    assert r.currency == "USD"
    assert r.warnings == []


def test_target():
    r = parse_receipt(TARGET)
    assert r.merchant_name == "TARGET STORES"
    assert r.date == "2026-02-18"
    assert r.subtotal == 46.48
    assert r.tax == 3.83
    assert r.tip is None
    assert r.total_amount == 50.31
    assert [i.name for i in r.line_items] == ["Wireless Mouse", "USB-C Cable 6ft", "Notebook 3-Pack"]
    assert [i.price for i in r.line_items] == [24.99, 12.50, 8.99]
    assert r.payment_method == "VISA ****4012"
    assert r.warnings == []


def test_quickmart_fuel():
    r = parse_receipt(QUICKMART)
    assert r.merchant_name == "QUICK-MART FUEL & MORE"
    assert r.date == "2026-02-25"
    assert r.subtotal is None
    assert r.tax == 0.28
    assert r.tip is None
    assert r.total_amount == 44.07
    assert len(r.line_items) == 2
    assert r.line_items[0].name == "PUMP 04 REGULAR UNLEADED - 12.4 GALLONS @ $3.25/GAL"
    assert r.line_items[0].quantity == 12.4
    assert r.line_items[0].price == 40.30
    assert r.line_items[1].name == "MONSTER ENERGY DRINK 160Z"
    assert r.line_items[1].price == 3.49
    assert r.payment_method == "CASH"
    assert r.warnings == []


def test_no_total_keyword_falls_back_to_largest_amount():
    r = parse_receipt(["CAFE ROMA", "Coffee 3.00", "Bagel 2.50", "Amount 5.50"])
    assert r.total_amount == 5.50
    assert any("largest amount" in w for w in r.warnings)


def test_multiple_tax_lines_are_summed_and_thousands_separators_work():
    r = parse_receipt([
        "MEGA ELECTRONICS",
        "12/31/2025",
        "Laptop 1,299.00",
        "Subtotal 1,299.00",
        "CGST 9% 116.91",
        "SGST 9% 116.91",
        "Grand Total 1,532.82",
    ])
    assert r.total_amount == 1532.82
    assert r.tax == 233.82
    assert r.line_items[0].price == 1299.00
    assert r.warnings == []


def test_mismatch_produces_warning_not_error():
    r = parse_receipt(["SHOP", "01/02/2026", "Thing 10.00", "SUBTOTAL 10.00", "TAX 1.00", "TOTAL 12.00"])
    assert r.total_amount == 12.00
    assert any("does not match total" in w for w in r.warnings)


def test_empty_input():
    r = parse_receipt(["", "=====", "   "])
    assert r.total_amount is None
    assert "No text found on the receipt" in r.warnings


def test_dates():
    assert parse_date("Date: Feb 20, 2026") == "2026-02-20"
    assert parse_date("02/18/2026") == "2026-02-18"
    assert parse_date("02-25-2026 08:12 AM") == "2026-02-25"
    assert parse_date("2026-03-01") == "2026-03-01"
    assert parse_date("25/12/2025") == "2025-12-25"  # day-first when first field > 12
    assert parse_date("20.02.2026") == "2026-02-20"
    assert parse_date("3 March 2026") == "2026-03-03"
    assert parse_date("no date here 12:30") is None
    assert parse_date("13/13/2026") is None


def test_line_amount_rules():
    assert line_amount("12.4 GALLONS @ $3.25/GAL 40.30") == 40.30
    assert line_amount("TAX (8.25%) 3.83") == 3.83
    assert line_amount("TAX (8.25%)") is None
    assert line_amount("Tel: (555) 019-2831") is None
    assert line_amount("Refund -5.00") == -5.00
    assert line_amount("Widget 4.00 T") == 4.00


def test_ocr_fixes():
    assert normalise_line("TAX 86'9 $") == "TAX $6.98"
    assert normalise_line("STATI0N #0491") == "STATION #0491"
    assert normalise_line("PUMP O4") == "PUMP 04"
    assert normalise_line("1x Espress0") == "1x Espresso"
    assert normalise_line("MONSTER 160Z") == "MONSTER 160Z"  # ambiguous: left alone


# Lines as RapidOCR produces them from a small (535x440) screenshot: spaces are dropped.
CORNER_BISTRO_LOWRES = [
    "THE CORNER BISTRO",
    "0rder#849-Table 12",
    "Date:Feb 20,2026 Time:19:45",
    "1xSparklingWater $ 4.00",
    "2x Caesar Salad $22.00",
    "2x Gri1led Salmon $ 48.00",
    "1xEspresso $ 3.50",
    "SUBTOTAL $ 77.50",
    "TAX $ 6.98",
    "GRATUITY/ TIP $15.00",
    "TOTAL DUE $99.48",
    "Server: Sarah M.",
]


def test_low_resolution_ocr_without_spaces():
    r = parse_receipt(CORNER_BISTRO_LOWRES)
    assert r.merchant_name == "THE CORNER BISTRO"
    assert r.date == "2026-02-20"
    assert [i.name for i in r.line_items] == ["Sparkling Water", "Caesar Salad", "Grilled Salmon", "Espresso"]
    assert [i.quantity for i in r.line_items] == [1, 2, 2, 1]
    assert r.total_amount == 99.48 and r.tip == 15.00 and r.tax == 6.98
    assert r.warnings == []
    assert normalise_line("0rder#849-Table 12") == "Order#849-Table 12"
