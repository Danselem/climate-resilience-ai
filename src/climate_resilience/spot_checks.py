"""Spot checks at known locations.

These do not assert an externally supplied ward name — doing so without an
authoritative ward list would be inventing a reference. They assert the
structural properties that catch misalignment: a point inside the metro lands
in exactly one ward, a point outside it lands in none, and the assignment is
deterministic and recorded so a reviewer can see where each point fell.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from .spatial_validation import Issue

# (label, lon, lat, expected_inside)
SPOT_POINTS: tuple[tuple[str, float, float, bool], ...] = (
    ("durban_cbd", 31.0218, -29.8587, True),
    ("umhlanga", 31.0850, -29.7260, True),
    ("pinetown", 30.8600, -29.8150, True),
    ("chatsworth", 30.8800, -29.9200, True),
    ("kwamashu", 30.9500, -29.7300, True),
    ("pietermaritzburg", 30.3900, -29.6100, False),
)


@dataclass(frozen=True)
class SpotResult:
    label: str
    ward_id: str | None
    ward_name: str | None
    inside_municipality: bool
    passed: bool


def check_points(
    wards: dict[str, tuple[str, BaseGeometry]],
    municipality: BaseGeometry,
    points: tuple[tuple[str, float, float, bool], ...] = SPOT_POINTS,
) -> tuple[list[SpotResult], list[Issue]]:
    results: list[SpotResult] = []
    issues: list[Issue] = []

    for label, lon, lat, expected_inside in points:
        point = Point(lon, lat)
        inside_metro = municipality.contains(point)
        before = len(issues)

        matches = [
            (wid, wname)
            for wid, (wname, geom) in wards.items()
            if geom.contains(point)
        ]

        if expected_inside and len(matches) != 1:
            issues.append(
                Issue("spot_check", "error", f"{label}: expected 1 ward, found {len(matches)}")
            )
        if not expected_inside and matches:
            issues.append(
                Issue("spot_check", "error", f"{label}: fell inside {len(matches)} ward(s)")
            )
        if inside_metro != expected_inside:
            issues.append(
                Issue(
                    "spot_check",
                    "error",
                    f"{label}: municipality containment {inside_metro}, "
                    f"expected {expected_inside}",
                )
            )

        ward_id, ward_name = matches[0] if len(matches) == 1 else (None, None)
        results.append(
            SpotResult(
                label=label,
                ward_id=ward_id,
                ward_name=ward_name,
                inside_municipality=inside_metro,
                passed=len(issues) == before,
            )
        )

    return results, issues
