"""Phase 1 pipeline: boundaries -> climate -> canonical -> mart.

Each stage is runnable on its own and records a manifest. Nothing here is
reachable over HTTP: batch work stays batch work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings
from .crosswalk import build_crosswalk
from .envelope import RunRef, now_utc
from .indicators import get as get_indicator
from .ingestion.boundaries import Municipality, fetch_municipality, fetch_wards
from .ingestion.climate import ClimateExtract, fetch_daily_tmax
from .manifest import RunManifest, RunRecorder, content_hash, sha256_file
from .mart.build import CellWeight, build_cell_rows, build_municipality_rows
from .spatial import STORAGE_CRS, Cell, area_km2, cells_covering, intersection_fraction
from .spatial_validation import LayerReport, check_layer, repair
from .spot_checks import SpotResult, check_points
from .store import repository
from .store.models import indicator_value

CLIMATE_SOURCE = "era5_openmeteo"


@dataclass(frozen=True)
class BoundarySummary:
    run_id: str
    ward_count: int
    report: LayerReport
    spot_results: list[SpotResult]
    report_path: Path
    manifest: RunManifest
    municipality: Municipality
    vintage: str
    crosswalk_rows: int


@dataclass(frozen=True)
class BuildSummary:
    run_id: str
    rows: int
    content_hash: str
    snapshot_path: Path
    manifest: RunManifest
    municipality: Municipality


def load_or_fetch_municipality(settings: Settings) -> Municipality:
    return fetch_municipality(settings, settings.municipality)


def plan_cells(municipality: Municipality, cell_deg: float) -> list[CellWeight]:
    """Cells that intersect the municipality, with the weights used later."""
    weights: list[CellWeight] = []
    for cell in cells_covering(municipality.geometry, cell_deg):
        fraction, area = intersection_fraction(cell.polygon(), municipality.geometry)
        if fraction > 0:
            weights.append(
                CellWeight(cell=cell, inside_fraction=round(fraction, 6), area_km2=round(area, 6))
            )
    if not weights:
        raise RuntimeError("no ERA5 cells intersect the municipality boundary")
    return weights


def weights_from_frame(
    frame: pd.DataFrame, municipality: Municipality, cell_deg: float
) -> dict[str, CellWeight]:
    """Area weights for the grid points actually returned by the source.

    The source may snap a request to a nearby grid point, so geometry follows
    the reported coordinate rather than the requested one.
    """
    weights: dict[str, CellWeight] = {}
    unique = frame[["cell_id", "lat", "lon"]].drop_duplicates(subset=["cell_id"])
    for record in unique.itertuples(index=False):
        cell = Cell(
            cell_id=str(record.cell_id),
            lat=float(record.lat),
            lon=float(record.lon),
            size_deg=cell_deg,
        )
        fraction, area = intersection_fraction(cell.polygon(), municipality.geometry)
        if fraction > 0:
            weights[cell.cell_id] = CellWeight(
                cell=cell, inside_fraction=round(fraction, 6), area_km2=round(area, 6)
            )
    if not weights:
        raise RuntimeError("no grid cells intersect the municipality boundary")
    return weights


def fetch_climate(
    settings: Settings, weights: list[CellWeight], *, version: str | None = None
) -> ClimateExtract:
    version = version or f"archive-{settings.history_start}_{settings.history_end}"
    extract = fetch_daily_tmax(
        settings,
        [w.cell for w in weights],
        start=settings.history_start,
        end=settings.history_end,
        version=version,
    )
    write_climate_pointer(settings, version=version, path=extract.processed_path)
    return extract


def climate_version_dir(settings: Settings, version: str) -> Path:
    return settings.processed_dir / CLIMATE_SOURCE / version


def write_climate_pointer(settings: Settings, *, version: str, path: Path) -> Path:
    """Record which climate version is current.

    The pointer exists so a downstream stage never has to guess between
    versions by sorting directory names. It stores the version (portable) and
    the artifact hash (so a rewritten parquet is detected, not silently used).
    """
    target = settings.processed_dir / CLIMATE_SOURCE / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "artifact": f"{CLIMATE_SOURCE}/{version}/daily_tmax.parquet",
        "sha256": sha256_file(path),
        "written_at": now_utc().isoformat(),
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def resolve_climate_path(settings: Settings, *, version: str | None = None) -> Path:
    """Locate the canonical climate parquet: explicit version, else the pointer.

    Never globs for a candidate. Choosing an input by lexicographic directory
    order is how a pipeline silently uses yesterday's data.
    """
    if version is not None:
        path = climate_version_dir(settings, version) / "daily_tmax.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"climate version {version!r} not found at {path}; "
                "run `climate-resilience climate` first or omit --climate-version"
            )
        return path

    pointer = settings.processed_dir / CLIMATE_SOURCE / "latest.json"
    if not pointer.exists():
        raise FileNotFoundError(
            f"no climate pointer at {pointer}; run `climate-resilience climate` "
            "(or `climate-resilience data`) before building the mart"
        )

    payload = json.loads(pointer.read_text(encoding="utf-8"))
    path = settings.processed_dir / str(payload["artifact"])
    if not path.exists():
        raise FileNotFoundError(
            f"climate pointer refers to a missing artifact: {path}; re-run the climate stage"
        )
    recorded = str(payload.get("sha256", ""))
    actual = sha256_file(path)
    if recorded and recorded != actual:
        raise RuntimeError(
            f"climate parquet {path} changed since the pointer was written "
            f"({recorded[:12]}… -> {actual[:12]}…); re-run the climate stage"
        )
    return path


def build_mart(
    settings: Settings,
    *,
    indicator_id: str = "hot_days_tmax_ge_35c",
    threshold: float | None = None,
    climate_version: str | None = None,
) -> BuildSummary:
    spec = get_indicator(indicator_id)
    threshold = spec.default_threshold if threshold is None else threshold
    if threshold is None:
        raise ValueError(f"indicator {indicator_id} requires an explicit threshold")

    municipality = load_or_fetch_municipality(settings)

    climate_path = resolve_climate_path(settings, version=climate_version)
    frame = pd.read_parquet(climate_path)
    weight_index = weights_from_frame(frame, municipality, settings.era5_cell_deg)

    recorder = RunRecorder(
        "build_mart",
        manifest_dir=settings.manifest_dir,
        parameters={
            "indicator_id": indicator_id,
            "threshold_c": threshold,
            "min_coverage": settings.min_coverage,
            "cell_deg": settings.era5_cell_deg,
            "municipality": settings.municipality,
            "climate_version": climate_path.parent.name,
        },
    )
    recorder.add_input(climate_path)
    recorder.add_input(municipality.feature_path)

    run = RunRef(
        git_commit=recorder.commit,
        run_id=recorder.run_id,
        created_at=now_utc(),
        inputs_hash=recorder.inputs_hash,
    )
    datasets = [municipality.dataset, _climate_dataset_ref(climate_path, frame)]

    cell_rows = build_cell_rows(
        frame,
        spec=spec,
        threshold=float(threshold),
        weights=weight_index,
        datasets=datasets,
        run=run,
        min_coverage=settings.min_coverage,
        cell_deg=settings.era5_cell_deg,
    )
    metro_rows = build_municipality_rows(
        cell_rows,
        spec=spec,
        weights=weight_index,
        municipality_name=settings.municipality,
        datasets=datasets,
        run=run,
        cell_deg=settings.era5_cell_deg,
        years_total=len(weight_index),
    )
    rows = cell_rows + metro_rows
    if not rows:
        raise RuntimeError("no publishable rows: every year was withheld for low coverage")

    digest = content_hash(rows)

    snapshot_dir = settings.processed_dir / "mart"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{indicator_id}-v{spec.method_version}.json"
    snapshot = {
        "content_hash": digest,
        "run_id": run.run_id,
        "indicator_id": indicator_id,
        "method_version": spec.method_version,
        "threshold_c": threshold,
        "rows": _jsonable(rows),
    }
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    recorder.add_output(snapshot_path)

    engine = repository.make_engine(settings.database_url)
    repository.ensure_schema(engine)
    repository.replace_build(
        engine,
        rows,
        indicator_id=indicator_id,
        method_version=spec.method_version,
        dataset_version=rows[0]["dataset_version"],
    )

    manifest = recorder.finish()
    return BuildSummary(
        run_id=run.run_id,
        rows=len(rows),
        content_hash=digest,
        snapshot_path=snapshot_path,
        manifest=manifest,
        municipality=municipality,
    )


def build_boundary_layer(settings: Settings) -> BoundarySummary:
    """Ingest, validate, crosswalk and persist the boundary layer.

    Errors block: nothing is written if the ward layer does not reconcile with
    the municipality.
    """
    municipality = load_or_fetch_municipality(settings)
    layer = fetch_wards(settings, settings.municipality)

    wards = {wid: geom for wid, (_, _, geom) in layer.wards.items()}
    report = check_layer(
        wards,
        municipality.geometry,
        expected_count=settings.expected_ward_count,
    )
    if not report.ok:
        raise RuntimeError(
            "boundary layer failed validation: "
            + "; ".join(issue.detail for issue in report.errors)
        )

    cleaned = {wid: repair(geom)[0] for wid, geom in wards.items()}
    ward_meta = {
        wid: (layer.wards[wid][0], layer.wards[wid][1], cleaned[wid]) for wid in cleaned
    }

    crosswalk = build_crosswalk(
        ward_meta,
        {settings.municipality: (settings.municipality, municipality.geometry)},
        vintage=layer.vintage,
    )
    split = [row for row in crosswalk if row.inside_fraction < 0.99]
    if split:
        raise RuntimeError(
            f"{len(split)} ward(s) are not fully contained in the municipality; "
            "refusing to crosswalk"
        )

    spot_results, spot_issues = check_points(
        {wid: (name, geom) for wid, (name, _, geom) in ward_meta.items()},
        municipality.geometry,
    )
    if spot_issues:
        raise RuntimeError(
            "boundary layer failed spot checks: "
            + "; ".join(issue.detail for issue in spot_issues)
        )

    recorder = RunRecorder(
        "build_boundaries",
        manifest_dir=settings.manifest_dir,
        parameters={
            "municipality": settings.municipality,
            "ward_vintage": layer.vintage,
            "expected_ward_count": settings.expected_ward_count,
        },
    )
    recorder.add_input(municipality.feature_path)
    recorder.add_input(layer.path)

    rows: list[dict[str, Any]] = [
        {
            "boundary_id": settings.municipality,
            "level": "municipality",
            "name": settings.municipality,
            "code": None,
            "parent_id": None,
            "vintage": municipality.vintage,
            "dataset_id": municipality.dataset.id,
            "dataset_version": municipality.dataset.version,
            "crs": STORAGE_CRS,
            "area_km2": round(municipality.area_km2, 4),
            "geometry_wkt": municipality.geometry.wkt,
        }
    ]
    rows += [
        {
            "boundary_id": wid,
            "level": "ward",
            "name": name,
            "code": number,
            "parent_id": settings.municipality,
            "vintage": layer.vintage,
            "dataset_id": layer.dataset.id,
            "dataset_version": layer.dataset.version,
            "crs": STORAGE_CRS,
            "area_km2": round(area_km2(geom), 4),
            "geometry_wkt": geom.wkt,
        }
        for wid, (name, number, geom) in sorted(ward_meta.items())
    ]

    engine = repository.make_engine(settings.database_url)
    repository.ensure_schema(engine)
    repository.replace_boundaries(engine, rows)
    repository.replace_crosswalk(
        engine,
        [
            {
                "ward_id": row.ward_id,
                "vintage": row.vintage,
                "ward_name": row.ward_name,
                "ward_number": row.ward_number,
                "municipality_id": row.municipality_id,
                "municipality_name": row.municipality_name,
                "inside_fraction": row.inside_fraction,
                "area_km2": row.area_km2,
            }
            for row in crosswalk
        ],
        vintage=layer.vintage,
    )

    report_dir = settings.processed_dir / "boundaries"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ward-validation-{layer.vintage}.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": recorder.run_id,
                "vintage": layer.vintage,
                "ward_count": report.count,
                "total_ward_area_km2": round(report.total_area_km2, 4),
                "municipality_area_km2": round(municipality.area_km2, 4),
                "repaired": report.repaired,
                "issues": [issue.__dict__ for issue in report.issues],
                "spot_checks": [result.__dict__ for result in spot_results],
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    recorder.add_output(report_path)
    manifest = recorder.finish()

    return BoundarySummary(
        run_id=recorder.run_id,
        ward_count=report.count,
        report=report,
        spot_results=spot_results,
        report_path=report_path,
        manifest=manifest,
        municipality=municipality,
        vintage=layer.vintage,
        crosswalk_rows=len(crosswalk),
    )


def _climate_dataset_ref(path: Path, frame: pd.DataFrame) -> Any:
    from .envelope import DatasetRef

    version = path.parent.name
    return DatasetRef(
        id="era5_openmeteo",
        version=version,
        checksum=sha256_file(path),
        source_url="https://archive-api.open-meteo.com/v1/archive",
        licence="CC BY 4.0 (Open-Meteo); underlying reanalysis: Copernicus ERA5",
    )


def _jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({k: (str(v) if v is not None else None) for k, v in row.items()})
    return out


def schema_columns() -> set[str]:
    return {column.name for column in indicator_value.columns}
