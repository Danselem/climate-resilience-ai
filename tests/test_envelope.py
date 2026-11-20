"""Envelope contract: the invariants that make results interpretable."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from climate_resilience.envelope import (
    DatasetRef,
    EvidenceEnvelope,
    Period,
    Quality,
    RunRef,
    Scope,
)


def dataset() -> DatasetRef:
    return DatasetRef(
        id="era5_openmeteo",
        version="archive-1980_2024",
        checksum="abc123",
        source_url="https://example.invalid",
        licence="CC BY 4.0",
    )


def run() -> RunRef:
    return RunRef(
        git_commit="deadbeef",
        run_id="20260101T000000Z-00000000",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        inputs_hash="inputshash",
    )


def quality() -> Quality:
    return Quality(
        n_samples=365,
        coverage_pct=100.0,
        missing_pct=0.0,
        native_resolution="0.25 deg (~28 km)",
    )


def heat_envelope(**overrides: object) -> EvidenceEnvelope:
    payload = {
        "value": 12.0,
        "unit": "days",
        "indicator_id": "hot_days_tmax_ge_35c",
        "method_id": "annual_extreme_day_count",
        "method_version": "1.0.0",
        "hazard_type": "heat",
        "scope": Scope(level="grid_cell", id="cell_lat-29.750_lon30.750", name="cell"),
        "period": Period(start=date(2020, 1, 1), end=date(2020, 12, 31), basis="reanalysis"),
        "datasets": [dataset()],
        "quality": quality(),
        "run": run(),
    }
    payload.update(overrides)
    return EvidenceEnvelope(**payload)


def test_heat_envelope_is_valid_and_serialisable() -> None:
    envelope = heat_envelope()
    restored = EvidenceEnvelope.model_validate_json(envelope.model_dump_json())
    assert restored.value == 12.0
    assert restored.period.basis == "reanalysis"


def test_flood_envelope_requires_mechanism_and_parameters() -> None:
    with pytest.raises(ValidationError) as exc:
        heat_envelope(hazard_type="flood")
    assert "mechanism" in str(exc.value)


def test_flood_envelope_rejects_partial_parameters() -> None:
    with pytest.raises(ValidationError):
        heat_envelope(hazard_type="flood", return_period_years=100, depth_threshold_m=0.5)


def test_complete_flood_envelope_is_accepted() -> None:
    envelope = heat_envelope(
        hazard_type="flood",
        return_period_years=100,
        depth_threshold_m=0.5,
        mechanism="riverine",
    )
    assert envelope.mechanism == "riverine"


def test_flood_parameters_are_rejected_on_non_flood_envelopes() -> None:
    with pytest.raises(ValidationError):
        heat_envelope(mechanism="riverine")


def test_projection_requires_scenario_model_and_baseline() -> None:
    with pytest.raises(ValidationError) as exc:
        heat_envelope(period=Period(start=date(2050, 1, 1), end=date(2050, 12, 31),
                                   basis="projection"))
    assert "projection requires" in str(exc.value)


def test_projection_with_full_labelling_is_accepted() -> None:
    envelope = heat_envelope(
        period=Period(start=date(2050, 1, 1), end=date(2050, 12, 31), basis="projection"),
        scenario="RCP8.5",
        model="CSIR",
        baseline_period=Period(
            start=date(1971, 1, 1), end=date(2000, 12, 31), basis="observation"
        ),
    )
    assert envelope.scenario == "RCP8.5"


def test_scenario_on_observation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        heat_envelope(scenario="RCP4.5")


def test_period_end_before_start_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Period(start=date(2020, 1, 1), end=date(2019, 1, 1), basis="reanalysis")
