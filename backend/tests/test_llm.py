"""The OpenRouter refiner is exercised with a mocked HTTP transport (no key, no network)."""

import json

import httpx

from backend.app.config import Settings
from backend.app.extraction import llm
from backend.app.extraction.parser import parse_receipt
from backend.tests.test_parser import TARGET


def _cfg(**overrides) -> Settings:
    cfg = Settings()
    cfg.openrouter_api_key = "test-key"
    cfg.extraction_engine = "auto"
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_refine_merges_model_output_and_fills_gaps_from_draft():
    draft = parse_receipt(TARGET)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        reply = {"merchant_name": "Target", "date": "2026-02-18", "line_items": [], "total_amount": 50.31}
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(reply) + "\n```"}}]})

    out = llm.refine_with_llm(TARGET, draft, _cfg(), client=_client(handler))
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["model"] == _cfg().openrouter_model
    assert "OCR TEXT" in captured["body"]["messages"][1]["content"]
    assert out is not None
    assert out.merchant_name == "Target"            # model value wins
    assert out.line_items == draft.line_items       # empty list -> keep draft
    assert out.tax == 3.83                          # missing -> keep draft
    assert out.engine.startswith("rapidocr+llm:")
    assert out.warnings == []


def test_refine_falls_back_on_http_error():
    draft = parse_receipt(TARGET)
    out = llm.refine_with_llm(TARGET, draft, _cfg(), client=_client(lambda r: httpx.Response(429, text="rate limited")))
    assert out is None


def test_refine_falls_back_on_garbage():
    draft = parse_receipt(TARGET)
    bad = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "Sorry, I cannot help."}}]})
    assert llm.refine_with_llm(TARGET, draft, _cfg(), client=_client(bad)) is None


def test_refine_disabled_without_key():
    cfg = _cfg(openrouter_api_key=None)
    assert llm.refine_with_llm(TARGET, parse_receipt(TARGET), cfg) is None
    assert cfg.llm_enabled is False
    assert _cfg(extraction_engine="rules").llm_enabled is False
    assert _cfg().llm_enabled is True
