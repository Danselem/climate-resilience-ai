"""Mart assembly: publishing rules, aggregation and provenance."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from climate_resilience.envelope import DatasetRef, RunRef
from climate_resilience.indicators import get as get_indicator
from climate_resilience.mart.build import (
    CellWeight,
    build_cell_rows,
    build_municipality_rows,
)
from climate_resilience.pipeline import schema_columns
from climate_resilience.spatial import Cell

SPEC = get_indicator("hot_days_tmax_ge_35c")


def dataset(version: str = "archive-1980_2024") -> DatasetRef:
    return DatasetRef(
        id="era5_openmeteo",
        version=version,
        checksum="abc",
        source_url="https://example.invalid",
        licence="CC BY 4.0",
    )


def run_ref(run_id: str = "run-1") -> RunRef:
    return RunRef(
        git_commit="deadbeef",
        run_id=run_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        inputs_hash="inputs",
    )


def weights() -> dict[str, CellWeight]:
    coastal = Cell(cell_id="cell_coastal", lat=-29.875, lon=31.0, size_deg=0.25)
    inland = Cell(cell_id="cell_inland", lat=-29.875, lon=30.75, size_deg=0.25)
    return {
        "cell_coastal": CellWeight(cell=coastal, inside_fraction=1.0, area_km2=600.0),
        "cell_inland": CellWeight(cell=inland, inside_fraction=0.5, area_km2=200.0),
    }


def frame(hot_cell_values: dict[str, dict[int, float]] | None = None) -> pd.DataFrame:
    """Two cells, two full years, constant daily values."""
    hot_cell_values = hot_cell_values or {
        "cell_coastal": {2020: 30.0, 2021: 36.0},
        "cell_inland": {2020: 30.0, 2021: 40.0},
    }
    rows = []
    for cell, per_year in hot_cell_values.items():
        for year, daily_value in per_year.items():
            index = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
            for timestamp in index:
                rows.append(
                    {
                        "cell_id": cell,
                        "date": timestamp.date(),
                        "tmax_c": daily_value,
                        "lat": -29.875,
                        "lon": 31.0,
                    }
                )
    return pd.DataFrame(rows)


def build(
    frame_: pd.DataFrame, *, run_id: str = "run-1", dataset_version: str = "archive-1980_2024"
) -> list[dict]:
    cells = build_cell_rows(
        frame_,
        spec=SPEC,
        threshold=35.0,
        weights=weights(),
        datasets=[dataset(dataset_version)],
        run=run_ref(run_id),
        min_coverage=0.90,
        cell_deg=0.25,
    )
    metro = build_municipality_rows(
        cells,
        spec=SPEC,
        weights=weights(),
        municipality_name="eThekwini",
        datasets=[dataset(dataset_version)],
        run=run_ref(run_id),
        cell_deg=0.25,
        years_total=2,
    )
    return cells + metro


def test_cell_rows_publish_one_row_per_cell_per_year() -> None:
    rows = build(frame())
    cell_rows = [r for r in rows if r["scope_level"] == "grid_cell"]
    assert len(cell_rows) == 4
    assert {r["value"] for r in cell_rows if r["period_start"].year == 2021} == {365.0}


def test_withheld_years_are_not_published() -> None:
    incomplete = frame()
    mask = (incomplete["cell_id"] == "cell_coastal") & (
        incomplete["date"] >= date(2021, 3, 1)
    ) & (incomplete["date"] <= date(2021, 8, 31))
    incomplete.loc[mask, "tmax_c"] = float("nan")

    rows = build(incomplete)
    coastal_2021 = [
        r for r in rows if r["scope_id"] == "cell_coastal" and r["period_start"].year == 2021
    ]
    assert coastal_2021 == []


def test_municipality_row_is_area_weighted_and_labelled_derived() -> None:
    rows = build(frame())
    metro = [r for r in rows if r["scope_level"] == "municipality"]
    assert len(metro) == 2
    assert all(r["basis"] == "derived" for r in metro)

    year_2021 = next(r for r in metro if r["period_start"].year == 2021)
    # coastal: 365 days, weight 600; inland: 365 days, weight 200
    assert year_2021["value"] == pytest.approx(365.0)
    assert year_2021["uncertainty_lower"] == 365.0
    assert year_2021["uncertainty_upper"] == 365.0


def test_area_weights_change_the_aggregate() -> None:
    skewed = {
        "cell_coastal": {2020: 30.0, 2021: 36.0},
        "cell_inland": {2020: 30.0, 2021: 30.0},
    }
    rows = build(frame(skewed))
    year_2021 = next(
        r for r in rows if r["scope_level"] == "municipality" and r["period_start"].year == 2021
    )
    # coastal 365 days at weight 600, inland 0 days at weight 200
    assert year_2021["value"] == pytest.approx((365.0 * 600 + 0.0 * 200) / 800)
    assert year_2021["value"] != pytest.approx(365.0)
    assert year_2021["uncertainty_lower"] == 0.0
    assert year_2021["uncertainty_upper"] == 365.0


def test_every_row_has_complete_provenance() -> None:
    rows = build(frame())
    for row in rows:
        assert row["dataset_version"]
        assert row["run_id"] == "run-1"
        assert row["native_resolution"]
        assert row["coverage_pct"] > 0


def test_row_keys_are_unique_across_scopes_and_years() -> None:
    rows = build(frame())
    assert len({r["row_key"] for r in rows}) == len(rows)


def test_row_matches_the_persistence_schema() -> None:
    row = build(frame())[0]
    assert set(row) == schema_columns()


def test_to_row_is_deterministic() -> None:
    first = build(frame(), run_id="a")[0]
    second = build(frame(), run_id="b")[0]
    assert first["row_key"] == second["row_key"]
    assert first["value"] == second["value"]


def test_municipality_scope_name_is_recorded() -> None:
    metro = [r for r in build(frame()) if r["scope_level"] == "municipality"]
    assert all(r["scope_name"] == "eThekwini" for r in metro)


def test_period_covers_a_full_calendar_year() -> None:
    row = build(frame())[0]
    assert row["period_start"] == date(2020, 1, 1)
    assert row["period_end"] == date(2020, 12, 31)


def test_empty_input_produces_no_metro_rows() -> None:
    assert build_municipality_rows(
        [],
        spec=SPEC,
        weights=weights(),
        municipality_name="eThekwini",
        datasets=[dataset()],
        run=run_ref(),
        cell_deg=0.25,
        years_total=2,
    ) == []


def test_period_and_unit_survive_row_flattening() -> None:
    row = build(frame())[0]
    assert row["period_start"] == date(2020, 1, 1)
    assert row["unit"] == "days"
