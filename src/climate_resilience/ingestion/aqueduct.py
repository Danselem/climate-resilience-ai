"""Aqueduct Floods v2 baseline hazard ingestion.

Riverine and coastal inundation depth, baseline scenario only. Each layer is a
global 1 km GeoTIFF (43200 x 21600, EPSG:4326, nodata -9999); the adapter
downloads it whole and clips to the municipality, because provenance needs a
real checksum of a real file. WRI serves range requests correctly, but GDAL's
``/vsicurl`` request pattern is throttled with intermittent 403s, so a remote
window read is not dependable and is not used.

Two parameter choices are recorded rather than assumed:

* Baseline only. The 2080 RCP8.5 riverine layers are forced by five GCMs while
  the baseline is forced by WATCH, so a baseline-to-2080 difference confounds
  climate change with a change of forcing dataset. Measured for eThekwini, the
  inter-GCM spread exceeds any change (ADR-010).
* No cell in eThekwini exceeds 0.5 m at any return period, at any mechanism, so
  the published threshold is "any modelled inundation" rather than the 0.5 m
  default. Publishing at 0.5 m would emit a column of structural zeros.

Coastal is genuinely zero here: the same raster floods Maputo Bay, so the null
is a property of the model and this coastline, not of the download.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window, from_bounds
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from ..config import Settings
from ..envelope import DatasetRef, now_utc
from ..manifest import sha256_file
from ..spatial import project
from .boundaries import Municipality
from .http import download

BASE_URL = "https://aqueduct.wridata.org/AqueductFloods20"
VERSION = "v2-historical-baseline"
LICENCE = "CC BY 4.0 (WRI); WRI requests attribution as the source"
# The published raster is 1 km, but the hydrology behind it is PCR-GLOBWB at
# 5' (~10 km). In eThekwini 99% of wet cells carry one of two depth values,
# so the raster is a coarse extent with two depth classes, not a continuous
# 1 km depth field. Both numbers are stated wherever the resolution is.
RASTER_RESOLUTION = "1 km (~0.00833 deg)"
MODEL_RESOLUTION = "5' (~10 km)"
RESOLUTION = f"{RASTER_RESOLUTION} raster; hydrological model {MODEL_RESOLUTION}"
RETURN_PERIODS = (10, 50, 100)
MIN_INSIDE_FRACTION = 1e-9
NODATA = -9999.0


@dataclass(frozen=True)
class FloodLayer:
    """One file: a mechanism, a return period, and its forcing parameterisation."""

    mechanism: str
    return_period_years: int
    filename: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.mechanism}-rp{self.return_period_years:03d}"


def baseline_layers() -> tuple[FloodLayer, ...]:
    """The baseline parameterisation.

    Riverine baseline is forced by WATCH; coastal baseline carries no sea-level
    rise and no subsidence. Both are the documented historical baseline of the
    release, not a choice between alternatives.
    """
    layers: list[FloodLayer] = []
    for rp in RETURN_PERIODS:
        layers.append(
            FloodLayer(
                mechanism="riverine",
                return_period_years=rp,
                filename=f"inunriver_historical_000000000WATCH_1980_rp{rp:05d}.tif",
                model="WATCH",
            )
        )
    for rp in RETURN_PERIODS:
        layers.append(
            FloodLayer(
                mechanism="coastal",
                return_period_years=rp,
                filename=f"inuncoast_historical_nosub_hist_rp{rp:04d}_0.tif",
                model="nosub",
            )
        )
    return tuple(layers)


@dataclass(frozen=True)
class FloodExtract:
    frame: pd.DataFrame
    dataset: DatasetRef
    raw_paths: dict[str, Path]
    processed_path: Path
    pointer_path: Path
    summary: dict[str, object]


def fetch_flood(
    settings: Settings,
    municipality: Municipality,
    *,
    version: str = VERSION,
    layers: tuple[FloodLayer, ...] | None = None,
) -> FloodExtract:
    """Download (or reuse) each baseline layer and clip it to the municipality.

    Raw inputs are immutable: an existing file is reused, never re-fetched.
    Pin a new ``version`` to refresh.
    """
    chosen = layers or baseline_layers()
    raw_dir = settings.raw_dir / "aqueduct_floods" / version
    raw_paths: dict[str, Path] = {}

    for layer in chosen:
        path = raw_dir / layer.filename
        if not path.exists():
            download(f"{BASE_URL}/{layer.filename}", path, timeout=600.0)
        raw_paths[layer.key] = path

    frames = [
        _clip_layer(raw_paths[layer.key], municipality.geometry, layer)
        for layer in chosen
    ]
    frame = pd.concat(frames, ignore_index=True)
    _validate(frame, chosen)

    processed_dir = settings.processed_dir / "aqueduct_floods" / version
    processed_dir.mkdir(parents=True, exist_ok=True)
    processed_path = processed_dir / "ethekwini_flood_depth_1km.parquet"
    frame.to_parquet(processed_path, index=False)

    summary = _summarise(frame, chosen)
    (processed_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    dataset = DatasetRef(
        id="aqueduct_floods",
        version=version,
        checksum=sha256_file(processed_path),
        source_url=BASE_URL,
        licence=LICENCE,
    )
    pointer_path = write_flood_pointer(
        settings,
        version=version,
        path=processed_path,
        dataset=dataset,
        layers=chosen,
        raw_paths=raw_paths,
        summary=summary,
    )
    return FloodExtract(
        frame=frame,
        dataset=dataset,
        raw_paths=raw_paths,
        processed_path=processed_path,
        pointer_path=pointer_path,
        summary=summary,
    )


def _clip_layer(
    path: Path,
    region: BaseGeometry,
    layer: FloodLayer,
    *,
    expect_global: bool = True,
) -> pd.DataFrame:
    """Clip one global raster to the municipality's bounding window."""
    region_proj = project(region)
    min_lon, min_lat, max_lon, max_lat = region.bounds

    with rasterio.open(path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            raise ValueError(
                f"{layer.filename}: CRS is {ds.crs}, expected EPSG:4326"
            )
        if ds.count != 1:
            raise ValueError(f"{layer.filename}: {ds.count} bands, expected 1")
        if expect_global and (ds.width != 43200 or ds.height != 21600):
            raise ValueError(
                f"{layer.filename}: extent is {ds.width}x{ds.height}, "
                "expected the global 43200x21600 grid"
            )

        window = from_bounds(min_lon, min_lat, max_lon, max_lat, transform=ds.transform)
        col_off = max(0, int(np.floor(window.col_off)))
        row_off = max(0, int(np.floor(window.row_off)))
        window = Window(
            col_off=col_off,
            row_off=row_off,
            width=min(ds.width - col_off, int(np.ceil(window.width)) + 1),
            height=min(ds.height - row_off, int(np.ceil(window.height)) + 1),
        )
        data = ds.read(1, window=window, boundless=True, masked=True)
        transform = ds.window_transform(window)
        size_deg = abs(transform.a)

    rows: list[dict[str, object]] = []
    for row in range(data.shape[0]):
        for col in range(data.shape[1]):
            value = data[row, col]
            if np.ma.is_masked(value):
                continue
            depth = float(value)
            if not np.isfinite(depth) or depth < 0 or depth == NODATA:
                continue

            x0, y0 = transform @ (col, row)
            x1, y1 = transform @ (col + 1, row + 1)
            cell = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            cell_proj = project(cell)
            if cell_proj.area <= 0:
                continue
            inside = cell_proj.intersection(region_proj).area / cell_proj.area
            if inside <= MIN_INSIDE_FRACTION:
                continue

            lon = (x0 + x1) / 2
            lat = (y0 + y1) / 2
            rows.append(
                {
                    "cell_id": f"aq_lat{lat:+.5f}_lon{lon:+.5f}",
                    "lon": round(lon, 6),
                    "lat": round(lat, 6),
                    "depth_m": round(depth, 6),
                    "fraction_inside": round(inside, 6),
                    "size_deg": round(size_deg, 8),
                    "mechanism": layer.mechanism,
                    "return_period_years": layer.return_period_years,
                    "scenario": "historical",
                    "model": layer.model,
                }
            )

    if not rows:
        raise RuntimeError(
            f"{layer.filename}: no valid cells intersect the municipality boundary"
        )
    return pd.DataFrame(rows)


def _validate(frame: pd.DataFrame, layers: tuple[FloodLayer, ...]) -> None:
    required = {
        "cell_id",
        "lon",
        "lat",
        "depth_m",
        "mechanism",
        "return_period_years",
        "model",
        "size_deg",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"flood grid missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("flood grid is empty")

    keys = ["cell_id", "mechanism", "return_period_years"]
    if frame.duplicated(keys).any():
        raise ValueError(f"flood grid has duplicate {'/'.join(keys)} rows")
    if (frame["depth_m"] < 0).any():
        raise ValueError("flood grid contains negative depth")

    present = {
        (m, rp)
        for m, rp in zip(
            frame["mechanism"], frame["return_period_years"], strict=True
        )
    }
    expected = {(layer.mechanism, layer.return_period_years) for layer in layers}
    if present != expected:
        raise ValueError(
            f"flood grid is missing layers: {sorted(expected - present)}"
        )


def _summarise(frame: pd.DataFrame, layers: tuple[FloodLayer, ...]) -> dict[str, object]:
    """Per-layer counts, so a null result is recorded, not inferred from silence."""
    cells: dict[str, object] = {}
    for layer in layers:
        subset = frame[
            (frame["mechanism"] == layer.mechanism)
            & (frame["return_period_years"] == layer.return_period_years)
        ]
        cells[layer.key] = {
            "file": layer.filename,
            "model": layer.model,
            "cells": int(len(subset)),
            "wet_cells": int((subset["depth_m"] > 0).sum()),
            "max_depth_m": round(float(subset["depth_m"].max()), 4),
        }
    return {
        "source": "WRI Aqueduct Floods v2, hazard maps",
        "version": VERSION,
        "resolution": RESOLUTION,
        "raster_resolution": RASTER_RESOLUTION,
        "model_resolution": MODEL_RESOLUTION,
        "return_periods": list(RETURN_PERIODS),
        "scenario": "historical",
        "layers": cells,
        "coastal_note": (
            "Coastal baseline has no wet cell in eThekwini at any published return "
            "period; the same raster inundates Maputo Bay, so this is a property of "
            "the model and this coastline, not a failed download"
        ),
        "pluvial_note": "Pluvial (surface-water) flooding is not represented",
    }


def write_flood_pointer(
    settings: Settings,
    *,
    version: str,
    path: Path,
    dataset: DatasetRef,
    layers: tuple[FloodLayer, ...],
    raw_paths: dict[str, Path],
    summary: dict[str, object],
) -> Path:
    target = settings.processed_dir / "aqueduct_floods" / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "artifact": f"aqueduct_floods/{version}/{path.name}",
        "sha256": sha256_file(path),
        "dataset": dataset.model_dump(),
        "layers": [
            {
                "mechanism": layer.mechanism,
                "return_period_years": layer.return_period_years,
                "model": layer.model,
                "file": raw_paths[layer.key].name,
                "sha256": sha256_file(raw_paths[layer.key]),
            }
            for layer in layers
        ],
        "summary": summary,
        "written_at": now_utc().isoformat(),
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def resolve_flood_path(settings: Settings, *, version: str | None = None) -> Path:
    """Locate the canonical flood parquet: explicit version, else the pointer."""
    if version is not None:
        path = (
            settings.processed_dir
            / "aqueduct_floods"
            / version
            / "ethekwini_flood_depth_1km.parquet"
        )
        if not path.exists():
            raise FileNotFoundError(
                f"flood version {version!r} not found at {path}; "
                "run `climate-resilience flood` first"
            )
        return path

    pointer = settings.processed_dir / "aqueduct_floods" / "latest.json"
    if not pointer.exists():
        raise FileNotFoundError(
            f"no flood pointer at {pointer}; run `climate-resilience flood` "
            "(or `climate-resilience data`) first"
        )
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    path = settings.processed_dir / str(payload["artifact"])
    if not path.exists():
        raise FileNotFoundError(
            f"flood pointer refers to a missing artifact: {path}; re-run the flood stage"
        )
    recorded = str(payload.get("sha256", ""))
    actual = sha256_file(path)
    if recorded and recorded != actual:
        raise RuntimeError(
            f"flood parquet {path} changed since the pointer was written "
            f"({recorded[:12]}… -> {actual[:12]}…); re-run the stage"
        )
    return path


def dataset_from_pointer(settings: Settings) -> DatasetRef:
    pointer = settings.processed_dir / "aqueduct_floods" / "latest.json"
    if not pointer.exists():
        raise FileNotFoundError(
            f"no flood pointer at {pointer}; run `climate-resilience flood` first"
        )
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    return DatasetRef.model_validate(payload["dataset"])
