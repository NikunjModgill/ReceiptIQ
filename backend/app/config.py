"""Runtime settings, all overridable through environment variables (see .env.example)."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (no extra dependency). Existing env vars win."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    data_dir: Path = Path(os.getenv("RECEIPTIQ_DATA_DIR", PROJECT_ROOT / "data"))
    db_path: Path = Path(os.getenv("RECEIPTIQ_DB_PATH", data_dir / "receipts.db"))
    upload_dir: Path = Path(os.getenv("RECEIPTIQ_UPLOAD_DIR", data_dir / "uploads"))
    frontend_dir: Path = PROJECT_ROOT / "frontend"

    max_upload_bytes: int = int(os.getenv("RECEIPTIQ_MAX_UPLOAD_MB", "10")) * 1024 * 1024

    # rules  -> local OCR + rule-based parser only (always free, works offline)
    # llm    -> local OCR, then refine with a free OpenRouter model (needs OPENROUTER_API_KEY)
    # auto   -> llm when a key is configured, otherwise rules
    extraction_engine: str = os.getenv("EXTRACTION_ENGINE", "auto").lower()

    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY") or None
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_timeout_s: float = float(os.getenv("OPENROUTER_TIMEOUT_S", "25"))

    @property
    def llm_enabled(self) -> bool:
        if self.extraction_engine == "rules":
            return False
        return bool(self.openrouter_api_key)


settings = Settings()
