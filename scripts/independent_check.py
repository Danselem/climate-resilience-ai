"""Independent reference check for `hot_days_tmax_ge_35c`.

Deliberately does not import the project's indicator code. It re-derives the
count from the raw JSON payloads with plain Python, then compares against the
published mart. If the two disagree, the mart is wrong.

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

    if mismatched or missing or extra:
        print("\nRESULT: FAIL")
        return 1
    print("\nRESULT: PASS — every published cell-year matches an independent recount")
    return 0


if __name__ == "__main__":
    sys.exit(main())
