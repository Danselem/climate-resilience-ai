"""CLI entrypoints.

    uv run climate-resilience boundaries
    uv run climate-resilience climate
    uv run climate-resilience mart
    uv run climate-resilience show --scope-level municipality
"""

from __future__ import annotations

import json

import typer

from . import catalogue as catalogue_module
from .config import get_settings
from .indicators import REGISTRY
from .pipeline import (
    build_boundary_layer,
    build_mart,
    fetch_climate,
    load_or_fetch_municipality,
    plan_cells,
)
from .store import repository

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def boundaries() -> None:
    """Fetch the municipal boundary and report what was actually obtained."""
    settings = get_settings()
    municipality = load_or_fetch_municipality(settings)
    typer.echo(f"municipality : {municipality.name}")
    typer.echo(f"area_km2     : {municipality.area_km2:,.1f}")
    typer.echo(f"vintage      : {municipality.vintage}")
    typer.echo(f"licence      : {municipality.licence}")
    typer.echo(f"checksum     : {municipality.dataset.checksum}")
    typer.echo(f"bounds       : {municipality.bounds}")
    typer.echo(f"path         : {municipality.feature_path}")


@app.command()
def wards() -> None:
    """Ingest, validate and persist the ward boundary layer (Phase 2 gate)."""
    settings = get_settings()
    summary = build_boundary_layer(settings)

    typer.echo(f"run_id        : {summary.run_id}")
    typer.echo(f"vintage       : {summary.vintage}")
    typer.echo(f"wards         : {summary.ward_count}")
    typer.echo(f"crosswalk     : {summary.crosswalk_rows} ward -> municipality row(s)")
    typer.echo(f"ward area     : {summary.report.total_area_km2:,.1f} km²")
    typer.echo(f"municipality  : {summary.municipality.area_km2:,.1f} km²")
    delta = summary.report.total_area_km2 - summary.municipality.area_km2
    typer.echo(f"difference    : {delta:+,.1f} km²")
    typer.echo(f"repaired      : {len(summary.report.repaired)}")
    for issue in summary.report.issues:
        typer.echo(f"  [{issue.severity}] {issue.code}: {issue.detail}")

    typer.echo("\nspot checks:")
    for result in summary.spot_results:
        mark = "ok  " if result.passed else "FAIL"
        typer.echo(f"  {mark} {result.label:<18} -> {result.ward_name}")
    typer.echo(f"\nreport        : {summary.report_path}")


@app.command()
def climate() -> None:
    """Fetch daily Tmax for every ERA5 cell intersecting the municipality."""
    settings = get_settings()
    municipality = load_or_fetch_municipality(settings)
    weights = plan_cells(municipality, settings.era5_cell_deg)
    typer.echo(f"cells intersecting municipality: {len(weights)}")
    extract = fetch_climate(settings, weights)
    frame = extract.frame
    typer.echo(f"rows          : {len(frame):,}")
    typer.echo(f"cells         : {frame['cell_id'].nunique()}")
    typer.echo(f"date range    : {frame['date'].min()} .. {frame['date'].max()}")
    typer.echo(f"missing tmax  : {int(frame['tmax_c'].isna().sum()):,}")
    typer.echo(f"processed     : {extract.processed_path}")


@app.command()
def mart(
    indicator: str = typer.Option("hot_days_tmax_ge_35c", help="Registered indicator id"),
    threshold: float | None = typer.Option(None, help="Override the default threshold"),
) -> None:
    """Build the indicator mart from canonical inputs."""
    settings = get_settings()
    summary = build_mart(settings, indicator_id=indicator, threshold=threshold)
    typer.echo(f"run_id        : {summary.run_id}")
    typer.echo(f"rows          : {summary.rows}")
    typer.echo(f"content_hash  : {summary.content_hash}")
    typer.echo(f"snapshot      : {summary.snapshot_path}")
    typer.echo(f"manifest      : {summary.manifest.stage}-{summary.run_id}.json")
    typer.echo(
        f"municipality  : {summary.municipality.name} "
        f"({summary.municipality.area_km2:,.1f} km²)"
    )


@app.command()
def show(
    indicator: str = typer.Option("hot_days_tmax_ge_35c"),
    scope_level: str = typer.Option("municipality", help="municipality | grid_cell"),
    limit: int = typer.Option(10),
) -> None:
    """Print published mart values with their provenance."""
    settings = get_settings()
    engine = repository.make_engine(settings.database_url)
    repository.ensure_schema(engine)
    rows = repository.fetch(engine, indicator_id=indicator, scope_level=scope_level)
    if not rows:
        typer.echo("no rows; run `climate-resilience mart` first")
        raise typer.Exit(code=1)
    typer.echo(f"{len(rows)} row(s) for {indicator} at {scope_level}")
    for row in rows[:limit]:
        typer.echo(
            f"{row['period_start']:%Y}  {row['value']:>8.3f} {row['unit']:<6} "
            f"{row['scope_id']:<32} basis={row['basis']:<8} cov={row['coverage_pct']:.1f}%"
        )
    last = rows[-1]
    typer.echo("")
    typer.echo("provenance of last row:")
    typer.echo(json.dumps({k: str(v) for k, v in last.items()}, indent=2))


@app.command()
def indicators() -> None:
    """List registered indicators and their definitions."""
    for spec in REGISTRY.values():
        typer.echo(f"{spec.indicator_id}  v{spec.method_version}  [{spec.hazard_type}]")
        typer.echo(f"  {spec.description}")
        typer.echo(f"  unit={spec.unit} method={spec.method_id} citation={spec.citation}")


@app.command()
def catalogue() -> None:
    """Validate the dataset catalogue and show gate status."""
    settings = get_settings()
    path = settings.catalogue_dir / "datasets.json"
    if not path.exists():
        typer.echo(f"no catalogue at {path}")
        raise typer.Exit(code=1)
    parsed = catalogue_module.load(path)
    problems = catalogue_module.validate(parsed)
    for entry in parsed.datasets:
        mark = {"active": "OK  ", "blocked": "BLOCK", "planned": "PLAN "}.get(
            entry.status, entry.status
        )
        typer.echo(f"{mark} {entry.id:<24} {entry.basis:<18} {entry.version}")
    if problems:
        typer.echo("")
        for problem in problems:
            typer.echo(f"problem: {problem}")
        raise typer.Exit(code=1)
    typer.echo("\ncatalogue valid")


if __name__ == "__main__":
    app()
