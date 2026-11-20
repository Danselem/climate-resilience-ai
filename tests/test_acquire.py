"""One-command acquisition: order, isolation, failure policy and offline mode."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from climate_resilience.acquire import DataReport, run_data, verify_artifacts
from climate_resilience.config import Settings
from climate_resilience.manifest import sha256_file


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/mart.db",
    )


def write_catalogue(
    tmp_path: Path,
    entries: list[dict],
) -> Path:
    path = tmp_path / "datasets.json"
    path.write_text(json.dumps({"version": 1, "datasets": entries}), encoding="utf-8")
    return path


def entry(
    dataset_id: str,
    *,
    required: bool = True,
    artifact: str | None = None,
    checksum: str | None = None,
    status: str = "active",
) -> dict:
    return {
        "id": dataset_id,
        "name": dataset_id,
        "role": "test",
        "source_url": "https://example.invalid",
        "licence": "CC BY 4.0",
        "version": "v1",
        "checksum": checksum,
        "basis": "observation",
        "units": "n/a",
        "crs": "EPSG:4326",
        "native_resolution": "vector",
        "spatial_coverage": "test",
        "temporal_coverage": "test",
        "time_basis": "n/a",
        "status": status,
        "retrieved_at": "2026-01-01",
        "artifact": artifact,
        "required": required,
        "known_gaps": ["test"],
    }


def make_artifact(settings: Settings, relative: str) -> str:
    path = settings.data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("payload", encoding="utf-8")
    return sha256_file(path)


def fake_builder(rows: int = 10):
    def build(_: Settings) -> SimpleNamespace:
        return SimpleNamespace(rows=rows, content_hash="hash")

    return build


def test_required_sources_run_in_dependency_order(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    checksums = {
        "geoboundaries_zaf_adm2": make_artifact(settings, "raw/adm2.geojson"),
        "geoboundaries_zaf_adm4": make_artifact(settings, "raw/adm4.geojson"),
        "era5_openmeteo": make_artifact(settings, "processed/tmax.parquet"),
    }
    artifacts = {
        "geoboundaries_zaf_adm2": "raw/adm2.geojson",
        "geoboundaries_zaf_adm4": "raw/adm4.geojson",
        "era5_openmeteo": "processed/tmax.parquet",
    }
    # Deliberately listed out of order in the catalogue.
    catalogue = write_catalogue(
        tmp_path,
        [
            entry("era5_openmeteo", artifact=artifacts["era5_openmeteo"],
                  checksum=checksums["era5_openmeteo"]),
            entry("geoboundaries_zaf_adm4", artifact=artifacts["geoboundaries_zaf_adm4"],
                  checksum=checksums["geoboundaries_zaf_adm4"]),
            entry("geoboundaries_zaf_adm2", artifact=artifacts["geoboundaries_zaf_adm2"],
                  checksum=checksums["geoboundaries_zaf_adm2"]),
        ],
    )

    calls: list[str] = []

    def runner(name: str):
        def run(_: Settings) -> str:
            calls.append(name)
            return f"{name} done"

        return run

    report = run_data(
        settings,
        catalogue_path=catalogue,
        runners={"boundaries": runner("boundaries"), "wards": runner("wards"),
                 "climate": runner("climate")},
        builder=fake_builder(),
    )

    assert calls == ["boundaries", "wards", "climate"]
    assert [s.dataset_id for s in report.sources] == [
        "geoboundaries_zaf_adm2",
        "geoboundaries_zaf_adm4",
        "era5_openmeteo",
    ]
    assert report.ok
    assert report.build.status == "ok"


def test_optional_failure_is_recorded_as_skipped(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    catalogue = write_catalogue(
        tmp_path,
        [entry("geoboundaries_zaf_adm2", required=False, artifact="raw/adm2.geojson",
               checksum="x")],
    )

    def boom(_: Settings) -> str:
        raise RuntimeError("source down")

    report = run_data(
        settings,
        catalogue_path=catalogue,
        runners={"boundaries": boom},
        builder=fake_builder(),
    )

    assert report.sources[0].status == "skipped"
    assert "site down" in report.sources[0].detail or "source down" in report.sources[0].detail
    assert report.ok, "an optional source must not fail the run"


def test_required_failure_fails_the_run_and_skips_the_build(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    catalogue = write_catalogue(
        tmp_path,
        [entry("geoboundaries_zaf_adm2", required=True, artifact="raw/adm2.geojson",
               checksum="x")],
    )

    def boom(_: Settings) -> str:
        raise RuntimeError("source down")

    report = run_data(
        settings,
        catalogue_path=catalogue,
        runners={"boundaries": boom},
        builder=fake_builder(),
    )

    assert report.sources[0].status == "failed"
    assert report.build.status == "skipped"
    assert not report.ok
    assert [s.dataset_id for s in report.failed_required] == ["geoboundaries_zaf_adm2"]


def test_artifact_mismatch_after_a_successful_runner_is_a_failure(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    make_artifact(settings, "raw/adm2.geojson")
    catalogue = write_catalogue(
        tmp_path,
        [entry("geoboundaries_zaf_adm2", artifact="raw/adm2.geojson", checksum="0" * 64)],
    )

    report = run_data(
        settings,
        catalogue_path=catalogue,
        runners={"boundaries": lambda _: "done"},
        builder=fake_builder(),
    )

    assert report.sources[0].status == "failed"
    assert "checksum mismatch" in report.sources[0].detail


def test_offline_mode_verifies_cache_and_does_not_call_runners(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    checksum = make_artifact(settings, "raw/adm2.geojson")
    catalogue = write_catalogue(
        tmp_path,
        [entry("geoboundaries_zaf_adm2", artifact="raw/adm2.geojson", checksum=checksum)],
    )

    def must_not_run(_: Settings) -> str:
        raise AssertionError("offline mode performed a network fetch")

    report = run_data(
        settings,
        offline=True,
        catalogue_path=catalogue,
        runners={"boundaries": must_not_run},
        builder=fake_builder(),
    )

    assert report.offline
    assert report.sources[0].status == "ok"
    assert report.build.status == "skipped"
    assert report.ok


def test_offline_mode_fails_when_a_required_artifact_is_missing(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    catalogue = write_catalogue(
        tmp_path,
        [entry("geoboundaries_zaf_adm2", artifact="raw/absent.geojson",
               checksum="0" * 64)],
    )

    report = run_data(settings, offline=True, catalogue_path=catalogue,
                      builder=fake_builder())

    assert report.sources[0].status == "failed"
    assert "missing" in report.sources[0].detail
    assert not report.ok


def test_offline_mode_detects_a_changed_artifact(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    checksum = make_artifact(settings, "raw/adm2.geojson")
    catalogue = write_catalogue(
        tmp_path,
        [entry("geoboundaries_zaf_adm2", artifact="raw/adm2.geojson", checksum=checksum)],
    )
    (settings.data_dir / "raw/adm2.geojson").write_text("tampered", encoding="utf-8")

    report = run_data(settings, offline=True, catalogue_path=catalogue,
                      builder=fake_builder())

    assert report.sources[0].status == "failed"
    assert "checksum mismatch" in report.sources[0].detail


def test_a_required_dataset_without_an_adapter_fails(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    catalogue = write_catalogue(
        tmp_path,
        [entry("census_2022", required=True, artifact="raw/census.csv", checksum="0" * 64)],
    )

    report = run_data(settings, catalogue_path=catalogue, builder=fake_builder())

    unmapped = [s for s in report.sources if s.dataset_id == "census_2022"]
    assert unmapped and unmapped[0].status == "failed"
    assert "no acquisition stage" in unmapped[0].detail
    assert not report.ok


def test_report_is_written_and_can_be_read_back(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    checksum = make_artifact(settings, "raw/adm2.geojson")
    catalogue = write_catalogue(
        tmp_path,
        [entry("geoboundaries_zaf_adm2", artifact="raw/adm2.geojson", checksum=checksum)],
    )

    report = run_data(settings, catalogue_path=catalogue,
                      runners={"boundaries": lambda _: "done"}, builder=fake_builder())
    written = settings.manifest_dir / f"data-{report.run_id}.json"

    assert written.exists()
    restored = DataReport.model_validate_json(written.read_text(encoding="utf-8"))
    assert restored.run_id == report.run_id
    assert restored.sources[0].status == "ok"


def test_invalid_catalogue_is_refused_before_any_fetch(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    catalogue = write_catalogue(
        tmp_path, [entry("geoboundaries_zaf_adm2", required=False, artifact=None)]
    )

    with pytest.raises(ValueError, match="catalogue is invalid"):
        run_data(settings, catalogue_path=catalogue, builder=fake_builder())


def test_verify_artifacts_reports_missing_and_mismatched(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    checksum = make_artifact(settings, "raw/ok.geojson")
    catalogue = write_catalogue(
        tmp_path,
        [
            entry("geoboundaries_zaf_adm2", artifact="raw/ok.geojson", checksum=checksum),
            entry("geoboundaries_zaf_adm4", artifact="raw/absent.geojson",
                  checksum="0" * 64),
        ],
    )

    problems = verify_artifacts(settings, catalogue_path=catalogue)

    assert [dataset for dataset, _ in problems] == ["geoboundaries_zaf_adm4"]


def test_a_missing_catalogue_explains_how_to_restore_it(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)

    with pytest.raises(ValueError, match="git checkout -- data/catalogue"):
        run_data(settings, catalogue_path=tmp_path / "absent.json", builder=fake_builder())
