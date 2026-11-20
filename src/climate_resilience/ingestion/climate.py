"""Historical daily temperature ingestion.

Production path is the Copernicus CDS ERA5 request (NetCDF, versioned,
reproducible). That path needs credentials and licence acceptance, which this
build environment does not have, so this adapter uses the Open-Meteo archive
API, which serves ERA5-derived daily aggregates over HTTPS without a key.

Both adapters produce the same canonical tidy table, so swapping the source
changes provenance, not downstream code:

    cell_id | date | tmax_c | lat | lon

The response's reported latitude/longitude is recorded, not the requested
coordinate: the data location is what the grid cell is, and pretending
otherwise would misplace every polygon weight.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import Settings
from ..envelope import DatasetRef
from ..spatial import Cell, cell_id
from .http import get_json

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
LICENCE = "CC BY 4.0 (Open-Meteo); underlying reanalysis: Copernicus ERA5"
TIME_BASIS = "local_day Africa/Johannesburg (UTC+2)"
BATCH_SIZE = 8


@dataclass(frozen=True)
class ClimateExtract:
    frame: pd.DataFrame
    dataset: DatasetRef
    raw_paths: list[Path]
    processed_path: Path
    time_basis: str = TIME_BASIS


def fetch_daily_tmax(
    settings: Settings,
    cells: list[Cell],
    *,
    start: str,
    end: str,
    version: str,
) -> ClimateExtract:
    raw_dir = settings.raw_dir / "era5_openmeteo" / version
    raw_dir.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    raw_paths: list[Path] = []
    checksums: list[str] = []

    for index, batch in enumerate(_chunks(cells, BATCH_SIZE)):
        raw_path = raw_dir / f"daily_tmax_batch{index:02d}.json"
        if raw_path.exists():
            # Raw inputs are immutable: a retrieved payload is reused, never
            # silently re-fetched. Pin a new version to refresh.
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            payload = get_json(_build_url(batch, start, end))
            raw_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        raw_paths.append(raw_path)
        checksums.append(_sha(raw_path))
        frames.extend(_parse(payload, batch))

    frame = pd.concat(frames, ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.drop_duplicates(subset=["cell_id", "date"]).sort_values(["cell_id", "date"])

    processed_dir = settings.processed_dir / "era5_openmeteo" / version
    processed_dir.mkdir(parents=True, exist_ok=True)
    processed_path = processed_dir / "daily_tmax.parquet"
    frame.to_parquet(processed_path, index=False)

    dataset = DatasetRef(
        id="era5_openmeteo",
        version=version,
        checksum=_combine_checksums(checksums),
        source_url=ARCHIVE_URL,
        licence=LICENCE,
    )
    return ClimateExtract(
        frame=frame,
        dataset=dataset,
        raw_paths=raw_paths,
        processed_path=processed_path,
    )


def _build_url(batch: list[Cell], start: str, end: str) -> str:
    lats = ",".join(f"{c.lat:.4f}" for c in batch)
    lons = ",".join(f"{c.lon:.4f}" for c in batch)
    return (
        f"{ARCHIVE_URL}?latitude={lats}&longitude={lons}"
        f"&start_date={start}&end_date={end}"
        "&daily=temperature_2m_max&timezone=Africa%2FJohannesburg"
    )


def _parse(payload: object, batch: list[Cell]) -> list[pd.DataFrame]:
    entries = payload if isinstance(payload, list) else [payload]
    frames: list[pd.DataFrame] = []
    for entry, cell in zip(entries, batch, strict=False):
        if not isinstance(entry, dict):
            raise RuntimeError("unexpected Open-Meteo payload")
        daily = entry.get("daily") or {}
        dates = daily.get("time") or []
        values = daily.get("temperature_2m_max") or []
        if len(dates) != len(values):
            raise RuntimeError("Open-Meteo daily arrays have mismatched lengths")
        # The data location is the reported grid point, not the requested one.
        lat = float(entry.get("latitude", cell.lat))
        lon = float(entry.get("longitude", cell.lon))
        frames.append(
            pd.DataFrame(
                {
                    "cell_id": cell_id(lat, lon),
                    "date": dates,
                    "tmax_c": pd.to_numeric(pd.Series(values), errors="coerce"),
                    "lat": lat,
                    "lon": lon,
                }
            )
        )
    return frames


def _chunks(items: list[Cell], size: int) -> list[list[Cell]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _sha(path: Path) -> str:
    from ..manifest import sha256_file

    return sha256_file(path)


def _combine_checksums(checksums: list[str]) -> str:
    from ..manifest import sha256_obj

    return sha256_obj(sorted(checksums))
