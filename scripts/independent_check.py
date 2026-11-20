"""Reference checks for the published mart.

The heat check deliberately does not import the project's indicator code: it
re-derives the count from the raw JSON payloads with plain Python. The exposure
check verifies the allocation invariant that ward totals sum to the municipal
total. The flood check recounts wet cells with a rasteriser instead of polygon
intersection, so the hazard extent is verified by a different method.

    uv run python scripts/independent_check.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from shapely.geometry import shape

THRESHOLD_C = 35.0
DB_PATH = Path("data/mart.db")
RAW_GLOB = "data/raw/era5_openmeteo/*/daily_tmax_batch*.json"


def cell_key(lat: float, lon: float) -> str:
    return f"cell_lat{lat:+.3f}_lon{lon:+.3f}"


def reference_counts() -> dict[tuple[str, int], int]:
    """(cell_id, year) -> days at or above the threshold, from raw JSON only."""
    observations: dict[str, dict[str, float]] = {}
    for path in sorted(Path().glob(RAW_GLOB)):
        payload = json.loads(path.read_text())
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            key = cell_key(float(entry["latitude"]), float(entry["longitude"]))
            per_cell = observations.setdefault(key, {})
            for day, value in zip(
                entry["daily"]["time"], entry["daily"]["temperature_2m_max"], strict=True
            ):
                if value is not None:
                    per_cell[day] = float(value)

    counts: dict[tuple[str, int], int] = {}
    for key, per_cell in observations.items():
        for day, value in per_cell.items():
            if value >= THRESHOLD_C:
                year = int(day[:4])
                counts[(key, year)] = counts.get((key, year), 0) + 1
        for day in per_cell:
            counts.setdefault((key, int(day[:4])), 0)
    return counts


def published_counts() -> dict[tuple[str, int], float]:
    if not DB_PATH.exists():
        raise SystemExit(f"mart not found at {DB_PATH}; run `climate-resilience mart`")
    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            """
            select scope_id, substr(period_start, 1, 4), value
            from indicator_value
            where indicator_id = 'hot_days_tmax_ge_35c' and scope_level = 'grid_cell'
            """
        ).fetchall()
    finally:
        connection.close()
    return {(scope_id, int(year)): float(value) for scope_id, year, value in rows}


def exposure_check() -> list[str]:
    """Ward exposure must sum to the municipal total, with 110 wards."""
    if not DB_PATH.exists():
        return [f"mart not found at {DB_PATH}"]
    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            """
            select scope_level, count(*), coalesce(sum(value), 0)
            from indicator_value
            where indicator_id = 'population_count_worldpop'
            group by scope_level
            """
        ).fetchall()
    finally:
        connection.close()

    totals = {level: (int(count), float(total)) for level, count, total in rows}
    problems: list[str] = []
    ward_count, ward_total = totals.get("ward", (0, 0.0))
    metro_count, metro_total = totals.get("municipality", (0, 0.0))

    if ward_count != 110:
        problems.append(f"expected 110 exposure wards, found {ward_count}")
    if metro_count != 1:
        problems.append(f"expected 1 exposure municipality row, found {metro_count}")
    if abs(ward_total - metro_total) > 1.0:
        problems.append(
            f"ward exposure sums to {ward_total:,.1f} but municipality is {metro_total:,.1f}"
        )

    print(f"exposure wards        : {ward_count}")
    print(f"exposure ward total   : {ward_total:,.1f}")
    print(f"exposure municipality : {metro_total:,.1f}")
    print(f"exposure mismatches   : {len(problems)}")
    return problems


def flood_check() -> list[str]:
    """Recount wet cells with a rasteriser and check the area invariant.

    The mart counts a cell as wet for a scope when the cell and the polygon
    overlap at all, so the reference uses ``all_touched=True`` for the same
    definition. Different implementation, same expected answer.
    """
    problems: list[str] = []
    if not DB_PATH.exists():
        return [f"mart not found at {DB_PATH}"]
    pointer = Path("data/processed/aqueduct_floods/latest.json")
    if not pointer.exists():
        return ["flood pointer missing; flood stage has not run"]

    payload = json.loads(pointer.read_text())
    municipal = _municipal_geometry()
    connection = sqlite3.connect(DB_PATH)
    try:
        for layer in payload["layers"]:
            raw = (
                Path("data/raw/aqueduct_floods") / payload["version"] / layer["file"]
            )
            if not raw.exists():
                problems.append(f"missing raw layer {raw}")
                continue
            with rasterio.open(raw) as dataset:
                window = from_bounds(*municipal.bounds, dataset.transform)
                data = dataset.read(1, window=window)
                transform = dataset.window_transform(window)
            mask = rasterize(
                [(municipal, 1)],
                out_shape=data.shape,
                transform=transform,
                fill=0,
                all_touched=True,
            )
            wet = int(((data > 0) & (mask == 1)).sum())
            row = connection.execute(
                """
                select n_samples from indicator_value
                where indicator_id = 'flood_exposed_area_pct'
                  and scope_level = 'municipality'
                  and mechanism = ? and return_period_years = ?
                """,
                (layer["mechanism"], layer["return_period_years"]),
            ).fetchone()
            if row is None:
                problems.append(
                    f"{layer['mechanism']} rp{layer['return_period_years']}: no mart row"
                )
                continue
            published = int(row[0])
            if published != wet:
                problems.append(
                    f"{layer['mechanism']} rp{layer['return_period_years']}: "
                    f"rasteriser finds {wet} wet cells, mart says {published}"
                )
            print(
                f"flood {layer['mechanism']:<8} rp{layer['return_period_years']:>3}: "
                f"{wet} wet cells, mart {published}"
            )
    finally:
        connection.close()

    problems.extend(_flood_area_invariant(connection_path=DB_PATH))
    return problems


def _flood_area_invariant(*, connection_path: Path) -> list[str]:
    """Ward exposed areas must sum to the municipal exposed area."""
    wards = _ward_areas()
    connection = sqlite3.connect(connection_path)
    try:
        rows = connection.execute(
            """
            select scope_level, mechanism, return_period_years, scope_id, value
            from indicator_value where indicator_id = 'flood_exposed_area_pct'
            """
        ).fetchall()
    finally:
        connection.close()

    municipal_area = _municipal_geometry_area()
    problems: list[str] = []
    for mechanism, return_period in (
        (row[1], row[2]) for row in rows if row[0] == "municipality"
    ):
        ward_rows = [
            row for row in rows if row[0] == "ward" and row[1] == mechanism
            and row[2] == return_period
        ]
        known = [row for row in ward_rows if row[3] in wards]
        total = sum(row[4] * wards[row[3]] / 100.0 for row in known)
        metro = next(
            row[4] for row in rows
            if row[0] == "municipality" and row[1] == mechanism and row[2] == return_period
        )
        metro_km2 = metro * municipal_area / 100.0
        print(
            f"flood area {mechanism:<8} rp{return_period:>3}: "
            f"wards {total:8.2f} km2, municipality {metro_km2:8.2f} km2 "
            f"({len(known)}/{len(ward_rows)} wards published)"
        )
        if abs(total - metro_km2) > max(1.0, 0.02 * metro_km2):
            problems.append(
                f"{mechanism} rp{return_period}: ward areas sum to {total:.2f} km2 "
                f"but the municipality is {metro_km2:.2f} km2"
            )
    return problems


def _municipal_geometry():
    path = next(Path().glob("data/processed/geoboundaries_zaf_adm2/*/ethekwini.geojson"))
    return shape(json.loads(path.read_text())["features"][0]["geometry"])


def _ward_areas() -> dict[str, float]:
    from pyproj import Transformer
    from shapely.ops import transform

    path = next(
        Path().glob("data/processed/geoboundaries_zaf_adm4/*/ethekwini-wards.geojson")
    )
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32736", always_xy=True)
    areas: dict[str, float] = {}
    for feature in json.loads(path.read_text())["features"]:
        geom = transform(to_utm.transform, shape(feature["geometry"]))
        areas[str(feature["properties"]["ward_id"])] = geom.area / 1e6
    return areas


def _municipal_geometry_area() -> float:
    from pyproj import Transformer
    from shapely.ops import transform

    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32736", always_xy=True)
    geom = transform(to_utm.transform, _municipal_geometry())
    return geom.area / 1e6


def main() -> int:
    reference = reference_counts()
    published = published_counts()

    missing = sorted(set(reference) - set(published))
    extra = sorted(set(published) - set(reference))
    mismatched = [
        (key, reference[key], published[key])
        for key in sorted(set(reference) & set(published))
        if abs(reference[key] - published[key]) > 1e-9
    ]

    print(f"reference cell-years : {len(reference)}")
    print(f"published cell-years : {len(published)}")
    print(f"missing from mart    : {len(missing)}")
    print(f"in mart but not raw  : {len(extra)}")
    print(f"value mismatches     : {len(mismatched)}")

    for key, ref, got in mismatched[:10]:
        print(f"  {key[0]} {key[1]}: reference={ref} published={got}")
    for key in missing[:10]:
        print(f"  missing {key}")
    for key in extra[:10]:
        print(f"  extra   {key}")

    print("")
    exposure_problems = exposure_check()
    for problem in exposure_problems:
        print(f"  exposure: {problem}")

    print("")
    flood_problems = flood_check()
    for problem in flood_problems:
        print(f"  flood: {problem}")

    if mismatched or missing or extra or exposure_problems or flood_problems:
        print("\nRESULT: FAIL")
        return 1
    print(
        "\nRESULT: PASS — heat cell-years match an independent recount; "
        "exposure wards sum to the municipality; flood wet cells match a "
        "rasteriser recount and flood ward areas sum to the municipality"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
