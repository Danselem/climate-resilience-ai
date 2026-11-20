"""Boundary gates: validity, alignment, overlap and area reconciliation."""

from __future__ import annotations

from shapely.geometry import Polygon, box

from climate_resilience.spatial_validation import check_layer, repair


def tile(side: int = 2, size: float = 0.1) -> dict[str, Polygon]:
    """A perfect grid of squares, keyed by row-column."""
    return {
        f"{r}{c}": box(c * size, r * size, (c + 1) * size, (r + 1) * size)
        for r in range(side)
        for c in range(side)
    }


def municipality(size: float = 0.2) -> Polygon:
    return box(0, 0, size, size)


def test_a_clean_tiled_layer_passes() -> None:
    report = check_layer(tile(), municipality(), expected_count=4)
    assert report.ok, report.errors
    assert report.repaired == []
    assert report.count == 4


def test_invalid_geometry_is_repaired_not_dropped() -> None:
    bowtie = Polygon([(0, 0), (0.1, 0.1), (0.1, 0), (0, 0.1)])
    assert not bowtie.is_valid

    fixed, was_repaired = repair(bowtie)
    assert was_repaired
    assert fixed.is_valid


def test_repairs_are_reported() -> None:
    wards = tile()
    wards["broken"] = Polygon([(0.2, 0.2), (0.3, 0.3), (0.3, 0.2), (0.2, 0.3)])
    report = check_layer(wards, municipality(0.4), expected_count=None)
    assert "broken" in report.repaired


def test_ward_outside_the_municipality_is_an_error() -> None:
    wards = tile()
    wards["away"] = box(5, 5, 5.1, 5.1)
    report = check_layer(wards, municipality())
    codes = {issue.code for issue in report.errors}
    assert "outside_municipality" in codes
    assert not report.ok


def test_area_mismatch_is_an_error() -> None:
    # Two wards covering only half of the municipality.
    wards = {"a": box(0, 0, 0.1, 0.2), "b": box(0.1, 0, 0.2, 0.2)}
    partial = box(0, 0, 0.4, 0.2)
    report = check_layer(wards, partial)
    codes = {issue.code for issue in report.errors}
    assert "area_reconciliation" in codes


def test_wrong_ward_count_is_an_error() -> None:
    report = check_layer(tile(), municipality(), expected_count=110)
    assert any(issue.code == "ward_count" for issue in report.errors)


def test_overlap_is_reported_as_a_warning() -> None:
    wards = tile()
    wards["duplicate"] = box(0, 0, 0.1, 0.1)
    report = check_layer(wards, municipality(), expected_count=None)
    overlaps = [i for i in report.issues if i.code == "overlap"]
    assert overlaps
    assert all(i.severity == "warning" for i in overlaps)


def test_empty_layer_does_not_crash() -> None:
    report = check_layer({}, municipality(), expected_count=None)
    assert report.count == 0
