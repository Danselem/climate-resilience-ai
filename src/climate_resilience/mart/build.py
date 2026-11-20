"""Building the indicator mart.

Precomputation is a deliberate design decision: raster/grid overlays never run
at question time. Every row carries the envelope that produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from ..envelope import DatasetRef, EvidenceEnvelope, Quality, RunRef, Scope
from ..indicators import IndicatorSpec
from ..indicators.heat import annual_extreme_day_counts, area_weighted_mean
from ..manifest import sha256_obj
from ..spatial import Cell, native_resolution_label

GRID_WARNING = (
    "ERA5 via Open-Meteo (secondary distribution); Copernicus CDS adapter not yet implemented"
)


@dataclass(frozen=True)
class CellWeight:
    cell: Cell
    inside_fraction: float
    area_km2: float


def build_cell_rows(
    frame: pd.DataFrame,
    *,
    spec: IndicatorSpec,
    threshold: float,
    weights: dict[str, CellWeight],
    datasets: list[DatasetRef],
    run: RunRef,
    min_coverage: float,
    cell_deg: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    resolution = native_resolution_label(cell_deg)

    for cell_key, group in frame.groupby("cell_id", sort=True):
        weight = weights.get(str(cell_key))
        if weight is None or weight.inside_fraction <= 0:
            continue

        series = group.set_index(pd.to_datetime(group["date"]))["tmax_c"]
        counts = annual_extreme_day_counts(
            series, threshold_c=threshold, min_coverage=min_coverage
        )

        warnings = [GRID_WARNING]
        if weight.inside_fraction < 0.999:
            warnings.append(
                f"grid cell {weight.inside_fraction:.3f} inside municipality; "
                "area weighting applied at aggregation"
            )

        for record in counts.itertuples(index=False):
            if record.status != "ok":
                continue  # I8: withheld years are not published
            year = int(record.year)
            envelope = EvidenceEnvelope(
                value=float(record.days),
                unit=spec.unit,
                indicator_id=spec.indicator_id,
                method_id=spec.method_id,
                method_version=spec.method_version,
                hazard_type=spec.hazard_type,
                scope=Scope(
                    level="grid_cell",
                    id=str(cell_key),
                    name=f"ERA5 cell {weight.cell.lat:+.3f},{weight.cell.lon:+.3f}",
                    geometry_ref=None,
                ),
                period=_year_period(year),
                datasets=datasets,
                quality=Quality(
                    n_samples=int(record.n_obs),
                    coverage_pct=round(float(record.coverage) * 100, 2),
                    missing_pct=round((1.0 - float(record.coverage)) * 100, 2),
                    native_resolution=resolution,
                    warnings=warnings,
                ),
                run=run,
            )
            rows.append(to_row(envelope))
    return rows


def build_municipality_rows(
    cell_rows: list[dict[str, Any]],
    *,
    spec: IndicatorSpec,
    weights: dict[str, CellWeight],
    municipality_name: str,
    datasets: list[DatasetRef],
    run: RunRef,
    cell_deg: float,
    years_total: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not cell_rows:
        return rows

    frame = pd.DataFrame(cell_rows)
    resolution = native_resolution_label(cell_deg)

    for year, group in frame.groupby(frame["period_start"].map(lambda d: d.year), sort=True):
        cell_ids = list(group["scope_id"])
        values = [float(v) for v in group["value"]]
        cell_weights = [weights[c].area_km2 for c in cell_ids]
        value = area_weighted_mean(values, cell_weights)

        withheld = years_total - len(cell_ids)
        warnings = [
            GRID_WARNING,
            "metro figure is an area-weighted mean across ERA5 grid cells, not a "
            "ward-level observation",
        ]
        if withheld > 0:
            warnings.append(f"{withheld} grid cell(s) withheld for low coverage in {year}")

        envelope = EvidenceEnvelope(
            value=round(value, 3),
            unit=spec.unit,
            indicator_id=spec.indicator_id,
            method_id=f"{spec.method_id}_area_weighted",
            method_version=spec.method_version,
            hazard_type=spec.hazard_type,
            scope=Scope(level="municipality", id="ethekwini", name=municipality_name),
            period=_year_period(int(year)),
            datasets=datasets,
            quality=Quality(
                n_samples=int(group["n_samples"].sum()),
                coverage_pct=round(float(group["coverage_pct"].mean()), 2),
                missing_pct=round(float(group["missing_pct"].mean()), 2),
                native_resolution=resolution,
                warnings=warnings,
            ),
            run=run,
        )
        row = to_row(envelope)
        row["basis"] = "derived"
        row["uncertainty_lower"] = round(min(values), 3)
        row["uncertainty_upper"] = round(max(values), 3)
        rows.append(row)
    return rows


def to_row(envelope: EvidenceEnvelope) -> dict[str, Any]:
    """Flatten an envelope to a mart row, with a deterministic surrogate key."""
    identity = {
        "indicator_id": envelope.indicator_id,
        "method_version": envelope.method_version,
        "scope_level": envelope.scope.level,
        "scope_id": envelope.scope.id,
        "period_start": envelope.period.start.isoformat(),
        "period_end": envelope.period.end.isoformat(),
        "hazard_type": envelope.hazard_type,
        "return_period_years": envelope.return_period_years,
        "depth_threshold_m": envelope.depth_threshold_m,
        "mechanism": envelope.mechanism,
        "basis": envelope.period.basis,
        "scenario": envelope.scenario,
        "model": envelope.model,
        "dataset_versions": sorted(d.version for d in envelope.datasets),
    }
    return {
        "row_key": sha256_obj(identity),
        "indicator_id": envelope.indicator_id,
        "method_version": envelope.method_version,
        "scope_level": envelope.scope.level,
        "scope_id": envelope.scope.id,
        "scope_name": envelope.scope.name,
        "period_start": envelope.period.start,
        "period_end": envelope.period.end,
        "hazard_type": envelope.hazard_type,
        "return_period_years": envelope.return_period_years,
        "depth_threshold_m": envelope.depth_threshold_m,
        "mechanism": envelope.mechanism,
        "basis": envelope.period.basis,
        "scenario": envelope.scenario,
        "model": envelope.model,
        "baseline_start": envelope.baseline_period.start if envelope.baseline_period else None,
        "baseline_end": envelope.baseline_period.end if envelope.baseline_period else None,
        "value": envelope.value,
        "unit": envelope.unit,
        "uncertainty_lower": envelope.uncertainty.lower if envelope.uncertainty else None,
        "uncertainty_upper": envelope.uncertainty.upper if envelope.uncertainty else None,
        "n_samples": envelope.quality.n_samples,
        "coverage_pct": envelope.quality.coverage_pct,
        "missing_pct": envelope.quality.missing_pct,
        "native_resolution": envelope.quality.native_resolution,
        "warnings": json.dumps(envelope.quality.warnings, ensure_ascii=False),
        "dataset_version": ",".join(sorted(d.version for d in envelope.datasets)),
        "run_id": envelope.run.run_id,
        "created_at": envelope.run.created_at,
    }


def _year_period(year: int) -> Any:
    from ..envelope import Period

    return Period(start=date(year, 1, 1), end=date(year, 12, 31), basis="reanalysis")
