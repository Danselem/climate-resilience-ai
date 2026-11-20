"""Flood exposure: ratios, denominators, and the things that must be refused."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from climate_resilience.flood import (
    COASTAL_NULL_WARNING,
    THRESHOLD_WARNING,
    _depth_quantisation_notes,
    _warnings,
)
from climate_resilience.indicators.flood import (
    FloodExposure,
    compute_flood_exposure,
)

PIXEL = 0.01


@dataclass(frozen=True)
class Ward:
    ward_id: str
    geometry: BaseGeometry


def grid(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def cell(
    lon: float,
    lat: float,
    depth: float,
    *,
    mechanism: str = "riverine",
    rp: int = 100,
) -> dict:
    return {
        "cell_id": f"aq_lat{lat:+.5f}_lon{lon:+.5f}",
        "lon": lon,
        "lat": lat,
        "depth_m": depth,
        "size_deg": PIXEL,
        "mechanism": mechanism,
        "return_period_years": rp,
    }


def population(lon: float, lat: float, people: float) -> dict:
    return {
        "lon": lon,
        "lat": lat,
        "size_deg": PIXEL,
        "source_value": people,
    }


def two_wards() -> list[Ward]:
    """Two wards that split one 0.01 deg cell down the middle."""
    return [
        Ward("ethekwini-001", box(30.0, -29.005, 30.005, -28.995)),
        Ward("ethekwini-002", box(30.005, -29.005, 30.01, -28.995)),
    ]


def one_ward(*, cells: int = 1) -> list[Ward]:
    """A ward covering exactly `cells` 0.01 deg cells."""
    return [Ward("ethekwini-001", box(30.0, -29.005, 30.0 + cells * PIXEL, -28.995))]


def test_a_cell_split_by_a_ward_boundary_is_shared_by_area() -> None:
    frame = grid([cell(30.005, -29.0, 0.4)])
    result = compute_flood_exposure(
        frame, two_wards(), pd.DataFrame([population(30.005, -29.0, 100.0)])
    )

    # Each ward is half a cell, so both are fully exposed; the split shows up in
    # the people, not in the fraction.
    by_ward = {r.scope_id: r for r in result}
    assert by_id(by_ward, "ethekwini-001").area_fraction_pct == pytest.approx(100.0, rel=1e-3)
    assert by_id(by_ward, "ethekwini-002").area_fraction_pct == pytest.approx(100.0, rel=1e-3)
    assert by_id(by_ward, "ethekwini-001").exposed_population == pytest.approx(50.0, rel=1e-2)
    assert by_id(by_ward, "ethekwini-002").exposed_population == pytest.approx(50.0, rel=1e-2)
    assert by_id(by_ward, "ethekwini-001").exposed_area_km2 == pytest.approx(
        by_id(by_ward, "ethekwini-001").scope_area_km2, rel=1e-4
    )


def by_id(by_ward: dict, ward_id: str) -> FloodExposure:
    return next(r for r in by_ward.values() if r.scope_id == ward_id and r.wet_cells >= 0)


def test_dry_cells_count_towards_coverage_but_not_exposure() -> None:
    frame = grid([cell(30.005, -29.0, 0.0), cell(30.015, -29.0, 0.0)])
    wards = one_ward(cells=2)

    result = compute_flood_exposure(frame, wards, pd.DataFrame([population(30.01, -29.0, 80.0)]))

    assert len(result) == 1
    only = result[0]
    assert only.exposed_area_km2 == 0
    assert only.exposed_population == 0
    assert only.wet_cells == 0
    assert only.coverage_pct > 99


def test_the_threshold_excludes_shallower_cells() -> None:
    frame = grid([cell(30.005, -29.0, 0.4), cell(30.015, -29.0, 0.6)])
    wards = one_ward(cells=2)
    population_frame = pd.DataFrame(
        [population(30.005, -29.0, 10.0), population(30.015, -29.0, 90.0)]
    )

    any_depth = compute_flood_exposure(frame, wards, population_frame, threshold_m=0.0)
    deep = compute_flood_exposure(frame, wards, population_frame, threshold_m=0.5)

    assert any_depth[0].wet_cells == 2
    assert any_depth[0].exposed_population == pytest.approx(100.0, rel=1e-2)
    assert any_depth[0].area_fraction_pct == pytest.approx(100.0, rel=1e-3)
    assert deep[0].wet_cells == 1
    assert deep[0].exposed_population == pytest.approx(90.0, rel=1e-2)
    assert deep[0].area_fraction_pct == pytest.approx(50.0, rel=1e-3)


def test_a_ward_with_no_hazard_data_reports_zero_coverage() -> None:
    frame = grid([cell(30.005, -29.0, 0.4)])
    wards = [Ward("ethekwini-001", box(31.0, -30.0, 31.02, -29.98))]

    result = compute_flood_exposure(frame, wards, pd.DataFrame([population(30.005, -29.0, 5.0)]))

    assert result[0].coverage_pct == 0.0
    assert result[0].wet_cells == 0


def test_riverine_and_coastal_are_never_merged() -> None:
    frame = grid(
        [
            cell(30.005, -29.0, 0.4, mechanism="riverine", rp=100),
            cell(30.005, -29.0, 0.0, mechanism="coastal", rp=100),
        ]
    )
    wards = one_ward()

    result = compute_flood_exposure(
        frame, wards, pd.DataFrame([population(30.005, -29.0, 50.0)])
    )

    assert {r.mechanism for r in result} == {"riverine", "coastal"}
    coastal = next(r for r in result if r.mechanism == "coastal")
    assert coastal.exposed_area_km2 == 0


def test_exposure_never_exceeds_the_ward_area() -> None:
    frame = grid([cell(30.005, -29.0, 0.4)])
    wards = two_wards()

    for result in compute_flood_exposure(
        frame, wards, pd.DataFrame([population(30.005, -29.0, 10.0)])
    ):
        assert result.exposed_area_km2 <= result.scope_area_km2 + 1e-6
        assert 0 <= result.area_fraction_pct <= 100


def test_area_increases_monotonically_with_return_period() -> None:
    frame = grid(
        [
            cell(30.005, -29.0, 0.1, rp=10),
            cell(30.005, -29.0, 0.3, rp=50),
            cell(30.005, -29.0, 0.5, rp=100),
            cell(30.015, -29.0, 0.0, rp=10),
            cell(30.015, -29.0, 0.4, rp=50),
            cell(30.015, -29.0, 0.4, rp=100),
        ]
    )
    wards = one_ward(cells=2)

    result = compute_flood_exposure(
        frame, wards, pd.DataFrame([population(30.005, -29.0, 10.0)])
    )
    by_rp = {r.return_period_years: r for r in result}

    assert (
        by_rp[10].area_fraction_pct
        <= by_rp[50].area_fraction_pct
        <= by_rp[100].area_fraction_pct
    )
    assert by_rp[10].max_depth_m <= by_rp[50].max_depth_m <= by_rp[100].max_depth_m


def test_pluvial_is_refused_rather_than_treated_as_another_mechanism() -> None:
    frame = grid([cell(30.005, -29.0, 0.4, mechanism="pluvial")])

    with pytest.raises(ValueError, match="pluvial"):
        compute_flood_exposure(
            frame, two_wards(), pd.DataFrame([population(30.005, -29.0, 1.0)])
        )


def test_duplicate_layer_rows_are_rejected() -> None:
    frame = grid([cell(30.005, -29.0, 0.4), cell(30.005, -29.0, 0.2)])

    with pytest.raises(ValueError, match="duplicate"):
        compute_flood_exposure(
            frame, two_wards(), pd.DataFrame([population(30.005, -29.0, 1.0)])
        )


def test_a_negative_threshold_is_rejected() -> None:
    frame = grid([cell(30.005, -29.0, 0.4)])

    with pytest.raises(ValueError, match="threshold"):
        compute_flood_exposure(
            frame,
            two_wards(),
            pd.DataFrame([population(30.005, -29.0, 1.0)]),
            threshold_m=-0.1,
        )


def test_a_near_binary_depth_field_is_described_not_hidden() -> None:
    frame = grid(
        [cell(30.0 + i * PIXEL, -29.0, 0.466) for i in range(9)]
        + [cell(30.0 + i * PIXEL, -29.1, 0.317) for i in range(3)]
        + [cell(30.0, -29.2, 0.05)]
    )

    notes = _depth_quantisation_notes(frame)

    assert (("riverine", 100) in notes)
    assert "near-binary" in notes[("riverine", 100)]


def test_a_continuous_depth_field_produces_no_quantisation_note() -> None:
    frame = grid([cell(30.0 + i * PIXEL, -29.0, 0.01 * i) for i in range(1, 40)])

    assert _depth_quantisation_notes(frame) == {}


def test_coastal_zero_carries_the_verified_null_warning() -> None:
    result = FloodExposure(
        scope_id="ethekwini-001",
        mechanism="coastal",
        return_period_years=100,
        exposed_area_km2=0.0,
        scope_area_km2=5.0,
        exposed_population=0.0,
        wet_cells=0,
        max_depth_m=0.0,
        coverage_pct=99.0,
    )

    warnings = _warnings(result, 0.0, "ward", None)

    assert COASTAL_NULL_WARNING in warnings
    assert THRESHOLD_WARNING in warnings
