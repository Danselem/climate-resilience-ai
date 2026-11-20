"""Aqueduct clipping: depth is metres, nodata is absence, and area is conserved."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from climate_resilience.ingestion.aqueduct import (
    NODATA,
    FloodLayer,
    _clip_layer,
    baseline_layers,
)

PIXEL = 0.01
WEST, NORTH = 30.0, -29.0

LAYER = FloodLayer(
    mechanism="riverine",
    return_period_years=100,
    filename="synthetic.tif",
    model="WATCH",
)


def make_raster(tmp_path: Path, values: np.ndarray, *, crs: str = "EPSG:4326") -> Path:
    path = tmp_path / "depth.tif"
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


def region(*, half_width: float = 4 * PIXEL):
    return box(WEST, NORTH - 4 * PIXEL, WEST + half_width, NORTH)


def test_depth_is_preserved_in_metres(tmp_path: Path) -> None:
    values = np.full((4, 4), 0.25)
    path = make_raster(tmp_path, values)

    frame = _clip_layer(path, region(), LAYER, expect_global=False)

    assert len(frame) == 16
    assert set(frame["depth_m"]) == {0.25}
    assert frame["mechanism"].eq("riverine").all()
    assert frame["return_period_years"].eq(100).all()


def test_dry_cells_are_kept_so_coverage_is_measurable(tmp_path: Path) -> None:
    values = np.zeros((4, 4))
    values[1, 1] = 0.4
    path = make_raster(tmp_path, values)

    frame = _clip_layer(path, region(), LAYER, expect_global=False)

    assert len(frame) == 16
    assert int((frame["depth_m"] > 0).sum()) == 1


def test_nodata_cells_are_absent_not_zero(tmp_path: Path) -> None:
    values = np.full((4, 4), 0.2)
    values[0, 0] = NODATA
    path = make_raster(tmp_path, values)

    frame = _clip_layer(path, region(), LAYER, expect_global=False)

    assert len(frame) == 15
    assert float(frame["depth_m"].min()) == pytest.approx(0.2)


def test_cells_outside_the_region_are_excluded(tmp_path: Path) -> None:
    path = make_raster(tmp_path, np.full((4, 4), 0.3))

    frame = _clip_layer(path, region(half_width=PIXEL), LAYER, expect_global=False)

    # Projecting a meridian is not exactly vertical, so neighbouring columns can
    # pick up a sliver. The invariant is that only one column is meaningfully in.
    inside = frame[frame["fraction_inside"] > 0.5]
    assert len(inside) == 4
    assert inside["lon"].nunique() == 1
    assert float(inside["lon"].iloc[0]) == pytest.approx(WEST + PIXEL / 2, abs=1e-6)


def test_a_raster_in_the_wrong_crs_is_rejected(tmp_path: Path) -> None:
    path = make_raster(tmp_path, np.full((4, 4), 0.3), crs="EPSG:3857")

    with pytest.raises(ValueError, match="EPSG:4326"):
        _clip_layer(path, region(), LAYER, expect_global=False)


def test_a_non_global_raster_is_rejected_when_a_global_layer_is_expected(
    tmp_path: Path,
) -> None:
    path = make_raster(tmp_path, np.full((4, 4), 0.3))

    with pytest.raises(ValueError, match="global"):
        _clip_layer(path, region(), LAYER)


def test_negative_depth_is_not_published(tmp_path: Path) -> None:
    values = np.full((4, 4), 0.2)
    values[2, 2] = -1.0
    path = make_raster(tmp_path, values)

    frame = _clip_layer(path, region(), LAYER, expect_global=False)

    assert (frame["depth_m"] >= 0).all()
    assert len(frame) == 15


def test_the_baseline_parameterisation_is_six_layers() -> None:
    layers = baseline_layers()

    assert len(layers) == 6
    assert {layer.mechanism for layer in layers} == {"riverine", "coastal"}
    assert {layer.return_period_years for layer in layers} == {10, 50, 100}
    assert {layer.model for layer in layers if layer.mechanism == "riverine"} == {"WATCH"}
    assert all("rcp" not in layer.filename for layer in layers)
