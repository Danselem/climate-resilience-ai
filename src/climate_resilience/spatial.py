"""Spatial policy and grid/polygon geometry.

Storage CRS is EPSG:4326. Distances and areas are computed in EPSG:32736
(UTM zone 36S), which covers the eThekwini metro. Reprojection is explicit
and logged, never implicit.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, box, shape
from shapely.geometry.base import BaseGeometry

STORAGE_CRS = "EPSG:4326"
COMPUTE_CRS = "EPSG:32736"
METRES_PER_DEGREE_AT_EQUATOR = 111_320.0


@dataclass(frozen=True)
class Cell:
    """One native-resolution grid cell, identified by its centre."""

    cell_id: str
    lat: float
    lon: float
    size_deg: float

    def polygon(self) -> Polygon:
        half = self.size_deg / 2
        return box(self.lon - half, self.lat - half, self.lon + half, self.lat + half)


def load_geojson(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def feature_by_name(collection: dict, needle: str) -> dict:
    """Find the first feature whose name properties contain `needle`."""
    target = needle.strip().lower()
    for feature in collection.get("features", []):
        props = {k: str(v) for k, v in feature.get("properties", {}).items() if v is not None}
        if any(target in value.lower() for value in props.values()):
            return feature
    raise LookupError(f"no feature matching {needle!r} in collection")


def geometry_of(feature: dict) -> BaseGeometry:
    geom = shape(feature["geometry"])
    if not geom.is_valid:
        raise ValueError("invalid geometry; repair before use")
    return geom


def project(geom: BaseGeometry, dst_crs: str = COMPUTE_CRS) -> BaseGeometry:
    transformer = _transformer(dst_crs)

    def reproject(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, reproject)


@lru_cache(maxsize=8)
def _transformer(dst_crs: str) -> Transformer:
    return Transformer.from_crs(STORAGE_CRS, dst_crs, always_xy=True)


def area_km2(geom: BaseGeometry, crs: str = COMPUTE_CRS) -> float:
    return project(geom, crs).area / 1_000_000.0


def intersection_fraction(cell: BaseGeometry, region: BaseGeometry) -> tuple[float, float]:
    """Return (fraction of cell inside region, intersection area in km²)."""
    cell_proj = project(cell)
    region_proj = project(region)
    cell_area = cell_proj.area
    if cell_area <= 0:
        return 0.0, 0.0
    inter = cell_proj.intersection(region_proj)
    return inter.area / cell_area, inter.area / 1_000_000.0


def cell_id(lat: float, lon: float) -> str:
    """Stable, readable identifier for a grid cell."""
    return f"cell_lat{lat:+.3f}_lon{lon:+.3f}"


def cells_covering(region: BaseGeometry, size_deg: float) -> list[Cell]:
    """Grid cells aligned to the native grid whose polygons intersect the bbox.

    Cells are anchored on multiples of ``size_deg``, matching the ERA5 grid
    convention where grid points sit on exact multiples rather than being
    offset by half a cell.
    """
    min_lon, min_lat, max_lon, max_lat = region.bounds
    step = size_deg
    lon_start = math.ceil(min_lon / step) * step
    lat_start = math.ceil(min_lat / step) * step

    cells: list[Cell] = []
    lon = lon_start
    while lon <= max_lon:
        lat = lat_start
        while lat <= max_lat:
            cells.append(
                Cell(cell_id=cell_id(lat, lon), lat=round(lat, 6), lon=round(lon, 6),
                     size_deg=step)
            )
            lat += step
        lon += step
    return cells


def native_resolution_label(size_deg: float) -> str:
    km = size_deg * METRES_PER_DEGREE_AT_EQUATOR / 1000.0
    return f"{size_deg:g} deg (~{km:.0f} km)"
