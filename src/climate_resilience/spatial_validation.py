"""Boundary quality gates.

A boundary layer is fit for use only if it is valid, aligns with the
municipality it belongs to, does not self-overlap, and reconciles in area.
These checks run before any ward-level number can be published.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from .spatial import area_km2, intersection_fraction, project

Severity = Literal["error", "warning"]
Geometry = Polygon | MultiPolygon


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class LayerReport:
    count: int
    repaired: list[str]
    issues: list[Issue]
    total_area_km2: float

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def repair(geom: BaseGeometry) -> tuple[BaseGeometry, bool]:
    """Return a valid geometry and whether a repair was needed."""
    if geom.is_valid:
        return geom, False
    fixed = shapely.make_valid(geom)
    if fixed.is_empty:
        fixed = geom.buffer(0)
    return fixed, True


def check_layer(
    wards: dict[str, Geometry],
    municipality: BaseGeometry,
    *,
    min_inside_fraction: float = 0.99,
    area_tolerance: float = 0.02,
    overlap_tolerance: float = 0.005,
    expected_count: int | None = None,
) -> LayerReport:
    """Run all gates. Errors block publication; warnings are recorded."""
    issues: list[Issue] = []
    repaired: list[str] = []

    if expected_count is not None and len(wards) != expected_count:
        issues.append(
            Issue(
                "ward_count",
                "error",
                f"expected {expected_count} wards, found {len(wards)}",
            )
        )

    clean: dict[str, BaseGeometry] = {}
    for key, geom in wards.items():
        fixed, was_repaired = repair(geom)
        if was_repaired:
            repaired.append(key)
        clean[key] = fixed

    for key, geom in clean.items():
        fraction, _ = intersection_fraction(geom, municipality)
        if fraction < min_inside_fraction:
            issues.append(
                Issue(
                    "outside_municipality",
                    "error",
                    f"{key}: only {fraction:.3f} of its area falls inside the municipality",
                )
            )

    ward_area = sum(area_km2(g) for g in clean.values())
    metro_area = area_km2(municipality)
    if metro_area > 0 and abs(ward_area - metro_area) / metro_area > area_tolerance:
        issues.append(
            Issue(
                "area_reconciliation",
                "error",
                f"wards sum to {ward_area:,.1f} km² against municipality {metro_area:,.1f} km²",
            )
        )

    projected = {key: project(geom) for key, geom in clean.items()}
    for key, share_info in _overlaps(projected, overlap_tolerance).items():
        for other, share in share_info:
            issues.append(
                Issue(
                    "overlap",
                    "warning",
                    f"{key} overlaps {other} by {share:.2%} of the smaller ward",
                )
            )

    return LayerReport(
        count=len(clean),
        repaired=repaired,
        issues=issues,
        total_area_km2=ward_area,
    )


def _overlaps(
    projected: dict[str, BaseGeometry], tolerance: float
) -> dict[str, list[tuple[str, float]]]:
    """Pairwise overlap shares, using a spatial index to avoid O(n²) tests."""
    keys = list(projected)
    tree = shapely.STRtree([projected[key] for key in keys])
    found: dict[str, list[tuple[str, float]]] = {}
    for position, key in enumerate(keys):
        geom = projected[key]
        for hit in tree.query(geom):
            if hit <= position:
                continue
            other_key = keys[hit]
            other = projected[other_key]
            overlap = geom.intersection(other).area
            if overlap <= 0:
                continue
            smaller = min(geom.area, other.area)
            share = overlap / smaller if smaller else 0.0
            if share > tolerance:
                found.setdefault(key, []).append((other_key, share))
    return found
