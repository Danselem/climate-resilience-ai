"""Climate input selection: explicit version or pointer, never a glob."""

from __future__ import annotations

from pathlib import Path

import pytest

from climate_resilience.config import Settings
from climate_resilience.pipeline import (
    resolve_climate_path,
    write_climate_pointer,
)


def settings_for(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path}/mart.db")


def make_series(settings: Settings, version: str, payload: bytes = b"parquet") -> Path:
    path = (
        settings.processed_dir
        / "era5_openmeteo"
        / version
        / "daily_tmax.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_pointer_is_written_and_resolved(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = make_series(settings, "archive-1980_2024")

    write_climate_pointer(settings, version="archive-1980_2024", path=path)

    assert resolve_climate_path(settings) == path
    assert resolve_climate_path(settings, version="archive-1980_2024") == path


def test_pointer_beats_a_lexicographically_later_version(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    chosen = make_series(settings, "archive-1980_2024")
    make_series(settings, "archive-2020_2030")

    write_climate_pointer(settings, version="archive-1980_2024", path=chosen)

    assert resolve_climate_path(settings) == chosen


def test_resolution_without_a_pointer_explains_the_next_step(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)

    with pytest.raises(FileNotFoundError, match="climate"):
        resolve_climate_path(settings)


def test_explicit_missing_version_lists_the_available_path(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    make_series(settings, "archive-1980_2024")

    with pytest.raises(FileNotFoundError, match="daily_tmax.parquet"):
        resolve_climate_path(settings, version="archive-1900_1910")


def test_a_changed_parquet_is_detected_not_silently_used(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = make_series(settings, "archive-1980_2024")
    write_climate_pointer(settings, version="archive-1980_2024", path=path)
    path.write_bytes(b"rewritten by hand")

    with pytest.raises(RuntimeError, match="changed since the pointer"):
        resolve_climate_path(settings)


def test_a_deleted_artifact_is_reported(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = make_series(settings, "archive-1980_2024")
    write_climate_pointer(settings, version="archive-1980_2024", path=path)
    path.unlink()

    with pytest.raises(FileNotFoundError, match="missing artifact"):
        resolve_climate_path(settings)
