"""WorldPop clipping: values are people, and area shares must conserve them."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from climate_resilience.ingestion.worldpop import _clip_to_municipality

PIXEL = 0.01
WEST, NORTH = 30.0, -29.0
NODATA = -99999.0


def make_raster(tmp_path: Path, values: np.ndarray, *, crs: str = "EPSG:4326") -> Path:
    path = tmp_path / "population.tif"
    profile = {
        "driver": "GTiff",
        "height": values.shape[0],
        "width": values.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": from_origin(WEST, NORTH, PIXEL, PIXEL),
        "nodata": NODATA,
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(values.astype("float32"), 1)
    return path


def test_a_full_polygon_conserves_every_person(tmp_path: Path) -> None:
    path = make_raster(tmp_path, np.full((4, 4), 10.0))
    region = box(WEST, NORTH - 4 * PIXEL, WEST + 4 * PIXEL, NORTH)

    grid = _clip_to_municipality(path, region)

    assert len(grid) == 16
    assert float(grid["population"].sum()) == pytest.approx(160.0, rel=1e-3)
    assert all(value == pytest.approx(1.0, abs=1e-3) for value in grid["fraction_inside"])


def test_a_half_polygon_takes_only_its_share(tmp_path: Path) -> None:
    path = make_raster(tmp_path, np.full((4, 4), 10.0))
    region = box(WEST, NORTH - 4 * PIXEL, WEST + 2 * PIXEL, NORTH)

    grid = _clip_to_municipality(path, region)

    # Projection of a meridian is not exactly vertical, so cells just outside
    # the strip can pick up a sliver. The invariant is the total, not the count.
    assert float(grid["population"].sum()) == pytest.approx(80.0, rel=1e-3)
    assert (grid["fraction_inside"] > 0.5).sum() == 8


def test_a_cell_split_by_the_boundary_is_allocated_by_area(tmp_path: Path) -> None:
    path = make_raster(tmp_path, np.full((4, 4), 10.0))
    region = box(WEST, NORTH - 4 * PIXEL, WEST + PIXEL / 2, NORTH)

    grid = _clip_to_municipality(path, region)

    assert len(grid) == 4
    assert float(grid["population"].sum()) == pytest.approx(20.0, rel=1e-3)
    assert all(value == pytest.approx(0.5, abs=1e-3) for value in grid["fraction_inside"])


def test_nodata_cells_are_excluded_not_counted_as_zero(tmp_path: Path) -> None:
    values = np.full((4, 4), 10.0)
    values[0, 0] = NODATA
    path = make_raster(tmp_path, values)
    region = box(WEST, NORTH - 4 * PIXEL, WEST + 4 * PIXEL, NORTH)

    grid = _clip_to_municipality(path, region)

    assert len(grid) == 15
    assert float(grid["population"].sum()) == pytest.approx(150.0, rel=1e-3)


def test_a_raster_in_the_wrong_crs_is_rejected(tmp_path: Path) -> None:
    path = make_raster(tmp_path, np.full((4, 4), 10.0), crs="EPSG:3857")
    region = box(WEST, NORTH - 4 * PIXEL, WEST + 4 * PIXEL, NORTH)

    with pytest.raises(ValueError, match="EPSG:4326"):
        _clip_to_municipality(path, region)
