"""The catalogue must be coherent, and must not claim more than was done."""

from __future__ import annotations

from pathlib import Path

from climate_resilience.catalogue import load, validate

CATALOGUE = Path(__file__).resolve().parents[1] / "data" / "catalogue" / "datasets.json"


def test_catalogue_parses_and_is_valid() -> None:
    parsed = load(CATALOGUE)
    assert parsed.version == 1
    assert validate(parsed) == []


def test_blocked_datasets_are_visible_not_hidden() -> None:
    parsed = load(CATALOGUE)
    blocked = {entry.id for entry in parsed.by_status("blocked")}
    assert "mdb_wards" in blocked, "the MDB gate must stay visible in the catalogue"


def test_active_datasets_declare_licence_and_checksum() -> None:
    parsed = load(CATALOGUE)
    active = parsed.by_status("active")
    assert active, "at least one dataset should be active after ingestion"
    for entry in active:
        assert entry.checksum, f"{entry.id} is active but has no checksum"
        assert entry.licence and entry.licence != "to be confirmed"
        assert entry.retrieved_at is not None


def test_every_entry_states_coverage_and_time_basis() -> None:
    parsed = load(CATALOGUE)
    for entry in parsed.datasets:
        assert entry.spatial_coverage
        assert entry.temporal_coverage
        assert entry.time_basis


def test_planned_datasets_are_not_marked_active() -> None:
    parsed = load(CATALOGUE)
    planned = {entry.id for entry in parsed.by_status("planned")}
    active = {entry.id for entry in parsed.by_status("active")}
    assert not planned & active


def test_every_active_dataset_is_acquirable() -> None:
    parsed = load(CATALOGUE)
    for entry in parsed.by_status("active"):
        assert entry.artifact, f"{entry.id} is active but names no artifact"
        assert entry.required, f"{entry.id} is active but not marked required"


def test_required_datasets_are_never_merely_planned() -> None:
    from climate_resilience.catalogue import DatasetEntry, validate

    parsed = load(CATALOGUE)
    blocked = next(entry for entry in parsed.datasets if entry.id == "mdb_wards")
    promoted = DatasetEntry(**{**blocked.model_dump(), "required": True})
    problems = validate(parsed.model_copy(update={"datasets": [promoted]}))
    assert any("required dataset is not active" in problem for problem in problems)


def test_active_dataset_without_an_artifact_is_a_problem() -> None:
    from climate_resilience.catalogue import validate

    parsed = load(CATALOGUE)
    stripped = [
        entry.model_copy(update={"artifact": None}) if entry.id == "era5_openmeteo" else entry
        for entry in parsed.datasets
    ]
    problems = validate(parsed.model_copy(update={"datasets": stripped}))
    assert any("no artifact path" in problem for problem in problems)
