"""Exposure allocation and envelopes: separate from hazard, traceable to a grid."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import box

from climate_resilience.config import Settings
from climate_resilience.envelope import DatasetRef
from climate_resilience.exposure import (
    INDICATOR_ID,
    WardGeometry,
    allocate_to_wards,
    build_exposure,
)
from climate_resilience.store import repository

WORLDPOP = DatasetRef(
    id="worldpop",
    version="test-v1",
    checksum="raw-checksum",
    source_url="https://example.invalid/worldpop.tif",
    licence="CC BY 4.0",
)


def grid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cell_id": "a",
                "lon": 30.005,
                "lat": -29.0,
                "population": 100.0,
                "fraction_inside": 1.0,
                "source_value": 100.0,
                "size_deg": 0.01,
            },
            {
                "cell_id": "b",
                "lon": 30.015,
                "lat": -29.0,
                "population": 100.0,
                "fraction_inside": 1.0,
                "source_value": 100.0,
                "size_deg": 0.01,
            },
        ]
    )


def wards() -> list[WardGeometry]:
    return [
        WardGeometry(
            ward_id="ethekwini-001",
            ward_name="eThekwini 001",
            ward_number=1,
            geometry=box(30.0, -29.01, 30.005, -28.99),
            checksum="ward-checksum",
        ),
        WardGeometry(
            ward_id="ethekwini-002",
            ward_name="eThekwini 002",
            ward_number=2,
            geometry=box(30.005, -29.01, 30.02, -28.99),
            checksum="ward-checksum",
        ),
    ]


def test_a_boundary_cell_is_split_between_wards() -> None:
    totals, counts = allocate_to_wards(grid_frame(), wards())

    assert totals["ethekwini-001"] == pytest.approx(50.0, rel=1e-4)
    assert totals["ethekwini-002"] == pytest.approx(150.0, rel=1e-4)
    assert counts["ethekwini-001"] == 1
    assert counts["ethekwini-002"] == 2


def test_ward_allocations_sum_to_the_municipal_total() -> None:
    totals, _ = allocate_to_wards(grid_frame(), wards())
    assert sum(totals.values()) == pytest.approx(float(grid_frame()["population"].sum()), rel=1e-4)


def test_build_exposure_publishes_wards_and_municipality(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/mart.db",
    )
    path = tmp_path / "grid.parquet"
    grid_frame().to_parquet(path, index=False)

    summary = build_exposure(
        settings,
        worldpop_path=path,
        worldpop_dataset=WORLDPOP,
        wards=wards(),
    )

    assert summary.rows == 3
    engine = repository.make_engine(settings.database_url)
    rows = repository.fetch(engine, indicator_id=INDICATOR_ID)
    assert len(rows) == 3

    ward_rows = [row for row in rows if row["scope_level"] == "ward"]
    metro = [row for row in rows if row["scope_level"] == "municipality"]
    assert sum(row["value"] for row in ward_rows) == pytest.approx(200.0, rel=1e-4)
    assert metro[0]["value"] == pytest.approx(200.0, rel=1e-4)
    assert all(row["hazard_type"] == "none" for row in rows)
    assert all(row["basis"] == "modelled_estimate" for row in rows)
    assert all(row["period_start"].year == 2020 for row in rows)
    assert all("test-v1" in row["dataset_version"] for row in rows)
    assert any("not a census count" in warning for warning in _warnings(rows[0]))


def test_a_duplicate_cell_id_is_rejected(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/mart.db",
    )
    frame = grid_frame()
    frame.loc[1, "cell_id"] = "a"
    path = tmp_path / "grid.parquet"
    frame.to_parquet(path, index=False)

    with pytest.raises(ValueError, match="duplicate cell_id"):
        build_exposure(
            settings,
            worldpop_path=path,
            worldpop_dataset=WORLDPOP,
            wards=wards(),
        )


def _warnings(row: dict) -> list[str]:
    import json

    return json.loads(row["warnings"])
