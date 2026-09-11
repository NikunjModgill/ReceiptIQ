"""Write a sample recipients.xlsx for the Expense Dispatcher (columns: name, email, department)."""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook

ROWS = [
    ("Finance Team", "finance@example.com", "finance"),
    ("Priya Manager", "priya.manager@example.com", "engineering"),
    ("Not An Email", "this-is-invalid", "ignored"),  # skipped by the dispatcher's validation
]


def main(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "recipients"
    ws.append(["name", "email", "department"])
    for row in ROWS:
        ws.append(row)
    wb.save(path)
    print(f"wrote {path} with {len(ROWS)} row(s)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("recipients.xlsx"))
