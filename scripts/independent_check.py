"""Reference checks for the published mart.

The heat check deliberately does not import the project's indicator code: it
re-derives the count from the raw JSON payloads with plain Python. The exposure
check verifies the allocation invariant that ward totals sum to the municipal
total.

    uv run python scripts/independent_check.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

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

    if mismatched or missing or extra or exposure_problems:
        print("\nRESULT: FAIL")
        return 1
    print(
        "\nRESULT: PASS — heat cell-years match an independent recount; "
        "exposure wards sum to the municipality"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
