"""One-command data acquisition and build.

Sources run in dependency order and are isolated: one blocked source does not
abort the rest, because a platform whose only data source is reachable is not a
platform. Every run writes a report recording each source's status, artifact
and checksum, so "it worked" and "it quietly skipped the census" cannot be
confused.

Failure policy is explicit, not implicit: a dataset marked ``required`` in the
catalogue fails the run; an optional one is recorded as skipped.

Offline mode verifies the cached artifacts against their catalogue checksums
and performs no network access. That is what makes the orchestration testable
in CI and usable on a laptop with no connectivity.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import catalogue as catalogue_module
from .config import Settings
from .envelope import now_utc
from .exposure import build_exposure
from .ingestion.census import fetch_census_ward_population
from .ingestion.worldpop import fetch_worldpop
from .manifest import git_commit, package_versions, sha256_file, sha256_obj
from .pipeline import (
    build_boundary_layer,
    build_mart,
    fetch_climate,
    load_or_fetch_municipality,
    plan_cells,
)

Status = Literal["ok", "failed", "skipped"]

# Catalogue dataset id -> stage name. A dataset with no stage has no adapter and
# cannot be acquired yet; if it is required, that is a failure, not a surprise.
STAGE_BY_DATASET: dict[str, str] = {
    "geoboundaries_zaf_adm2": "boundaries",
    "geoboundaries_zaf_adm4": "wards",
    "era5_openmeteo": "climate",
    "worldpop": "worldpop",
    "census_2022_ward_population": "census",
}

# Execution order, not catalogue order: geometry before the grid it weights,
# and everything before the mart.
STAGE_ORDER: tuple[str, ...] = (
    "boundaries",
    "wards",
    "climate",
    "worldpop",
    "census",
)


@dataclass(frozen=True)
class PipelineSummary:
    """Combined result of the heat mart and the exposure build."""

    rows: int
    content_hash: str
    heat_rows: int
    exposure_rows: int


def build_all(settings: Settings) -> PipelineSummary:
    heat = build_mart(settings)
    exposure = build_exposure(settings)
    return PipelineSummary(
        rows=heat.rows + exposure.rows,
        content_hash=sha256_obj(
            {"heat": heat.content_hash, "exposure": exposure.content_hash}
        ),
        heat_rows=heat.rows,
        exposure_rows=exposure.rows,
    )



class SourceResult(BaseModel):
    dataset_id: str
    stage: str
    required: bool
    status: Status
    detail: str
    artifact: str | None = None
    sha256: str | None = None
    seconds: float = 0.0


class BuildResult(BaseModel):
    status: Status
    detail: str
    rows: int | None = None
    content_hash: str | None = None
    seconds: float = 0.0


class DataReport(BaseModel):
    """What one `data` run actually did, per source."""

    run_id: str
    git_commit: str
    offline: bool
    started_at: datetime
    finished_at: datetime
    package_versions: dict[str, str] = Field(default_factory=dict)
    sources: list[SourceResult] = Field(default_factory=list)
    build: BuildResult

    @property
    def failed_required(self) -> list[SourceResult]:
        return [s for s in self.sources if s.required and s.status != "ok"]

    @property
    def ok(self) -> bool:
        return not self.failed_required and self.build.status in ("ok", "skipped")


def _run_boundaries(settings: Settings) -> str:
    municipality = load_or_fetch_municipality(settings)
    return (
        f"{municipality.name}: {municipality.area_km2:,.1f} km², "
        f"vintage {municipality.vintage}"
    )


def _run_wards(settings: Settings) -> str:
    summary = build_boundary_layer(settings)
    return (
        f"{summary.ward_count} wards, {summary.crosswalk_rows} crosswalk rows, "
        f"{len(summary.report.repaired)} repaired"
    )


def _run_climate(settings: Settings) -> str:
    municipality = load_or_fetch_municipality(settings)
    weights = plan_cells(municipality, settings.era5_cell_deg)
    extract = fetch_climate(settings, weights)
    return (
        f"{len(extract.frame):,} rows across {extract.frame['cell_id'].nunique()} cells, "
        f"{extract.frame['date'].min()}..{extract.frame['date'].max()}"
    )


def _run_worldpop(settings: Settings) -> str:
    municipality = load_or_fetch_municipality(settings)
    extract = fetch_worldpop(settings, municipality)
    return (
        f"{len(extract.grid):,} cells, "
        f"{float(extract.grid['population'].sum()):,.0f} persons, "
        "WorldPop 2020 1 km"
    )


def _run_census(settings: Settings) -> str:
    extract = fetch_census_ward_population(settings)
    summary = extract.summary
    return (
        f"{summary['ward_count']} eThekwini wards, "
        f"{float(summary['population_total']):,.0f} persons; "
        "not joined to geometry (census 111 vs boundary 110)"
    )


STAGE_RUNNERS: dict[str, Callable[[Settings], str]] = {
    "boundaries": _run_boundaries,
    "wards": _run_wards,
    "climate": _run_climate,
    "worldpop": _run_worldpop,
    "census": _run_census,
}


def run_data(
    settings: Settings,
    *,
    offline: bool = False,
    catalogue_path: Path | None = None,
    runners: dict[str, Callable[[Settings], str]] | None = None,
    builder: Callable[[Settings], Any] | None = None,
) -> DataReport:
    """Acquire every catalogued source, then build the mart.

    Returns a report rather than raising: the caller decides the exit code, and
    the report is always written, including when a source failed.
    """
    runners = runners or STAGE_RUNNERS
    path = catalogue_path or settings.catalogue_dir / "datasets.json"
    if not path.exists():
        raise ValueError(
            f"no catalogue at {path}. The catalogue is configuration and is tracked "
            "in git; restore it with `git checkout -- data/catalogue` rather than "
            "leaving the pipeline to guess which sources exist."
        )
    catalogue = catalogue_module.load(path)
    problems = catalogue_module.validate(catalogue)
    if problems:
        raise ValueError("catalogue is invalid: " + "; ".join(problems))

    started = now_utc()
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{sha256_obj({'offline': offline})[:8]}"

    sources: list[SourceResult] = []
    entries = {entry.id: entry for entry in catalogue.datasets}

    # Acquisition is catalogue-driven: a stage runs only for a dataset the
    # catalogue actually lists. STAGE_ORDER fixes the dependency order.
    planned = [
        (stage, dataset_id)
        for stage in STAGE_ORDER
        for dataset_id, mapped in STAGE_BY_DATASET.items()
        if mapped == stage and dataset_id in entries
    ]
    for stage, dataset_id in planned:
        sources.append(
            _run_source(settings, entries[dataset_id], stage, runners, offline=offline)
        )

    covered = set(STAGE_BY_DATASET)
    for entry in catalogue.datasets:
        if entry.required and entry.id not in covered:
            sources.append(
                SourceResult(
                    dataset_id=entry.id,
                    stage="unmapped",
                    required=True,
                    status="failed",
                    detail="required dataset has no acquisition stage; add an adapter",
                )
            )

    build = _build(settings, sources, offline=offline, builder=builder or build_all)
    report = DataReport(
        run_id=run_id,
        git_commit=git_commit(),
        offline=offline,
        started_at=started,
        finished_at=now_utc(),
        package_versions=package_versions(),
        sources=sources,
        build=build,
    )
    _write_report(settings, report)
    return report


def _run_source(
    settings: Settings,
    entry: catalogue_module.DatasetEntry,
    stage: str,
    runners: dict[str, Callable[[Settings], str]],
    *,
    offline: bool,
) -> SourceResult:
    artifact = settings.data_dir / entry.artifact if entry.artifact else None
    base = {
        "dataset_id": entry.id,
        "stage": stage,
        "required": entry.required,
        "artifact": entry.artifact,
    }

    if offline:
        detail, sha = _check_artifact(entry, artifact)
        status: Status = "ok" if detail is None else "failed"
        return SourceResult(
            **base,
            status=status,
            detail=detail or "cached artifact matches catalogue checksum",
            sha256=sha,
        )

    runner = runners.get(stage)
    if runner is None:
        return SourceResult(
            **base,
            status="failed" if entry.required else "skipped",
            detail=f"no adapter implemented for stage {stage!r}",
        )

    tick = time.perf_counter()
    try:
        detail = runner(settings)
    except Exception as exc:  # noqa: BLE001 - a source failure must not abort the run
        return SourceResult(
            **base,
            status="failed" if entry.required else "skipped",
            detail=f"{type(exc).__name__}: {exc}",
            seconds=round(time.perf_counter() - tick, 3),
        )
    elapsed = round(time.perf_counter() - tick, 3)

    problem, sha = _check_artifact(entry, artifact)
    if problem is not None:
        return SourceResult(
            **base,
            status="failed" if entry.required else "skipped",
            detail=problem,
            sha256=sha,
            seconds=elapsed,
        )
    return SourceResult(**base, status="ok", detail=detail, sha256=sha, seconds=elapsed)


def _check_artifact(
    entry: catalogue_module.DatasetEntry, path: Path | None
) -> tuple[str | None, str | None]:
    """Compare an artifact against the catalogue. Returns (problem, sha256)."""
    if path is None:
        return "no artifact path declared; cannot verify what was acquired", None
    if not path.exists():
        return f"artifact missing at {path}", None
    actual = sha256_file(path)
    if entry.checksum and actual != entry.checksum:
        return (
            f"artifact checksum mismatch at {path} "
            f"(catalogue {entry.checksum[:12]}…, file {actual[:12]}…)",
            actual,
        )
    return None, actual


def _build(
    settings: Settings,
    sources: list[SourceResult],
    *,
    offline: bool,
    builder: Callable[[Settings], Any],
) -> BuildResult:
    if offline:
        return BuildResult(status="skipped", detail="offline: build not attempted")
    if any(s.required and s.status != "ok" for s in sources):
        return BuildResult(
            status="skipped", detail="skipped: a required source did not succeed"
        )

    tick = time.perf_counter()
    try:
        summary = builder(settings)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return BuildResult(
            status="failed",
            detail=f"{type(exc).__name__}: {exc}",
            seconds=round(time.perf_counter() - tick, 3),
        )
    return BuildResult(
        status="ok",
        detail=f"{summary.rows} mart rows",
        rows=summary.rows,
        content_hash=summary.content_hash,
        seconds=round(time.perf_counter() - tick, 3),
    )


def _write_report(settings: Settings, report: DataReport) -> Path:
    settings.manifest_dir.mkdir(parents=True, exist_ok=True)
    target = settings.manifest_dir / f"data-{report.run_id}.json"
    target.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return target


def verify_artifacts(
    settings: Settings, *, catalogue_path: Path | None = None
) -> list[tuple[str, str]]:
    """Check every active artifact against the catalogue. Returns (id, problem)."""
    path = catalogue_path or settings.catalogue_dir / "datasets.json"
    catalogue = catalogue_module.load(path)
    found: list[tuple[str, str]] = []
    for entry in catalogue.datasets:
        if entry.status != "active":
            continue
        artifact = settings.data_dir / entry.artifact if entry.artifact else None
        problem, _ = _check_artifact(entry, artifact)
        if problem is not None:
            found.append((entry.id, problem))
    return found
