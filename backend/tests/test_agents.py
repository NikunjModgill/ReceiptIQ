"""Part 2 workflow test: runs Fetcher -> Analyst -> Composer -> Dispatcher (dry run) on a temp DB."""

import email
from pathlib import Path

from openpyxl import Workbook

from agents.expense_dispatcher import (
    AnalystAgent,
    ComposerAgent,
    DispatcherAgent,
    FetcherAgent,
    Orchestrator,
    WorkflowState,
    categorise,
)
from backend.app.database import Database
from backend.app.extraction.parser import parse_receipt
from backend.tests.test_parser import CORNER_BISTRO, QUICKMART, TARGET


def _seed_db(path: Path) -> Database:
    db = Database(path)
    db.insert_receipt("corner_bistro.png", parse_receipt(CORNER_BISTRO))
    db.insert_receipt("target.png", parse_receipt(TARGET))
    db.insert_receipt("quickmart_fuel.png", parse_receipt(QUICKMART))
    db.insert_receipt("corner_bistro_again.png", parse_receipt(CORNER_BISTRO))  # duplicate
    return db


def _recipients(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Email", "Department"])
    ws.append(["Finance", "finance@example.com", "finance"])
    ws.append(["Bad Row", "not-an-email", ""])
    wb.save(path)
    return path


def test_categorise():
    assert categorise({"merchant_name": "THE CORNER BISTRO", "extracted": {}}) == "dining"
    assert categorise({"merchant_name": "QUICK-MART FUEL & MORE", "extracted": {}}) == "fuel"
    assert categorise({"merchant_name": "TARGET STORES", "extracted": {}}) == "retail"
    assert categorise({"merchant_name": "ZZZ", "extracted": {}}) == "other"


def test_dry_run_workflow(tmp_path):
    _seed_db(tmp_path / "r.db")
    outbox = tmp_path / "outbox"
    state = Orchestrator([
        FetcherAgent(db_path=tmp_path / "r.db"),
        AnalystAgent(),
        ComposerAgent(),
        DispatcherAgent(_recipients(tmp_path / "recipients.xlsx"), dry_run=True, outbox=outbox),
    ]).run(WorkflowState())

    a = state.analysis
    assert a["count"] == 4
    assert a["total"] == round(99.48 * 2 + 50.31 + 44.07, 2)
    assert a["by_category"]["dining"] == round(99.48 * 2, 2)
    assert any("duplicate" in f for x in a["anomalies"] for f in x["flags"])

    assert "Expense Summary" in state.subject
    assert "| THE CORNER BISTRO |" in state.summary_markdown
    assert "<table" in state.summary_html
    assert state.summary_csv.count("\n") == 1 + 4 + 3 + 2 + 4  # header + items per receipt

    assert [r.email for r in state.recipients] == ["finance@example.com"]  # invalid row skipped
    assert state.dispatched[0]["status"] == "dry-run"
    eml = list(outbox.glob("*.eml"))
    assert len(eml) == 1
    msg = email.message_from_bytes(eml[0].read_bytes())
    assert msg["To"] == "Finance <finance@example.com>"
    assert "Expense Summary" in msg["Subject"]
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts and "text/csv" in parts


def test_date_filter(tmp_path):
    _seed_db(tmp_path / "r.db")
    state = FetcherAgent(db_path=tmp_path / "r.db").run(WorkflowState(since="2026-02-21"))
    assert [r["merchant_name"] for r in state.receipts] == ["QUICK-MART FUEL & MORE"]
