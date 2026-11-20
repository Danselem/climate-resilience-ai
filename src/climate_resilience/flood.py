"""Flood exposure build.

Publishes two indicators per ward (and the municipality), per mechanism and per
return period. Riverine and coastal are separate rows and are never summed.

The pluvial caveat is not a note in the documentation: it is attached to every
row, because a reader who takes a riverine depth for a general flood risk
assessment has been misled by us, not by the source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
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
from .exposure import WardGeometry, ward_dataset, wards_from_store
from .indicators import IndicatorSpec
from .indicators import get as get_indicator
from .indicators.flood import MIN_MEANINGFUL_FRACTION, FloodExposure, compute_flood_exposure
from .ingestion.aqueduct import RESOLUTION, dataset_from_pointer, resolve_flood_path
from .ingestion.boundaries import Municipality
from .ingestion.worldpop import dataset_from_pointer as worldpop_dataset_from_pointer
from .ingestion.worldpop import resolve_worldpop_path
from .manifest import RunManifest, RunRecorder, content_hash
from .mart.build import to_row
from .pipeline import load_or_fetch_municipality
from .store import repository

AREA_INDICATOR = "flood_exposed_area_pct"
POPULATION_INDICATOR = "flood_exposed_population"

DEFAULT_THRESHOLD_M = 0.0

# The Aqueduct baseline is EUWATCH forcing over 1960-1999 (Technical Note,
# A.1.1). It is not a single event and not a recent window.
BASELINE_START = date(1960, 1, 1)
BASELINE_END = date(1999, 12, 31)

FLOOD_WARNINGS = [
    "riverine and coastal flooding only; pluvial (surface-water) flooding is not "
    "modelled and is excluded by design (I9)",
    "~1 km hazard grid: ward-scale statistics, not street-level or property-level prediction",
    "baseline represents current conditions forced by EUWATCH over 1960-1999; it is "
    "not a recent period and not a single observed event",
    "the source model excludes flood defences, weirs and sluices, and does not capture "
    "flash floods well",
    "50-year and longer return periods carry considerable uncertainty in the source's "
    "extreme-value analysis",
]

THRESHOLD_WARNING = (
    "no cell in eThekwini exceeds 0.5 m at any return period, so exposure is published "
    "at any modelled inundation (threshold 0.0 m) rather than the 0.5 m default; see ADR-010"
)

POPULATION_WARNING = (
    "population is interpolated onto the wet part of each 1 km cell; at this resolution "
    "the figure is an upper bound on people in water"
)

COASTAL_NULL_WARNING = (
    "Aqueduct v2 models no coastal inundation for eThekwini at this return period; the "
    "same raster inundates Maputo Bay, and JICA's 2025 Durban flood survey also rates "
    "coastal storm surge risk as currently low, so this is a model result rather than a "
    "missing download. It does not mean the coast cannot flood"
)

DEPTH_QUANTISATION_WARNING = (
    "depth is near-binary: the wet cells carry only a handful of distinct values "
    "because the hydrological model is 5' (~10 km) and the 1 km raster only "
    "partitions its water level over the terrain; treat this as modelled extent "
    "with coarse depth classes, not a continuous depth field"
)

COASTAL_WINDOW_WARNING = (
    "the release publishes no separate coastal baseline window; this row uses the "
    "riverine baseline window 1960-1999"
)

SLIVER_WARNING = (
    "exposed area is below 0.1% of the scope, smaller than the hazard grid can resolve"
)


@dataclass(frozen=True)
class FloodSummary:
    run_id: str
    rows: int
    area_rows: int
    population_rows: int
    withheld: tuple[str, ...]
    content_hash: str
    snapshot_paths: tuple[Path, ...]
    manifest: RunManifest


@dataclass(frozen=True)
class _Scope:
    """The municipality presented as a ward-shaped scope."""

    ward_id: str
    geometry: BaseGeometry


def build_flood(
    settings: Settings,
    *,
    threshold_m: float = DEFAULT_THRESHOLD_M,
    flood_path: Path | None = None,
    flood_dataset: DatasetRef | None = None,
    wards: list[WardGeometry] | None = None,
    municipality: Municipality | None = None,
) -> FloodSummary:
    area_spec = get_indicator(AREA_INDICATOR)
    population_spec = get_indicator(POPULATION_INDICATOR)

    grid_path = flood_path or resolve_flood_path(settings)
    population_path = resolve_worldpop_path(settings)
    grid = pd.read_parquet(grid_path)
    population = pd.read_parquet(population_path)

    dataset = flood_dataset or dataset_from_pointer(settings)
    population_dataset = worldpop_dataset_from_pointer(settings)
    wards = wards if wards is not None else wards_from_store(settings)
    if not wards:
        raise RuntimeError("no ward boundaries available; run the wards stage first")
    metro = municipality or load_or_fetch_municipality(settings)

    results = compute_flood_exposure(
        grid,
        [*wards, _Scope(ward_id="ethekwini", geometry=metro.geometry)],
        population,
        threshold_m=threshold_m,
    )

    recorder = RunRecorder(
        "build_flood",
        manifest_dir=settings.manifest_dir,
        parameters={
            "indicator_ids": [AREA_INDICATOR, POPULATION_INDICATOR],
            "flood_version": dataset.version,
            "depth_threshold_m": threshold_m,
            "municipality": settings.municipality,
        },
    )
    recorder.add_input(grid_path)
    recorder.add_input(population_path)
    ward_path = _ward_file(settings, wards[0].dataset_version)
    if ward_path.exists():
        recorder.add_input(ward_path)

    run = RunRef(
        git_commit=recorder.commit,
        run_id=recorder.run_id,
        created_at=now_utc(),
        inputs_hash=recorder.inputs_hash,
    )

    period = Period(start=BASELINE_START, end=BASELINE_END, basis="modelled_estimate")
    names = {ward.ward_id: ward.ward_name for ward in wards}
    names["ethekwini"] = settings.municipality

    depth_notes = _depth_quantisation_notes(grid)
    area_rows: list[dict[str, object]] = []
    population_rows: list[dict[str, object]] = []
    withheld: list[str] = []
    for result in results:
        if result.coverage_pct <= 0:
            # No hazard data over this scope. Publishing 0.0 would claim "not
            # exposed" when the truth is "not modelled here", so the row is
            # withheld and recorded (I8).
            withheld.append(
                f"{result.scope_id}/{result.mechanism}/rp{result.return_period_years}"
            )
            continue
        scope_level = "municipality" if result.scope_id == "ethekwini" else "ward"
        scope = Scope(level=scope_level, id=result.scope_id, name=names[result.scope_id])
        warnings = _warnings(
            result,
            threshold_m,
            scope_level,
            depth_notes.get((result.mechanism, result.return_period_years)),
        )

        area_rows.append(
            _row(
                value=result.area_fraction_pct,
                spec=area_spec,
                scope=scope,
                period=period,
                result=result,
                warnings=warnings,
                datasets=[dataset, ward_dataset(wards[0])],
                run=run,
                threshold_m=threshold_m,
            )
        )
        population_rows.append(
            _row(
                value=result.exposed_population,
                spec=population_spec,
                scope=scope,
                period=period,
                result=result,
                warnings=[*warnings, POPULATION_WARNING],
                datasets=[dataset, population_dataset, ward_dataset(wards[0])],
                run=run,
                threshold_m=threshold_m,
            )
        )

    snapshot_paths: list[Path] = []
    for spec, rows in ((area_spec, area_rows), (population_spec, population_rows)):
        snapshot_paths.append(
            _persist(settings, spec, rows, run, recorder, withheld)
        )

    return FloodSummary(
        run_id=run.run_id,
        rows=len(area_rows) + len(population_rows),
        area_rows=len(area_rows),
        population_rows=len(population_rows),
        withheld=tuple(withheld),
        content_hash=content_hash([*area_rows, *population_rows]),
        snapshot_paths=tuple(snapshot_paths),
        manifest=recorder.finish(),
    )


def _depth_quantisation_notes(grid: pd.DataFrame) -> dict[tuple[str, int], str]:
    """Flag a depth field that is a mask in disguise, one layer at a time.

    The source's riverine depth comes from a 5' hydrological model. When almost
    every wet cell in a layer shares one of two values, a depth threshold is not
    measuring depth; saying so is part of publishing the number.
    """
    notes: dict[tuple[str, int], str] = {}
    for (mechanism, return_period), layer in grid.groupby(
        ["mechanism", "return_period_years"], sort=True
    ):
        wet = layer[layer["depth_m"] > 0]
        if wet.empty:
            continue
        counts = wet["depth_m"].value_counts()
        if len(counts) > 10:
            continue
        top = counts.head(2) if len(counts) >= 2 else counts
        share = float(top.sum()) / float(len(wet))
        if share < 0.9:
            continue
        notes[(str(mechanism), int(return_period))] = (
            f"{share:.0%} of wet cells carry one of {len(top)} depth values in this "
            f"layer ({', '.join(f'{value:.3f} m' for value in top.index)}). "
            + DEPTH_QUANTISATION_WARNING
        )
    return notes


def _warnings(
    result: FloodExposure,
    threshold_m: float,
    scope_level: str,
    depth_note: str | None,
) -> list[str]:
    warnings = [*FLOOD_WARNINGS]
    if depth_note:
        warnings.append(depth_note)
    if threshold_m == 0.0:
        warnings.append(THRESHOLD_WARNING)
    if result.mechanism == "coastal":
        warnings.append(COASTAL_WINDOW_WARNING)
        if result.max_depth_m <= 0:
            warnings.append(COASTAL_NULL_WARNING)
    fraction = result.area_fraction_pct / 100.0
    if 0 < fraction < MIN_MEANINGFUL_FRACTION:
        warnings.append(SLIVER_WARNING)
    if result.coverage_pct < 90:
        warnings.append(
            f"hazard data covers {result.coverage_pct:.1f}% of the scope; the remainder is "
            "nodata (the source marks sea and outside-land cells as nodata)"
        )
    if scope_level == "municipality":
        warnings.append(
            "municipality value is computed on the municipal polygon, not by summing wards"
        )
    return warnings


def _row(
    *,
    value: float,
    spec: IndicatorSpec,
    scope: Scope,
    period: Period,
    result: FloodExposure,
    warnings: list[str],
    datasets: list[DatasetRef],
    run: RunRef,
    threshold_m: float,
) -> dict[str, object]:
    envelope = EvidenceEnvelope(
        value=round(float(value), 3),
        unit=spec.unit,
        indicator_id=spec.indicator_id,
        method_id=spec.method_id,
        method_version=spec.method_version,
        hazard_type="flood",
        return_period_years=result.return_period_years,
        depth_threshold_m=threshold_m,
        mechanism=result.mechanism,  # type: ignore[arg-type]
        scope=scope,
        period=period,
        datasets=datasets,
        quality=Quality(
            n_samples=result.wet_cells,
            coverage_pct=result.coverage_pct,
            missing_pct=round(100.0 - result.coverage_pct, 2),
            native_resolution=RESOLUTION,
            warnings=warnings,
        ),
        run=run,
    )
    return to_row(envelope)


def _persist(
    settings: Settings,
    spec: IndicatorSpec,
    rows: list[dict[str, object]],
    run: RunRef,
    recorder: RunRecorder,
    withheld: list[str],
) -> Path:
    digest = content_hash(rows)
    snapshot_path = settings.processed_dir / "mart" / (
        f"{spec.indicator_id}-v{spec.method_version}.json"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "content_hash": digest,
                "run_id": run.run_id,
                "indicator_id": spec.indicator_id,
                "method_version": spec.method_version,
                "withheld": withheld,
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
        indicator_id=spec.indicator_id,
        method_version=spec.method_version,
    )
    return snapshot_path


def _ward_file(settings: Settings, version: str) -> Path:
    return (
        settings.processed_dir
        / "geoboundaries_zaf_adm4"
        / version
        / "ethekwini-wards.geojson"
    )
