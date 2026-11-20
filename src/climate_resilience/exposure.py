"""Exposure indicators from WorldPop.

Exposure is not risk. These rows answer "where do people live", not "what are
they exposed to". They carry ``hazard_type = 'none'`` and must be combined with
a hazard in a separate, explicit calculation.

The exposure surface is a 1 km dasymetric grid, allocated to wards by area
share. The ward geometry is the validated ADM4 layer; the Census 2022 ward
table is deliberately not joined, because its 111 ward codes do not match the
110 ADM4 polygons (see ``docs/limitations.md``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import shapely
from shapely import wkt
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from .config import Settings
from .envelope import (
    DatasetRef,
    EvidenceEnvelope,
    Period,
    Quality,
    RunRef,
    Scope,
    now_utc,
)
from .indicators import IndicatorSpec
from .indicators import get as get_indicator
from .ingestion.worldpop import RESOLUTION, resolve_worldpop_path
from .manifest import RunManifest, RunRecorder, content_hash, sha256_file
from .mart.build import to_row
from .spatial import project
from .store import repository

INDICATOR_ID = "population_count_worldpop"

EXPOSURE_WARNINGS = [
    "WorldPop 2020 is two years before Census 2022; this is a modelled exposure "
    "denominator, not a census count",
    "1 km product used because the 100 m national GeoTIFF does not support spatial "
    "subsetting; see ADR-009",
    "ward geometry is geoBoundaries ADM4, not the MDB release",
    "population is allocated by each cell's area share; boundary cells are split, "
    "not counted at their centre",
]


@dataclass(frozen=True)
class WardGeometry:
    ward_id: str
    ward_name: str
    ward_number: int
    geometry: BaseGeometry
    dataset_id: str = "geoboundaries_zaf_adm4"
    dataset_version: str = "adm4-2020"
    checksum: str = "see catalogue"


@dataclass(frozen=True)
class ExposureSummary:
    run_id: str
    rows: int
    content_hash: str
    snapshot_path: Path
    manifest: RunManifest


def build_exposure(
    settings: Settings,
    *,
    worldpop_path: Path | None = None,
    worldpop_dataset: DatasetRef | None = None,
    wards: list[WardGeometry] | None = None,
) -> ExposureSummary:
    spec = get_indicator(INDICATOR_ID)
    path = worldpop_path or resolve_worldpop_path(settings)
    grid = pd.read_parquet(path)
    _validate_grid(grid)

    dataset = worldpop_dataset or _dataset_from_pointer(settings)
    wards = wards if wards is not None else _wards_from_store(settings)
    if not wards:
        raise RuntimeError("no ward boundaries available; run the wards stage first")

    allocations, counts = allocate_to_wards(grid, wards)
    municipal_total = float(grid["population"].sum())

    recorder = RunRecorder(
        "build_exposure",
        manifest_dir=settings.manifest_dir,
        parameters={
            "indicator_id": INDICATOR_ID,
            "worldpop_version": dataset.version,
            "municipality": settings.municipality,
        },
    )
    recorder.add_input(path)
    ward_path = _ward_file(settings, wards[0].dataset_version)
    if ward_path.exists():
        recorder.add_input(ward_path)

    run = RunRef(
        git_commit=recorder.commit,
        run_id=recorder.run_id,
        created_at=now_utc(),
        inputs_hash=recorder.inputs_hash,
    )

    rows: list[dict[str, object]] = []
    period = Period(
        start=date(2020, 1, 1), end=date(2020, 12, 31), basis="modelled_estimate"
    )
    for ward in wards:
        value = float(allocations.get(ward.ward_id, 0.0))
        warnings = list(EXPOSURE_WARNINGS)
        if value <= 0:
            warnings.append("no WorldPop population allocated to this ward; check geometry")
        rows.append(
            _row(
                value=value,
                spec=spec,
                scope=Scope(level="ward", id=ward.ward_id, name=ward.ward_name),
                period=period,
                n_samples=counts.get(ward.ward_id, 0),
                warnings=warnings,
                datasets=[dataset, _ward_dataset(ward)],
                run=run,
            )
        )

    rows.append(
        _row(
            value=municipal_total,
            spec=spec,
            scope=Scope(
                level="municipality", id="ethekwini", name=settings.municipality
            ),
            period=period,
            n_samples=len(grid),
            warnings=[
                *EXPOSURE_WARNINGS,
                "municipality total is the clipped 1 km grid, not the Census 2022 count",
            ],
            datasets=[dataset],
            run=run,
        )
    )

    digest = content_hash(rows)
    snapshot_path = settings.processed_dir / "mart" / (
        f"{INDICATOR_ID}-v{spec.method_version}.json"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "content_hash": digest,
                "run_id": run.run_id,
                "indicator_id": INDICATOR_ID,
                "method_version": spec.method_version,
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    recorder.add_output(snapshot_path)

    engine = repository.make_engine(settings.database_url)
    repository.ensure_schema(engine)
    repository.replace_build(
        engine,
        rows,
        indicator_id=INDICATOR_ID,
        method_version=spec.method_version,
    )

    return ExposureSummary(
        run_id=run.run_id,
        rows=len(rows),
        content_hash=digest,
        snapshot_path=snapshot_path,
        manifest=recorder.finish(),
    )


def allocate_to_wards(
    grid: pd.DataFrame, wards: list[WardGeometry]
) -> tuple[dict[str, float], dict[str, int]]:
    """Allocate each 1 km cell's people to wards by intersection-area share.

    ``source_value`` is the whole cell's population, so wards that tile the
    municipality sum back to the municipality total. A cell straddling a ward
    boundary is split; it is not assigned to the ward containing its centre.
    """
    projected = [(ward, project(ward.geometry)) for ward in wards]
    tree = shapely.STRtree([geom for _, geom in projected])
    totals: dict[str, float] = {ward.ward_id: 0.0 for ward in wards}
    counts: dict[str, int] = {ward.ward_id: 0 for ward in wards}

    for record in grid.itertuples(index=False):
        half = float(record.size_deg) / 2
        cell = box(
            float(record.lon) - half,
            float(record.lat) - half,
            float(record.lon) + half,
            float(record.lat) + half,
        )
        cell_proj = project(cell)
        area = cell_proj.area
        if area <= 0:
            continue
        for index in tree.query(cell_proj):
            ward, geom = projected[int(index)]
            overlap = cell_proj.intersection(geom).area
            share = overlap / area
            if share <= 1e-9:
                continue
            totals[ward.ward_id] += float(record.source_value) * share
            counts[ward.ward_id] += 1

    return totals, counts


def _validate_grid(grid: pd.DataFrame) -> None:
    required = {
        "cell_id",
        "lon",
        "lat",
        "population",
        "fraction_inside",
        "source_value",
        "size_deg",
    }
    missing = required - set(grid.columns)
    if missing:
        raise ValueError(f"WorldPop grid missing columns: {sorted(missing)}")
    if grid.empty:
        raise ValueError("WorldPop grid is empty")
    if grid["cell_id"].duplicated().any():
        raise ValueError("WorldPop grid has duplicate cell_id values")
    if float(grid["population"].sum()) <= 0:
        raise ValueError("WorldPop grid has no population")


def _dataset_from_pointer(settings: Settings) -> DatasetRef:
    pointer = settings.processed_dir / "worldpop" / "latest.json"
    if not pointer.exists():
        raise FileNotFoundError(
            f"no WorldPop pointer at {pointer}; run `climate-resilience worldpop` first"
        )
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    return DatasetRef.model_validate(payload["dataset"])


def _wards_from_store(settings: Settings) -> list[WardGeometry]:
    engine = repository.make_engine(settings.database_url)
    repository.ensure_schema(engine)
    rows = repository.fetch_boundaries(engine, level="ward")
    wards: list[WardGeometry] = []
    for row in rows:
        version = str(row["dataset_version"])
        path = _ward_file(settings, version)
        wards.append(
            WardGeometry(
                ward_id=str(row["boundary_id"]),
                ward_name=str(row["name"]),
                ward_number=int(row["code"] or 0),
                geometry=wkt.loads(str(row["geometry_wkt"])),
                dataset_id=str(row["dataset_id"]),
                dataset_version=version,
                checksum=sha256_file(path) if path.exists() else "see catalogue",
            )
        )
    return wards


def _ward_file(settings: Settings, version: str) -> Path:
    return (
        settings.processed_dir
        / "geoboundaries_zaf_adm4"
        / version
        / "ethekwini-wards.geojson"
    )


def _ward_dataset(ward: WardGeometry) -> DatasetRef:
    # The pilot's ward layer is ADM4; a future MDB layer must supply its own
    # source URL and licence rather than inheriting these.
    return DatasetRef(
        id=ward.dataset_id,
        version=ward.dataset_version,
        checksum=ward.checksum,
        source_url="https://www.geoboundaries.org/",
        licence="CC BY 3.0 IGO",
    )


def _row(
    *,
    value: float,
    spec: IndicatorSpec,
    scope: Scope,
    period: Period,
    n_samples: int,
    warnings: list[str],
    datasets: list[DatasetRef],
    run: RunRef,
) -> dict[str, object]:
    envelope = EvidenceEnvelope(
        value=round(value, 1),
        unit=spec.unit,
        indicator_id=spec.indicator_id,
        method_id=spec.method_id,
        method_version=spec.method_version,
        hazard_type="none",
        scope=scope,
        period=period,
        datasets=datasets,
        quality=Quality(
            n_samples=n_samples,
            coverage_pct=100.0,
            missing_pct=0.0,
            native_resolution=RESOLUTION,
            warnings=warnings,
        ),
        run=run,
    )
    return to_row(envelope)
