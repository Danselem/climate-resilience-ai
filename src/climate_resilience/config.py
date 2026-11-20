"""Runtime configuration. Environment-driven; no secrets in code."""

from __future__ import annotations

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
    history_start: str = "1980-01-01"
    history_end: str = "2024-12-31"

    # Grid cell size of the ERA5 native resolution, in degrees.
    era5_cell_deg: float = 0.25

    # Minimum fraction of days required before an annual value is published.
    min_coverage: float = 0.90

    # Expected ward count for the pilot municipality, used as a validation gate.
    expected_ward_count: int = 110

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
