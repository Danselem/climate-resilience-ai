"""Tool contracts: evidence or a precise refusal, never a bare number."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from test_mart import build, frame

from climate_resilience.envelope import (
    DatasetRef,
    EvidenceEnvelope,
    Period,
    Quality,
    RunRef,
    Scope,
)
from climate_resilience.mart.build import to_row
from climate_resilience.store import repository
from climate_resilience.store.models import boundary, boundary_crosswalk, indicator_value
from climate_resilience.tools import (
    coverage,
    explain,
    get_indicator,
    rank_scopes,
    resolve_scope,
)

HEAT = "hot_days_tmax_ge_35c"
FLOOD_AREA = "flood_exposed_area_pct"


@pytest.fixture
def engine():
    engine = repository.make_engine("sqlite://")
    repository.ensure_schema(engine)
    return engine


def seed_heat(engine) -> list[dict]:
    rows = build(frame())
    repository.replace_build(
        engine, rows, indicator_id=HEAT, method_version="1.0.0"
    )
    return rows


def run_ref() -> RunRef:
    return RunRef(
        git_commit="deadbeef",
        run_id="run-flood",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        inputs_hash="inputs",
    )


def flood_row(
    scope_id: str,
    *,
    mechanism: str = "riverine",
    return_period: int = 100,
    value: float = 10.0,
) -> dict:
    envelope = EvidenceEnvelope(
        value=value,
        unit="percent",
        indicator_id=FLOOD_AREA,
        method_id="aqueduct_inundation_area_share",
        method_version="1.0.0",
        hazard_type="flood",
        return_period_years=return_period,
        depth_threshold_m=0.0,
        mechanism=mechanism,  # type: ignore[arg-type]
        scope=Scope(level="ward", id=scope_id, name=scope_id),
        period=Period(
            start=date(1960, 1, 1), end=date(1999, 12, 31), basis="modelled_estimate"
        ),
        datasets=[
            DatasetRef(
                id="aqueduct_floods",
                version="v2-historical-baseline",
                checksum="abc",
                source_url="https://example.invalid",
                licence="CC BY 4.0",
            )
        ],
        quality=Quality(
            n_samples=1,
            coverage_pct=100.0,
            missing_pct=0.0,
            native_resolution="1 km",
            warnings=["pluvial flooding is not modelled"],
        ),
        run=run_ref(),
    )
    return to_row(envelope)


def seed_flood(engine, rows: list[dict]) -> None:
    repository.replace_build(
        engine, rows, indicator_id=FLOOD_AREA, method_version="1.0.0"
    )


def test_a_tool_returns_the_envelope_not_just_the_number(engine) -> None:
    seed_heat(engine)

    result = get_indicator(engine, indicator_id=HEAT)

    assert result.status == "ok"
    assert result.envelopes
    envelope = result.envelopes[0]
    assert envelope.datasets[0].licence == "CC BY 4.0"
    assert envelope.method_id == "annual_extreme_day_count"
    assert envelope.run.git_commit == "deadbeef"
    assert envelope.quality.warnings == [
        "ERA5 via Open-Meteo (secondary distribution); Copernicus CDS adapter "
        "not yet implemented"
    ]


def test_an_unregistered_indicator_is_refused_with_the_registry(engine) -> None:
    seed_heat(engine)

    result = get_indicator(engine, indicator_id="flood_risk_score")

    assert result.status == "insufficient"
    assert result.envelopes == []
    assert any(HEAT in item for item in result.missing)
    assert result.available is not None


def test_a_request_outside_the_published_window_is_refused(engine) -> None:
    seed_heat(engine)

    result = get_indicator(engine, indicator_id=HEAT, period_year=1900)

    assert result.status == "insufficient"
    assert result.available is not None
    assert result.available.indicators == [HEAT]


def test_a_flood_ranking_requires_a_return_period(engine) -> None:
    seed_flood(engine, [flood_row("ethekwini-001")])

    result = rank_scopes(engine, indicator_id=FLOOD_AREA)

    assert result.status == "insufficient"
    assert "return_period_years" in result.missing
    assert result.available is not None
    assert 100 in result.available.return_periods


def test_a_flood_ranking_never_ranks_across_mechanisms(engine) -> None:
    seed_flood(
        engine,
        [
            flood_row("ethekwini-001", mechanism="riverine", value=40.0),
            flood_row("ethekwini-002", mechanism="riverine", value=20.0),
            flood_row("ethekwini-001", mechanism="coastal", value=99.0),
        ],
    )

    result = rank_scopes(engine, indicator_id=FLOOD_AREA, return_period_years=100)

    assert result.status == "ok"
    mechanisms = [envelope.mechanism for envelope in result.envelopes]
    # Grouped, never interleaved: a coastal 99 must not outrank a riverine 40.
    assert mechanisms == sorted(mechanisms)
    assert result.message is not None
    assert "never be added" in result.message


def test_a_flood_ranking_returns_only_the_requested_mechanism(engine) -> None:
    seed_flood(
        engine,
        [
            flood_row("ethekwini-001", mechanism="riverine", value=40.0),
            flood_row("ethekwini-002", mechanism="riverine", value=20.0),
            flood_row("ethekwini-001", mechanism="coastal", value=99.0),
        ],
    )

    result = rank_scopes(
        engine, indicator_id=FLOOD_AREA, return_period_years=100, mechanism="riverine"
    )

    assert result.status == "ok"
    assert {envelope.mechanism for envelope in result.envelopes} == {"riverine"}
    assert [envelope.value for envelope in result.envelopes] == [40.0, 20.0]


def test_ranking_uses_the_latest_period_rather_than_mixing_years(engine) -> None:
    skewed = {
        "cell_coastal": {2020: 30.0, 2021: 36.0},
        "cell_inland": {2020: 36.0, 2021: 30.0},
    }
    rows = build(frame(skewed))
    repository.replace_build(engine, rows, indicator_id=HEAT, method_version="1.0.0")

    result = rank_scopes(engine, indicator_id=HEAT, scope_level="grid_cell", limit=2)

    assert result.status == "ok"
    years = {envelope.period.start.year for envelope in result.envelopes}
    assert years == {2021}
    assert result.message is not None
    assert "latest published period (2021)" in result.message
    assert result.envelopes[0].scope.id == "cell_coastal"


def test_explain_returns_the_row_it_was_given(engine) -> None:
    rows = seed_heat(engine)
    row_key = str(rows[0]["row_key"])

    result = explain(engine, row_key=row_key)

    assert result.status == "ok"
    assert len(result.envelopes) == 1
    assert result.envelopes[0].indicator_id == HEAT


def test_explain_refuses_an_unknown_key(engine) -> None:
    seed_heat(engine)

    result = explain(engine, row_key="nope")

    assert result.status == "insufficient"


def test_coverage_reports_what_the_mart_holds(engine) -> None:
    seed_heat(engine)
    seed_flood(engine, [flood_row("ethekwini-001")])

    result = coverage(engine)

    assert result.status == "ok"
    assert result.available is not None
    assert set(result.available.indicators) == {HEAT, FLOOD_AREA}
    assert result.available.rows == 7


def seed_boundaries(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            boundary.insert(),
            [
                {
                    "boundary_id": "ethekwini-075",
                    "level": "ward",
                    "name": "Ward 75",
                    "code": 75,
                    "parent_id": "ethekwini",
                    "vintage": "adm4-2020",
                    "dataset_id": "geoboundaries_zaf_adm4",
                    "dataset_version": "adm4-2020",
                    "crs": "EPSG:4326",
                    "area_km2": 7.06,
                    "geometry_wkt": "POLYGON ((0 0, 1 0, 1 1, 0 0))",
                },
                {
                    "boundary_id": "ethekwini",
                    "level": "municipality",
                    "name": "eThekwini",
                    "code": None,
                    "parent_id": None,
                    "vintage": "adm2-2020",
                    "dataset_id": "geoboundaries_zaf_adm2",
                    "dataset_version": "adm2-2020",
                    "crs": "EPSG:4326",
                    "area_km2": 2556.6,
                    "geometry_wkt": "POLYGON ((0 0, 1 0, 1 1, 0 0))",
                },
            ],
        )
        conn.execute(
            boundary_crosswalk.insert(),
            [
                {
                    "ward_id": "ethekwini-075",
                    "vintage": "adm4-2020",
                    "ward_name": "Ward 75",
                    "ward_number": 75,
                    "municipality_id": "ethekwini",
                    "municipality_name": "eThekwini",
                    "inside_fraction": 1.0,
                    "area_km2": 7.06,
                }
            ],
        )


def test_resolve_scope_accepts_a_ward_number(engine) -> None:
    seed_boundaries(engine)

    result = resolve_scope(engine, query="ward 75")

    assert result.status == "ok"
    assert [scope.id for scope in result.scopes] == ["ethekwini-075"]
    assert result.scopes[0].ward_number == 75


def test_resolve_scope_accepts_a_municipality_name(engine) -> None:
    seed_boundaries(engine)

    result = resolve_scope(engine, query="ethekwini")

    assert result.status == "ok"
    assert result.scopes[0].level == "municipality"


def test_resolve_scope_refuses_a_place_it_does_not_hold(engine) -> None:
    seed_boundaries(engine)

    result = resolve_scope(engine, query="Umlazi")

    assert result.status == "insufficient"
    assert result.scopes == []


def test_the_mart_rejects_a_row_without_an_envelope(engine) -> None:
    seed_heat(engine)
    with engine.begin() as conn:
        conn.execute(indicator_value.update().values(envelope_json=None))

    with pytest.raises(RuntimeError, match="envelope_json"):
        get_indicator(engine, indicator_id=HEAT)
