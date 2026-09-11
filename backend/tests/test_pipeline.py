"""End-to-end OCR + parsing on the three receipts shipped with the assessment."""

import pytest

from backend.app.extraction.pipeline import extract_receipt

GROUND_TRUTH = {
    "corner_bistro.png": dict(merchant="THE CORNER BISTRO", date="2026-02-20", subtotal=77.50, tax=6.98, tip=15.00, total=99.48, n_items=4),
    "target.png": dict(merchant="TARGET STORES", date="2026-02-18", subtotal=46.48, tax=3.83, tip=None, total=50.31, n_items=3),
    "quickmart_fuel.png": dict(merchant="QUICK-MART FUEL & MORE", date="2026-02-25", subtotal=None, tax=0.28, tip=None, total=44.07, n_items=2),
    # 535x440 screenshot of the bistro receipt: exercises the small-image upscaling path
    "corner_bistro_lowres.png": dict(merchant="THE CORNER BISTRO", date="2026-02-20", subtotal=77.50, tax=6.98, tip=15.00, total=99.48, n_items=4),
}


@pytest.mark.parametrize("name", list(GROUND_TRUTH))
def test_sample_receipts(fixtures_dir, name):
    truth = GROUND_TRUTH[name]
    r = extract_receipt(fixtures_dir / name)
    assert r.engine == "rapidocr+rules"
    assert r.merchant_name == truth["merchant"]
    assert r.date == truth["date"]
    assert r.subtotal == truth["subtotal"]
    assert r.tax == truth["tax"]
    assert r.tip == truth["tip"]
    assert r.total_amount == truth["total"]
    assert len(r.line_items) == truth["n_items"]
    assert all(i.price is not None for i in r.line_items)
    assert r.warnings == [], r.warnings


def test_pdf_input(sample_pdf):
    r = extract_receipt(sample_pdf)
    assert r.merchant_name == "TARGET STORES"
    assert r.total_amount == 50.31
    assert len(r.line_items) == 3
