"""Crosswalk and spot checks: ward placement must be explicit and unambiguous."""

from __future__ import annotations

from shapely.geometry import box

from climate_resilience.crosswalk import build_crosswalk
from climate_resilience.spot_checks import check_points


def test_ward_is_assigned_to_the_containing_municipality() -> None:
    wards = {"w1": ("Ward 1", 1, box(0, 0, 0.1, 0.1))}
    municipalities = {"metro": ("Metro", box(0, 0, 0.2, 0.2))}
    rows = build_crosswalk(wards, municipalities, vintage="2020")

    assert len(rows) == 1
    assert rows[0].municipality_id == "metro"
    assert rows[0].inside_fraction > 0.999
    assert rows[0].ward_number == 1
    assert rows[0].vintage == "2020"


def test_split_ward_is_visible_via_its_fraction() -> None:
    half_inside = box(0.05, 0.0, 0.15, 0.1)  # straddles the municipality edge
    wards = {"w1": ("Ward 1", 1, half_inside)}
    municipalities = {"metro": ("Metro", box(0, 0, 0.1, 0.1))}
    rows = build_crosswalk(wards, municipalities, vintage="2020")

    assert rows[0].inside_fraction < 0.99


def test_best_municipality_wins_when_two_overlap() -> None:
    wards = {"w1": ("Ward 1", 1, box(0.05, 0, 0.15, 0.1))}
    municipalities = {
        "west": ("West", box(0, 0, 0.1, 0.1)),
        "east": ("East", box(0.1, 0, 0.2, 0.1)),
    }
    rows = build_crosswalk(wards, municipalities, vintage="2020")
    # The ward straddles both municipalities, so neither contains it.
    assert 0.45 < rows[0].inside_fraction < 0.55
    assert rows[0].municipality_id in {"west", "east"}


def test_spot_check_passes_when_a_point_hits_exactly_one_ward() -> None:
    wards = {"w1": ("Ward 1", box(0, 0, 1, 1)), "w2": ("Ward 2", box(1, 0, 2, 1))}
    results, issues = check_points(
        wards,
        box(0, 0, 2, 1),
        points=(("inside", 0.5, 0.5, True), ("outside", 9.0, 9.0, False)),
    )

    assert issues == []
    assert results[0].ward_id == "w1"
    assert results[1].ward_name is None


def test_spot_check_fails_when_a_point_is_in_no_ward() -> None:
    wards = {"w1": ("Ward 1", box(0, 0, 1, 1))}
    _, issues = check_points(wards, box(0, 0, 2, 1), points=(("gap", 1.5, 0.5, True),))
    assert issues and issues[0].code == "spot_check"


def test_spot_check_fails_when_a_point_is_in_two_wards() -> None:
    wards = {
        "w1": ("Ward 1", box(0, 0, 1, 1)),
        "w2": ("Ward 2", box(0.5, 0, 2, 1)),
    }
    _, issues = check_points(wards, box(0, 0, 2, 1), points=(("overlap", 0.75, 0.5, True),))
    assert issues and "expected 1 ward" in issues[0].detail


def test_outside_point_landing_inside_a_ward_fails() -> None:
    wards = {"w1": ("Ward 1", box(0, 0, 1, 1))}
    _, issues = check_points(wards, box(0, 0, 1, 1), points=(("wrong", 0.5, 0.5, False),))
    assert issues


def test_passed_reflects_each_point_not_the_previous_failure() -> None:
    wards = {"w1": ("Ward 1", box(0, 0.5, 1, 1))}
    results, issues = check_points(
        wards,
        box(0, 0, 1, 1),
        points=(("gap", 0.5, 0.25, True), ("hit", 0.5, 0.75, True)),
    )

    assert len(issues) == 1
    assert issues[0].detail.startswith("gap:")
    assert [result.passed for result in results] == [False, True]
