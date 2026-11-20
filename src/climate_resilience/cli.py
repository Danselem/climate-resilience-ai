"""CLI entrypoints.

    uv run climate-resilience boundaries
    uv run climate-resilience climate
    uv run climate-resilience mart
    uv run climate-resilience show --scope-level municipality
"""

from __future__ import annotations

import json

import typer

from . import acquire
from . import catalogue as catalogue_module
from .config import get_settings
from .exposure import build_exposure
from .flood import build_flood
from .indicators import REGISTRY
from .ingestion.aqueduct import fetch_flood
from .ingestion.census import fetch_census_ward_population
from .ingestion.worldpop import fetch_worldpop
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
def worldpop() -> None:
    """Clip the WorldPop 1 km grid to the municipality."""
    settings = get_settings()
    municipality = load_or_fetch_municipality(settings)
    extract = fetch_worldpop(settings, municipality)
    typer.echo(f"cells         : {len(extract.grid):,}")
    typer.echo(f"population    : {float(extract.grid['population'].sum()):,.0f}")
    typer.echo("resolution    : 1 km (WorldPop 2020, UN-adjusted)")
    typer.echo(f"processed     : {extract.processed_path}")


@app.command()
def census() -> None:
    """Fetch the Census 2022 ward population table (population only)."""
    settings = get_settings()
    extract = fetch_census_ward_population(settings)
    typer.echo(f"wards         : {extract.summary['ward_count']}")
    typer.echo(f"population    : {float(extract.summary['population_total']):,.0f}")
    typer.echo(f"processed     : {extract.processed_path}")
    typer.echo("note          : 111 census wards vs 110 boundary wards; not joined")


@app.command()
def exposure() -> None:
    """Build ward and municipality population exposure from WorldPop."""
    settings = get_settings()
    summary = build_exposure(settings)
    typer.echo(f"run_id        : {summary.run_id}")
    typer.echo(f"rows          : {summary.rows}")
    typer.echo(f"content_hash  : {summary.content_hash}")
    typer.echo(f"snapshot      : {summary.snapshot_path}")


@app.command()
def flood() -> None:
    """Download the Aqueduct baseline layers and clip them to the municipality."""
    settings = get_settings()
    municipality = load_or_fetch_municipality(settings)
    extract = fetch_flood(settings, municipality)
    typer.echo(f"cell-layers   : {len(extract.frame):,}")
    for key, layer in extract.summary["layers"].items():  # type: ignore[union-attr]
        typer.echo(
            f"  {key:<14} wet={layer['wet_cells']:>4}  max={layer['max_depth_m']:>5.3f} m"
        )
    typer.echo(
        "resolution    : 1 km raster from a 5' (~10 km) hydrological model "
        "(Aqueduct Floods v2, baseline)"
    )
    typer.echo(f"processed     : {extract.processed_path}")


@app.command("flood-exposure")
def flood_exposure(
    threshold: float | None = typer.Option(
        None, help="Depth threshold in metres; default is any modelled inundation"
    ),
) -> None:
    """Build ward and municipality flood exposure from the hazard grid."""
    settings = get_settings()
    summary = build_flood(settings, threshold_m=0.0 if threshold is None else threshold)
    typer.echo(f"run_id        : {summary.run_id}")
    typer.echo(f"rows          : {summary.rows} "
               f"({summary.area_rows} area, {summary.population_rows} population)")
    typer.echo(f"content_hash  : {summary.content_hash}")
    typer.echo(f"withheld      : {len(summary.withheld)} scope-layers (no hazard data)")
    for item in summary.withheld[:6]:
        typer.echo(f"  {item}")
    for path in summary.snapshot_paths:
        typer.echo(f"snapshot      : {path}")


@app.command()
def mart(
    indicator: str = typer.Option("hot_days_tmax_ge_35c", help="Registered indicator id"),
    threshold: float | None = typer.Option(None, help="Override the default threshold"),
    climate_version: str | None = typer.Option(
        None, help="Climate version to use; default is the recorded pointer"
    ),
) -> None:
    """Build the indicator mart from canonical inputs."""
    settings = get_settings()
    summary = build_mart(
        settings,
        indicator_id=indicator,
        threshold=threshold,
        climate_version=climate_version,
    )
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
def data(
    offline: bool = typer.Option(
        False, "--offline", help="Verify cached artifacts only; no network access"
    ),
) -> None:
    """Acquire every catalogued source, then build the mart.

    Required sources must succeed; optional ones are recorded as skipped. The
    run always writes data/manifests/data-<run_id>.json.
    """
    settings = get_settings()
    try:
        report = acquire.run_data(settings, offline=offline)
    except ValueError as exc:
        typer.echo(f"cannot run: {exc}")
        raise typer.Exit(code=1) from exc

    typer.echo(f"run_id        : {report.run_id}")
    typer.echo(f"mode          : {'offline (no network)' if offline else 'live'}")
    typer.echo("")
    for source in report.sources:
        mark = {"ok": "ok  ", "failed": "FAIL", "skipped": "skip"}[source.status]
        typer.echo(
            f"  {mark} {source.dataset_id:<24} {source.detail} "
            f"({source.seconds:.1f}s)"
        )
    build = report.build
    mark = {"ok": "ok  ", "failed": "FAIL", "skipped": "skip"}[build.status]
    typer.echo(f"  {mark} mart build               {build.detail}")
    if build.content_hash:
        typer.echo(f"       content_hash             {build.content_hash}")
    typer.echo(f"\nreport        : data-{report.run_id}.json")

    if not report.ok:
        typer.echo("")
        for source in report.failed_required:
            typer.echo(f"required source failed: {source.dataset_id}: {source.detail}")
        if build.status == "failed":
            typer.echo(f"build failed: {build.detail}")
        raise typer.Exit(code=1)
    typer.echo("\nall required sources acquired")


@app.command()
def verify() -> None:
    """Check catalogue coherence and that every active artifact matches its checksum."""
    settings = get_settings()
    path = settings.catalogue_dir / "datasets.json"
    parsed = catalogue_module.load(path)
    problems = catalogue_module.validate(parsed)
    for entry in parsed.datasets:
        if entry.status == "active":
            typer.echo(f"active {entry.id:<24} {entry.checksum[:12] if entry.checksum else '-'}")
    for dataset_id, problem in acquire.verify_artifacts(settings):
        problems.append(f"{dataset_id}: {problem}")

    if problems:
        typer.echo("")
        for problem in problems:
            typer.echo(f"problem: {problem}")
        raise typer.Exit(code=1)
    typer.echo("\nartifacts match catalogue checksums")


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
