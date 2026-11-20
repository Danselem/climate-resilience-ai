"""WorldPop population ingestion.

The project's exposure surface is WorldPop: a dasymetric population grid, not
a ward-total multiplied by an area share. The 100 m national GeoTIFF is 609 MB
and data.worldpop.org does not honour HTTP range requests, so the 100 m file
cannot be subset at download. The 1 km aggregated UN-adjusted product is
7.3 MB, covers the same population model, and is the MVP exposure surface
(ADR-009). The resolution and the upgrade path are recorded, not hidden.

The adapter writes one canonical table: one row per 1 km cell that intersects
the municipality, with the population allocated to the municipality by the
cell's area share. Values are people, never density.
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

WORLDPOP_URL = (
    "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/"
    "ZAF/zaf_ppp_2020_1km_Aggregated_UNadj.tif"
)
VERSION = "wpgp-2020-1km-un-adjusted"
LICENCE = "CC BY 4.0"
RESOLUTION = "1 km (~0.00833 deg)"

# Cells that touch the boundary by a floating-point sliver are not part of the
# region. Counting them adds noise and inflates the cell count without adding
# a meaningful number of people.
MIN_INSIDE_FRACTION = 1e-9


@dataclass(frozen=True)
class WorldPopExtract:
    grid: pd.DataFrame
    dataset: DatasetRef
    raw_path: Path
    processed_path: Path
    pointer_path: Path


def fetch_worldpop(
    settings: Settings,
    municipality: Municipality,
    *,
    version: str = VERSION,
) -> WorldPopExtract:
    """Download (or reuse) the national raster and clip it to the municipality.

    Raw inputs are immutable: an existing file is reused, never re-fetched.
    Pin a new ``version`` to refresh.
    """
    raw_dir = settings.raw_dir / "worldpop" / version
    raw_path = raw_dir / "zaf_ppp_2020_1km_Aggregated_UNadj.tif"
    if not raw_path.exists():
        download(WORLDPOP_URL, raw_path, timeout=300.0)

    grid = _clip_to_municipality(raw_path, municipality.geometry)

    processed_dir = settings.processed_dir / "worldpop" / version
    processed_dir.mkdir(parents=True, exist_ok=True)
    processed_path = processed_dir / "ethekwini_population_1km.parquet"
    grid.to_parquet(processed_path, index=False)

    dataset = DatasetRef(
        id="worldpop",
        version=version,
        checksum=sha256_file(raw_path),
        source_url=WORLDPOP_URL,
        licence=LICENCE,
    )
    pointer_path = write_worldpop_pointer(
        settings,
        version=version,
        path=processed_path,
        dataset=dataset,
    )
    return WorldPopExtract(
        grid=grid,
        dataset=dataset,
        raw_path=raw_path,
        processed_path=processed_path,
        pointer_path=pointer_path,
    )


def _clip_to_municipality(raw_path: Path, region: BaseGeometry) -> pd.DataFrame:
    region_proj = project(region)
    min_lon, min_lat, max_lon, max_lat = region.bounds

    with rasterio.open(raw_path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            raise ValueError(f"WorldPop raster CRS is {ds.crs}, expected EPSG:4326")
        if ds.count != 1:
            raise ValueError(f"WorldPop raster has {ds.count} bands, expected 1")

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
            people = float(value)
            if not np.isfinite(people) or people < 0:
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
                    "cell_id": f"wp_lat{lat:+.5f}_lon{lon:+.5f}",
                    "lon": round(lon, 6),
                    "lat": round(lat, 6),
                    "population": round(people * inside, 6),
                    "fraction_inside": round(inside, 6),
                    "source_value": round(people, 6),
                    "size_deg": round(size_deg, 8),
                }
            )

    if not rows:
        raise RuntimeError("no WorldPop cells intersect the municipality boundary")

    grid = pd.DataFrame(rows).sort_values("cell_id").reset_index(drop=True)
    if float(grid["population"].sum()) <= 0:
        raise RuntimeError("WorldPop allocation produced zero population")
    return grid


def write_worldpop_pointer(
    settings: Settings,
    *,
    version: str,
    path: Path,
    dataset: DatasetRef,
) -> Path:
    target = settings.processed_dir / "worldpop" / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "artifact": f"worldpop/{version}/{path.name}",
        "sha256": sha256_file(path),
        "dataset": dataset.model_dump(),
        "written_at": now_utc().isoformat(),
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def resolve_worldpop_path(settings: Settings, *, version: str | None = None) -> Path:
    """Locate the canonical WorldPop parquet: explicit version, else the pointer."""
    if version is not None:
        path = (
            settings.processed_dir
            / "worldpop"
            / version
            / "ethekwini_population_1km.parquet"
        )
        if not path.exists():
            raise FileNotFoundError(
                f"WorldPop version {version!r} not found at {path}; "
                "run `climate-resilience worldpop` first"
            )
        return path

    pointer = settings.processed_dir / "worldpop" / "latest.json"
    if not pointer.exists():
        raise FileNotFoundError(
            f"no WorldPop pointer at {pointer}; run `climate-resilience worldpop` "
            "(or `climate-resilience data`) first"
        )
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    path = settings.processed_dir / str(payload["artifact"])
    if not path.exists():
        raise FileNotFoundError(
            f"WorldPop pointer refers to a missing artifact: {path}; re-run the stage"
        )
    recorded = str(payload.get("sha256", ""))
    actual = sha256_file(path)
    if recorded and recorded != actual:
        raise RuntimeError(
            f"WorldPop parquet {path} changed since the pointer was written "
            f"({recorded[:12]}… -> {actual[:12]}…); re-run the stage"
        )
    return path


def dataset_from_pointer(settings: Settings) -> DatasetRef:
    """Read the recorded dataset reference, never re-derive it from disk."""
    pointer = settings.processed_dir / "worldpop" / "latest.json"
    if not pointer.exists():
        raise FileNotFoundError(
            f"no WorldPop pointer at {pointer}; run `climate-resilience worldpop` first"
        )
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    return DatasetRef.model_validate(payload["dataset"])
