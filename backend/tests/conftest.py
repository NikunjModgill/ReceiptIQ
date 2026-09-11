import os
import tempfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Point the app at a throwaway data dir BEFORE backend.app.config is imported.
_tmp = tempfile.mkdtemp(prefix="receiptiq-test-")
os.environ["RECEIPTIQ_DATA_DIR"] = _tmp
os.environ["RECEIPTIQ_DB_PATH"] = str(Path(_tmp) / "test.db")
os.environ["RECEIPTIQ_UPLOAD_DIR"] = str(Path(_tmp) / "uploads")
os.environ["EXTRACTION_ENGINE"] = "rules"
os.environ.pop("OPENROUTER_API_KEY", None)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory) -> Path:
    """A one-page PDF wrapping the Target receipt, to exercise the PDF path."""
    from PIL import Image

    out = tmp_path_factory.mktemp("pdf") / "target.pdf"
    with Image.open(FIXTURES / "target.png") as img:
        img.convert("RGB").save(out, "PDF", resolution=200)
    return out
