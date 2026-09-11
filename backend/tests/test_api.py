"""HTTP-level tests of the FastAPI app (uses a temp SQLite DB, see conftest)."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # context manager triggers the lifespan (DB + OCR init)
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_then_list_then_get_then_delete(client, fixtures_dir):
    with open(fixtures_dir / "corner_bistro.png", "rb") as f:
        r = client.post("/upload", files={"file": ("corner_bistro.png", f, "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "corner_bistro.png"
    assert body["merchant_name"] == "THE CORNER BISTRO"
    assert body["date"] == "2026-02-20"
    assert body["total_amount"] == 99.48
    assert body["extracted"]["tax"] == 6.98
    assert body["extracted"]["tip"] == 15.00
    assert len(body["extracted"]["line_items"]) == 4
    rid = body["id"]

    r = client.get("/receipts")
    assert r.status_code == 200
    listing = r.json()
    assert listing["count"] >= 1
    assert listing["receipts"][0]["id"] == rid  # newest first
    assert set(listing["receipts"][0]) >= {"id", "filename", "merchant_name", "date", "total_amount", "created_at", "extracted"}

    assert client.get(f"/receipts/{rid}").json()["merchant_name"] == "THE CORNER BISTRO"

    assert client.delete(f"/receipts/{rid}").status_code == 204
    assert client.get(f"/receipts/{rid}").status_code == 404
    assert client.delete(f"/receipts/{rid}").status_code == 404


def test_upload_pdf(client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        r = client.post("/upload", files={"file": ("target.pdf", f, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["merchant_name"] == "TARGET STORES"
    assert r.json()["total_amount"] == 50.31


def test_rejects_unsupported_extension(client):
    r = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert "Unsupported file type" in r.json()["detail"]


def test_rejects_mismatched_content(client):
    r = client.post("/upload", files={"file": ("fake.png", b"this is not a png", "image/png")})
    assert r.status_code == 400
    assert "does not look like" in r.json()["detail"]


def test_rejects_empty_file(client):
    r = client.post("/upload", files={"file": ("empty.png", b"", "image/png")})
    assert r.status_code == 400
