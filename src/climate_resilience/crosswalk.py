"""Ward-to-municipality crosswalk.

Ward codes are not stable across delimitation cycles, so the mapping is stored
explicitly with its vintage rather than inferred at query time. A join without
a crosswalk is a defect.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from .spatial import area_km2, intersection_fraction


@dataclass(frozen=True)
class CrosswalkRow:
    ward_id: str
    ward_name: str
    ward_number: int | None
    municipality_id: str
    municipality_name: str
    vintage: str
    area_km2: float
    inside_fraction: float


def build_crosswalk(
    wards: dict[str, tuple[str, int | None, BaseGeometry]],
    municipalities: dict[str, tuple[str, BaseGeometry]],
    *,
    vintage: str,
    min_inside: float = 0.99,
) -> list[CrosswalkRow]:
    """Assign each ward to the municipality that contains it.

    A ward that no municipality contains, or that is split between two, is
    reported by returning ``inside_fraction < min_inside`` so the caller can
    fail rather than guess.
    """
    rows: list[CrosswalkRow] = []
    for ward_id, (ward_name, ward_number, ward_geom) in sorted(wards.items()):
        best: CrosswalkRow | None = None
        for muni_id, (muni_name, muni_geom) in municipalities.items():
            fraction, _ = intersection_fraction(ward_geom, muni_geom)
            if best is None or fraction > best.inside_fraction:
                best = CrosswalkRow(
                    ward_id=ward_id,
                    ward_name=ward_name,
                    ward_number=ward_number,
                    municipality_id=muni_id,
                    municipality_name=muni_name,
                    vintage=vintage,
                    area_km2=round(area_km2(ward_geom), 4),
                    inside_fraction=round(fraction, 6),
                )
        if best is not None:
            rows.append(best)
    return rows
