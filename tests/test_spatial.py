"""Spatial policy: CRS handling, grid construction and area weights."""

from __future__ import annotations

import pytest
from shapely.geometry import box

from climate_resilience.spatial import (
    Cell,
    area_km2,
    cell_id,
    cells_covering,
    intersection_fraction,
    native_resolution_label,
)

# A box over the Durban coastal strip.
REGION = box(30.90, -30.00, 31.10, -29.80)


def test_area_is_computed_in_metres_not_degrees() -> None:
    # ~0.2 deg square near 30 S is on the order of 400-500 km2.
    assert 350 < area_km2(REGION) < 550


def test_cell_polygon_area_is_roughly_a_quarter_degree_cell() -> None:
    cell = Cell(cell_id="c", lat=-29.875, lon=31.0, size_deg=0.25)
    assert 500 < area_km2(cell.polygon()) < 800


def test_cells_cover_the_region_bounding_box() -> None:
    cells = cells_covering(REGION, 0.25)
    assert cells
    min_lon, min_lat, max_lon, max_lat = REGION.bounds
    for cell in cells:
        assert min_lat <= cell.lat <= max_lat
        assert min_lon <= cell.lon <= max_lon


def test_cell_ids_are_stable_and_readable() -> None:
    first = cell_id(-29.875, 31.0)
    assert first == cell_id(-29.875, 31.0)
    assert "lat-29.875" in first
    assert "lon+31.000" in first


def test_fraction_of_identical_geometry_is_one() -> None:
    fraction, area = intersection_fraction(REGION, REGION)
    assert fraction == pytest.approx(1.0)
    assert area == pytest.approx(area_km2(REGION), rel=1e-6)


def test_fraction_of_disjoint_geometry_is_zero() -> None:
    far_away = box(20.0, -20.0, 20.1, -19.9)
    fraction, area = intersection_fraction(far_away, REGION)
    assert fraction == 0.0
    assert area == 0.0


def test_half_overlap_is_reported_as_a_fraction() -> None:
    shifted = box(31.00, -30.00, 31.20, -29.80)  # shifted east by half a width
    fraction, _ = intersection_fraction(shifted, REGION)
    assert 0.45 < fraction < 0.55


def test_native_resolution_label_states_both_units() -> None:
    label = native_resolution_label(0.25)
    assert "0.25" in label
    assert "km" in label
