"""Municipal boundary ingestion.

Primary source is the Municipal Demarcation Board. That site was unreachable
from the build environment (connection timeout), so this module uses the
geoBoundaries ADM2 release, which is itself derived from MDB data and carries
an explicit licence. The MDB adapter is declared but not enabled: no result at
ward level may be published until authoritative ward polygons are ingested.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry.base import BaseGeometry

from ..config import Settings
from ..envelope import DatasetRef
from ..spatial import STORAGE_CRS, area_km2, feature_by_name, geometry_of, load_geojson
from .http import DownloadResult, download, get_json

GEOBOUNDARIES_METADATA_URL = "https://www.geoboundaries.org/api/current/gbOpen/ZAF/ADM2/"
ADM4_METADATA_URL = "https://www.geoboundaries.org/api/current/gbOpen/ZAF/ADM4/"
GEOBOUNDARIES_LICENCE = "CC BY 3.0 IGO"
GEOBOUNDARIES_SOURCE = (
    "geoBoundaries ZAF ADM2 (derived from South African Municipal Demarcation Board)"
)
ADM4_SOURCE = (
    "geoBoundaries ZAF ADM4 wards (derived from South African Municipal Demarcation Board)"
)


@dataclass(frozen=True)
class Municipality:
    name: str
    feature_path: Path
    geometry: BaseGeometry
    dataset: DatasetRef
    licence: str
    vintage: str
    area_km2: float
    crs: str = STORAGE_CRS

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return tuple(self.geometry.bounds)  # type: ignore[return-value]


def fetch_municipality(settings: Settings, name: str) -> Municipality:
    """Download the ADM2 release and extract one municipality."""
    meta = get_json(GEOBOUNDARIES_METADATA_URL)
    if not isinstance(meta, dict) or "gjDownloadURL" not in meta:
        raise RuntimeError("unexpected geoBoundaries metadata payload")

    release = str(meta.get("boundaryYearRepresented", "unknown"))
    version = f"adm2-{release}"
    raw_dir = settings.raw_dir / "geoboundaries_zaf_adm2" / version
    raw_path = raw_dir / "geoBoundaries-ZAF-ADM2.geojson"

    if raw_path.exists():
        result = DownloadResult(
            url=str(meta["gjDownloadURL"]),
            path=raw_path,
            sha256=_existing_sha(raw_path),
            bytes=raw_path.stat().st_size,
            retrieved_at="cached",
        )
    else:
        result = download(str(meta["gjDownloadURL"]), raw_path)

    collection = load_geojson(result.path)
    feature = feature_by_name(collection, name)
    geom = geometry_of(feature)

    processed_dir = settings.processed_dir / "geoboundaries_zaf_adm2" / version
    processed_dir.mkdir(parents=True, exist_ok=True)
    feature_path = processed_dir / f"{name.lower()}.geojson"
    feature_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "source": GEOBOUNDARIES_SOURCE,
                "crs": STORAGE_CRS,
                "licence": str(meta.get("boundaryLicense", GEOBOUNDARIES_LICENCE)),
                "vintage": release,
                "features": [feature],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return Municipality(
        name=name,
        feature_path=feature_path,
        geometry=geom,
        dataset=DatasetRef(
            id="geoboundaries_zaf_adm2",
            version=version,
            checksum=result.sha256,
            source_url=str(meta["gjDownloadURL"]),
            licence=str(meta.get("boundaryLicense", GEOBOUNDARIES_LICENCE)),
        ),
        licence=str(meta.get("boundaryLicense", GEOBOUNDARIES_LICENCE)),
        vintage=release,
        area_km2=area_km2(geom),
    )


def require_mdb_wards() -> None:
    """Authoritative ward polygons are a hard prerequisite for ward-level results.

    geoBoundaries ADM4 wards are in use (a redistribution of MDB data), which is
    sufficient for geometry, crosswalking and validation. It is not sufficient
    to publish ward-level statistics against Census geography, because the ward
    codes are parsed rather than official and the vintage may not match. This
    gate stays raised until the MDB release itself is ingested.
    """
    raise RuntimeError(
        "Authoritative MDB ward boundaries not available. The geoBoundaries ADM4 "
        "substitute (CC BY 3.0 IGO) supports ward geometry but carries no official "
        "ward codes and an unverified vintage. Ward-level published statistics must "
        "not be released until this gate passes."
    )


@dataclass(frozen=True)
class WardLayer:
    name: str
    path: Path
    vintage: str
    licence: str
    dataset: DatasetRef
    wards: dict[str, tuple[str, int | None, BaseGeometry]]


def fetch_wards(settings: Settings, municipality: str) -> WardLayer:
    """Download the ADM4 ward release and extract one municipality's wards.

    The layer is a redistribution of MDB data, not the MDB release itself.
    Ward numbers are parsed from the feature name (``eThekwini 001``) because
    the source does not carry official ward codes; this is recorded so no
    downstream join can assume otherwise.
    """
    meta = get_json(ADM4_METADATA_URL)
    if not isinstance(meta, dict) or "gjDownloadURL" not in meta:
        raise RuntimeError("unexpected geoBoundaries ADM4 metadata payload")

    release = str(meta.get("boundaryYearRepresented", "unknown"))
    version = f"adm4-{release}"
    raw_dir = settings.raw_dir / "geoboundaries_zaf_adm4" / version
    raw_path = raw_dir / "geoBoundaries-ZAF-ADM4.geojson"
    if not raw_path.exists():
        download(str(meta["gjDownloadURL"]), raw_path)

    collection = load_geojson(raw_path)
    prefix = municipality.strip().lower()
    selected: list[dict] = []
    wards: dict[str, tuple[str, int | None, BaseGeometry]] = {}

    for feature in collection.get("features", []):
        name = str(feature.get("properties", {}).get("shapeName", ""))
        if not name.lower().startswith(f"{prefix} "):
            continue
        number = _trailing_int(name)
        suffix = f"{number:03d}" if number is not None else f"{len(selected):03d}"
        ward_id = f"{prefix}-{suffix}"
        wards[ward_id] = (name, number, geometry_of(feature))
        selected.append(
            {
                "type": "Feature",
                "properties": {
                    "ward_id": ward_id,
                    "ward_name": name,
                    "ward_number": number,
                    "municipality": municipality,
                    "ward_code_provenance": "parsed from shapeName; not an official MDB code",
                },
                "geometry": feature["geometry"],
            }
        )

    if not selected:
        raise RuntimeError(f"no wards found for {municipality!r} in ADM4 release")

    processed_dir = settings.processed_dir / "geoboundaries_zaf_adm4" / version
    processed_dir.mkdir(parents=True, exist_ok=True)
    path = processed_dir / f"{prefix}-wards.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "source": ADM4_SOURCE,
                "crs": STORAGE_CRS,
                "licence": str(meta.get("boundaryLicense", GEOBOUNDARIES_LICENCE)),
                "vintage": release,
                "ward_count": len(selected),
                "features": selected,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return WardLayer(
        name=municipality,
        path=path,
        vintage=release,
        licence=str(meta.get("boundaryLicense", GEOBOUNDARIES_LICENCE)),
        dataset=DatasetRef(
            id="geoboundaries_zaf_adm4",
            version=version,
            checksum=_existing_sha(raw_path),
            source_url=str(meta["gjDownloadURL"]),
            licence=str(meta.get("boundaryLicense", GEOBOUNDARIES_LICENCE)),
        ),
        wards=wards,
    )


def _trailing_int(text: str) -> int | None:
    match = re.search(r"(\d+)\s*$", text)
    return int(match.group(1)) if match else None


def _existing_sha(path: Path) -> str:
    from ..manifest import sha256_file

    return sha256_file(path)
