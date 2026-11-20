"""Flood exposure indicators.

Flood exposure is a ratio or a population count against a denominator, so the
denominator is stated in every definition: ward area for the area fraction,
WorldPop persons for the population count.

Two rules are structural, not stylistic:

* Riverine and coastal are never summed (I4, §10.7). A row carries one
  mechanism, one return period and one depth threshold.
* Pluvial flooding cannot be produced, because no pluvial layer is registered
  (I9). There is no "all flood" mechanism to fall back to.

The hazard grid is ~1 km. A cell crossing a ward boundary is split by area, not
assigned to the ward containing its centre, and population is interpolated onto
the wet part of each cell. At 1 km that makes the population figure an upper
bound: the model reports one depth per cell, so everyone in a wet cell is
counted as exposed even where the water occupies part of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd
import shapely
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from ..spatial import project

# Fraction of a ward below which an exposed area is smaller than the hazard
# grid can resolve. The value is still published; it carries a warning instead.
MIN_MEANINGFUL_FRACTION = 0.001


class WardLike(Protocol):
    ward_id: str
    geometry: BaseGeometry


@dataclass(frozen=True)
class FloodExposure:
    """One ward (or municipality) for one mechanism and one return period."""

    scope_id: str
    mechanism: str
    return_period_years: int
    exposed_area_km2: float
    scope_area_km2: float
    exposed_population: float
    wet_cells: int
    max_depth_m: float
    coverage_pct: float

    @property
    def area_fraction_pct(self) -> float:
        if self.scope_area_km2 <= 0:
            return 0.0
        return 100.0 * self.exposed_area_km2 / self.scope_area_km2


def compute_flood_exposure(
    grid: pd.DataFrame,
    wards: list[WardLike],
    population: pd.DataFrame,
    *,
    threshold_m: float = 0.0,
) -> list[FloodExposure]:
    """Expose each ward to each hazard layer, by intersection area.

    ``grid`` is the canonical long table with one row per cell per layer;
    ``population`` is the WorldPop table with ``lon``, ``lat``, ``size_deg`` and
    ``source_value``. Coverage is measured against every valid hazard cell, so
    a ward with no hazard data is distinguishable from a dry ward.
    """
    _validate(grid, population, threshold_m)

    ward_proj = [(ward.ward_id, project(ward.geometry)) for ward in wards]
    ward_tree = shapely.STRtree([geom for _, geom in ward_proj])
    ward_area = {ward_id: geom.area / 1e6 for ward_id, geom in ward_proj}

    pop_geom = [_population_cell(row) for row in population.itertuples(index=False)]
    pop_tree = shapely.STRtree(pop_geom)
    pop_values = population["source_value"].to_numpy(dtype=float)

    results: list[FloodExposure] = []
    for (mechanism, return_period), layer in grid.groupby(
        ["mechanism", "return_period_years"], sort=True
    ):
        covered = {ward_id: 0.0 for ward_id in ward_area}
        exposed = {ward_id: 0.0 for ward_id in ward_area}
        persons = {ward_id: 0.0 for ward_id in ward_area}
        wet_cells = {ward_id: 0 for ward_id in ward_area}
        deepest = {ward_id: 0.0 for ward_id in ward_area}

        for record in layer.itertuples(index=False):
            half = float(record.size_deg) / 2
            cell = project(
                box(
                    float(record.lon) - half,
                    float(record.lat) - half,
                    float(record.lon) + half,
                    float(record.lat) + half,
                )
            )
            if cell.area <= 0:
                continue
            depth = float(record.depth_m)
            is_wet = depth > 0 and depth >= threshold_m

            for index in ward_tree.query(cell):
                ward_id, geom = ward_proj[int(index)]
                piece = cell.intersection(geom)
                area = piece.area
                if area <= 0:
                    continue
                covered[ward_id] += area
                if not is_wet:
                    continue

                exposed[ward_id] += area
                wet_cells[ward_id] += 1
                deepest[ward_id] = max(deepest[ward_id], depth)
                persons[ward_id] += _population_in(piece, pop_geom, pop_tree, pop_values)

        for ward_id, area_km2 in ward_area.items():
            if area_km2 <= 0:
                continue
            results.append(
                FloodExposure(
                    scope_id=ward_id,
                    mechanism=str(mechanism),
                    return_period_years=int(return_period),
                    exposed_area_km2=round(exposed[ward_id] / 1e6, 6),
                    scope_area_km2=round(area_km2, 6),
                    exposed_population=round(persons[ward_id], 1),
                    wet_cells=wet_cells[ward_id],
                    max_depth_m=round(deepest[ward_id], 4),
                    coverage_pct=round(100.0 * covered[ward_id] / (area_km2 * 1e6), 2),
                )
            )

    return results


def _population_cell(record: object) -> BaseGeometry:
    half = float(record.size_deg) / 2
    return project(
        box(
            float(record.lon) - half,
            float(record.lat) - half,
            float(record.lon) + half,
            float(record.lat) + half,
        )
    )


def _population_in(
    piece: BaseGeometry,
    pop_geom: list[BaseGeometry],
    pop_tree: shapely.STRtree,
    pop_values: object,
) -> float:
    """Areal interpolation of WorldPop onto the wet piece of a cell."""
    total = 0.0
    for index in pop_tree.query(piece):
        index = int(index)
        cell_area = pop_geom[index].area
        if cell_area <= 0:
            continue
        share = pop_geom[index].intersection(piece).area / cell_area
        if share <= 1e-9:
            continue
        total += float(pop_values[index]) * share  # type: ignore[index]
    return total


def _validate(grid: pd.DataFrame, population: pd.DataFrame, threshold_m: float) -> None:
    required = {
        "cell_id",
        "lon",
        "lat",
        "depth_m",
        "size_deg",
        "mechanism",
        "return_period_years",
    }
    missing = required - set(grid.columns)
    if missing:
        raise ValueError(f"flood grid missing columns: {sorted(missing)}")
    if grid.empty:
        raise ValueError("flood grid is empty")
    if threshold_m < 0:
        raise ValueError(f"depth threshold must be >= 0, got {threshold_m}")

    unknown = set(grid["mechanism"]) - {"riverine", "coastal"}
    if unknown:
        raise ValueError(f"unsupported flood mechanism: {sorted(unknown)}")
    if "pluvial" in set(grid["mechanism"]):
        raise ValueError("I9: pluvial flooding is not a registered mechanism")

    duplicates = grid.duplicated(["cell_id", "mechanism", "return_period_years"])
    if duplicates.any():
        raise ValueError("flood grid has duplicate cell/mechanism/return-period rows")

    if float(population["source_value"].sum()) <= 0:
        raise ValueError("population surface has no people")
