"""Runtime configuration. Environment-driven; no secrets in code."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CRP_", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/mart.db"
    municipality: str = "eThekwini"

    # Climate data window for the historical baseline.
    # `history_end = None` means "the last complete calendar year", resolved at
    # fetch time and recorded in the dataset version. Set it explicitly to pin
    # a window. A partial year is never published (see indicators/heat.py).
    history_start: str = "1980-01-01"
    history_end: str | None = None

    # Grid cell size of the ERA5 native resolution, in degrees.
    era5_cell_deg: float = 0.25

    # Minimum fraction of days required before an annual value is published.
    min_coverage: float = 0.90

    # Expected ward count for the pilot municipality, used as a validation gate.
    expected_ward_count: int = 110

    # Document index (pgvector). Deliberately a different store from the mart:
    # prose needs similarity search, measurements need exact keys.
    documents_dsn: str = "postgresql://crp:crp@localhost:5433/crp"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    log_level: str = "INFO"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def manifest_dir(self) -> Path:
        return self.data_dir / "manifests"

    @property
    def catalogue_dir(self) -> Path:
        return self.data_dir / "catalogue"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def resolve_history_end(history_end: str | None, *, today: date | None = None) -> str:
    """Return an explicit end date, or the last complete calendar year.

    A dynamic default must still yield a reproducible run, so the resolved
    value is written into the dataset version and the run manifest. Fetching
    again in January produces a new version, not a mutated one.
    """
    if history_end:
        return history_end
    today = today or date.today()
    return date(today.year - 1, 12, 31).isoformat()
