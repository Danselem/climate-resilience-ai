"""Persistence and weighting: the write path the mart depends on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import box
from test_mart import build, frame

from climate_resilience.envelope import DatasetRef
from climate_resilience.ingestion.boundaries import Municipality
from climate_resilience.pipeline import weights_from_frame
from climate_resilience.store import repository


@pytest.fixture
def engine():
    engine = repository.make_engine("sqlite://")
    repository.ensure_schema(engine)
    return engine


def test_replace_build_inserts_rows(engine) -> None:
    rows = build(frame())
    inserted = repository.replace_build(
        engine,
        rows,
        indicator_id="hot_days_tmax_ge_35c",
        method_version="1.0.0",
    )
    assert inserted == len(rows)
    assert repository.count(engine) == len(rows)


def test_rebuilding_is_idempotent(engine) -> None:
    rows = build(frame(), run_id="run-a")
    kwargs = {
        "indicator_id": "hot_days_tmax_ge_35c",
        "method_version": "1.0.0",
    }
    repository.replace_build(engine, rows, **kwargs)
    repository.replace_build(engine, build(frame(), run_id="run-b"), **kwargs)

    assert repository.count(engine) == len(rows), "a rebuild must not duplicate rows"


def test_fetch_can_filter_by_scope(engine) -> None:
    rows = build(frame())
    repository.replace_build(
        engine,
        rows,
        indicator_id="hot_days_tmax_ge_35c",
        method_version="1.0.0",
    )

    metro = repository.fetch(
        engine, indicator_id="hot_days_tmax_ge_35c", scope_level="municipality"
    )
    cells = repository.fetch(engine, indicator_id="hot_days_tmax_ge_35c", scope_level="grid_cell")

    assert len(metro) == 2
    assert len(cells) == 4
    assert all(row["basis"] == "derived" for row in metro)


def test_fetch_orders_by_period(engine) -> None:
    rows = build(frame())
    repository.replace_build(
        engine,
        rows,
        indicator_id="hot_days_tmax_ge_35c",
        method_version="1.0.0",
    )
    metro = repository.fetch(
        engine, indicator_id="hot_days_tmax_ge_35c", scope_level="municipality"
    )
    assert [row["period_start"].year for row in metro] == [2020, 2021]


def test_row_key_includes_the_dataset_version() -> None:
    first = build(frame(), dataset_version="v1")[0]
    second = build(frame(), dataset_version="v2")[0]
    assert first["row_key"] != second["row_key"]


def test_a_new_dataset_version_replaces_the_live_rows(engine) -> None:
    first = build(frame(), dataset_version="v1")
    repository.replace_build(
        engine,
        first,
        indicator_id="hot_days_tmax_ge_35c",
        method_version="1.0.0",
    )
    second = build(frame(), dataset_version="v2")
    repository.replace_build(
        engine,
        second,
        indicator_id="hot_days_tmax_ge_35c",
        method_version="1.0.0",
    )
    assert repository.count(engine) == len(second), (
        "a new input version supersedes the live rows; stale duplicates are not kept"
    )


def municipality(tmp_path: Path) -> Municipality:
    feature = tmp_path / "ethekwini.geojson"
    feature.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    return Municipality(
        name="eThekwini",
        feature_path=feature,
        geometry=box(30.9, -30.0, 31.1, -29.8),
        dataset=DatasetRef(
            id="geoboundaries_zaf_adm2",
            version="adm2-2020",
            checksum="abc",
            source_url="https://example.invalid",
            licence="CC BY 3.0 IGO",
        ),
        licence="CC BY 3.0 IGO",
        vintage="2020",
        area_km2=430.0,
    )


def test_weights_use_reported_coordinates(tmp_path: Path) -> None:
    panel = frame()
    panel["lat"] = -29.875
    panel["lon"] = 31.0
    weights = weights_from_frame(panel, municipality(tmp_path), 0.25)

    assert set(weights) == {"cell_coastal", "cell_inland"}
    for weight in weights.values():
        assert 0 < weight.inside_fraction <= 1
        assert weight.area_km2 > 0


def test_cells_that_miss_the_municipality_are_dropped(tmp_path: Path) -> None:
    panel = frame()
    panel.loc[panel["cell_id"] == "cell_inland", "lon"] = 25.0
    weights = weights_from_frame(panel, municipality(tmp_path), 0.25)
    assert set(weights) == {"cell_coastal"}


def test_weights_reject_a_panel_entirely_outside_the_municipality(tmp_path: Path) -> None:
    panel = frame()
    panel["lat"] = -20.0
    panel["lon"] = 20.0
    with pytest.raises(RuntimeError):
        weights_from_frame(panel, municipality(tmp_path), 0.25)


def boundary_rows() -> list[dict]:
    return [
        {
            "boundary_id": "ethekwini",
            "level": "municipality",
            "name": "eThekwini",
            "code": None,
            "parent_id": None,
            "vintage": "2020",
            "dataset_id": "geoboundaries_zaf_adm2",
            "dataset_version": "adm2-2020",
            "crs": "EPSG:4326",
            "area_km2": 430.0,
            "geometry_wkt": box(30.9, -30.0, 31.1, -29.8).wkt,
        },
        {
            "boundary_id": "ethekwini-001",
            "level": "ward",
            "name": "eThekwini 001",
            "code": 1,
            "parent_id": "ethekwini",
            "vintage": "2020",
            "dataset_id": "geoboundaries_zaf_adm4",
            "dataset_version": "adm4-2020",
            "crs": "EPSG:4326",
            "area_km2": 430.0,
            "geometry_wkt": box(30.9, -30.0, 31.1, -29.8).wkt,
        },
    ]


def crosswalk_rows() -> list[dict]:
    return [
        {
            "ward_id": "ethekwini-001",
            "vintage": "2020",
            "ward_name": "eThekwini 001",
            "ward_number": 1,
            "municipality_id": "ethekwini",
            "municipality_name": "eThekwini",
            "inside_fraction": 0.9997,
            "area_km2": 430.0,
        }
    ]


def test_boundaries_roundtrip_by_level(engine) -> None:
    repository.replace_boundaries(engine, boundary_rows())

    municipality_rows = repository.fetch_boundaries(engine, level="municipality")
    ward_rows = repository.fetch_boundaries(engine, level="ward")

    assert [row["boundary_id"] for row in municipality_rows] == ["ethekwini"]
    assert [row["boundary_id"] for row in ward_rows] == ["ethekwini-001"]
    assert ward_rows[0]["parent_id"] == "ethekwini"
    assert ward_rows[0]["geometry_wkt"].startswith("POLYGON")


def test_boundary_rebuild_is_idempotent(engine) -> None:
    repository.replace_boundaries(engine, boundary_rows())
    repository.replace_boundaries(engine, boundary_rows())
    assert len(repository.fetch_boundaries(engine)) == 2


def test_a_new_boundary_vintage_replaces_the_old_rows(engine) -> None:
    repository.replace_boundaries(engine, boundary_rows())
    refreshed = [
        {**row, "vintage": "2021", "dataset_version": "adm4-2021"}
        if row["level"] == "ward"
        else row
        for row in boundary_rows()
    ]
    repository.replace_boundaries(engine, refreshed)

    rows = repository.fetch_boundaries(engine)
    assert len(rows) == 2, "one active version per boundary, not one per vintage"
    assert {row["vintage"] for row in rows if row["level"] == "ward"} == {"2021"}


def test_crosswalk_roundtrip_filters_by_municipality(engine) -> None:
    repository.replace_crosswalk(engine, crosswalk_rows(), vintage="2020")

    rows = repository.fetch_crosswalk(engine, municipality_id="ethekwini")
    assert len(rows) == 1
    assert rows[0]["ward_number"] == 1
    assert rows[0]["inside_fraction"] == pytest.approx(0.9997)

    assert repository.fetch_crosswalk(engine, municipality_id="other") == []


def test_empty_boundary_write_is_a_noop(engine) -> None:
    assert repository.replace_boundaries(engine, []) == 0
    assert repository.replace_crosswalk(engine, [], vintage="2020") == 0
    assert repository.fetch_boundaries(engine) == []
