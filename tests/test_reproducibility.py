"""N9: the same inputs must produce the same numbers.

Reproducibility is asserted over content hashes that exclude run identity,
because a run id necessarily differs between runs while the values must not.
"""

from __future__ import annotations

from test_mart import build, frame

from climate_resilience.manifest import content_hash


def test_two_builds_from_identical_inputs_are_identical() -> None:
    first = build(frame(), run_id="run-a")
    second = build(frame(), run_id="run-b")
    assert content_hash(first) == content_hash(second)


def test_run_ids_differ_but_values_do_not() -> None:
    first = build(frame(), run_id="run-a")
    second = build(frame(), run_id="run-b")
    assert {r["run_id"] for r in first} == {"run-a"}
    assert {r["run_id"] for r in second} == {"run-b"}
    assert [r["value"] for r in first] == [r["value"] for r in second]


def test_a_changed_input_changes_the_content_hash() -> None:
    baseline = content_hash(build(frame()))
    cooler_inland = content_hash(
        build(frame({"cell_coastal": {2020: 30.0, 2021: 36.0},
                     "cell_inland": {2020: 30.0, 2021: 30.0}}))
    )
    assert baseline != cooler_inland


def test_row_order_does_not_affect_the_content_hash() -> None:
    rows = build(frame())
    assert content_hash(rows) == content_hash(list(reversed(rows)))
