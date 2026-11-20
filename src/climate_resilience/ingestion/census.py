"""Census 2022 ward-level population estimates.

Stats SA's pages sit behind a bot challenge, but the released files are served
directly. The ward product covers population only -- age, sex and population
group. Service, tenure and employment indicators exist only in the interactive
SuperWeb/SuperCross tools and are not acquired here, so this table cannot carry
the vulnerability axis (see ``docs/limitations.md``).

The product publishes 4,468 wards nationally, 111 in eThekwini
(codes ``59500001``-``59500111``). The ADM4 boundary layer has 110 polygons.
The table is therefore stored with official ward codes and deliberately not
joined to geometry: a 111-to-110 join would be an assumption, not a crosswalk.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import Settings
from ..envelope import DatasetRef
from ..manifest import sha256_file
from .http import download

URL = (
    "https://www.statssa.gov.za/wp-content/uploads/2025/11/"
    "Ward-Product_Locked-spreadsheets.zip"
)
VERSION = "2022-ward-sae-2025-10-27"
LICENCE = (
    "Statistics South Africa copyright; use permitted with acknowledgement of "
    "Stats SA as the source"
)
SOURCE = "Statistics South Africa, Ward-level Small Area Population Estimates, 2022"
MUNICIPALITY_PREFIX = "595"  # eThekwini, ETH
EXPECTED_WARDS = 111

FILES = {
    "population_group": "PP_Population Group_27-10-2025.xlsx",
    "sex": "PP_Sex_27-10-2025.xlsx",
    "age_group": "PP_Age Group_27-10-2025.xlsx",
}


@dataclass(frozen=True)
class CensusExtract:
    frame: pd.DataFrame
    dataset: DatasetRef
    raw_path: Path
    processed_path: Path
    summary: dict[str, object]


def fetch_census_ward_population(
    settings: Settings, *, version: str = VERSION
) -> CensusExtract:
    """Download, parse and store the eThekwini ward population table."""
    raw_dir = settings.raw_dir / "census_2022_ward_population" / version
    raw_path = raw_dir / "Ward-Product_Locked-spreadsheets.zip"
    if not raw_path.exists():
        download(URL, raw_path, timeout=180.0)

    extracted = _extract(raw_path, raw_dir / "extracted")
    frame, summary = _parse(extracted)

    processed_dir = settings.processed_dir / "census_2022_ward_population" / version
    processed_dir.mkdir(parents=True, exist_ok=True)
    processed_path = processed_dir / "ethekwini_ward_population.parquet"
    frame.to_parquet(processed_path, index=False)
    (processed_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    dataset = DatasetRef(
        id="census_2022_ward_population",
        version=version,
        checksum=sha256_file(raw_path),
        source_url=URL,
        licence=LICENCE,
    )
    return CensusExtract(
        frame=frame,
        dataset=dataset,
        raw_path=raw_path,
        processed_path=processed_path,
        summary=summary,
    )


def _extract(archive: Path, into: Path) -> dict[str, Path]:
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        names = {Path(name).name: name for name in zf.namelist()}
        for filename in FILES.values():
            if filename not in names:
                raise RuntimeError(f"census archive is missing {filename}")
            target = into / filename
            if not target.exists():
                with zf.open(names[filename]) as source:
                    target.write_bytes(source.read())
    return {label: into / filename for label, filename in FILES.items()}


def _parse(paths: dict[str, Path]) -> tuple[pd.DataFrame, dict[str, object]]:
    population = _read(paths["population_group"], "Wards")
    sex = _read(paths["sex"], "Wards_Sex")
    age = _read(paths["age_group"], "Age_group")

    population = _normalise(population, "Ward_Code")
    sex = _normalise(sex, "WARD_CODE")
    age = _normalise(age, "Ward_Code")

    population = population.rename(
        columns={
            "Black African": "population_black_african",
            "Coloured": "population_coloured",
            "Indian/Asian": "population_indian_asian",
            "White": "population_white",
            "Other": "population_other",
            "Total": "population_total",
        }
    )
    sex = sex.rename(
        columns={"Male": "population_male", "Female": "population_female", "Total": "sex_total"}
    )
    age = age.rename(
        columns={
            column: (
                "age_total"
                if column == "Total"
                else f"age_{column.replace('-', '_').replace('+', 'plus')}"
            )
            for column in age.columns
            if column != "ward_code"
        }
    )

    national_wards = len(population)
    merged = population.merge(sex, on="ward_code", how="inner").merge(
        age, on="ward_code", how="inner"
    )
    if len(merged) != national_wards:
        raise RuntimeError(
            "census workbooks disagree on ward codes: "
            f"{national_wards} population rows, {len(merged)} merged rows"
        )

    _check_totals(merged)

    eth = merged[merged["ward_code"].str.startswith(MUNICIPALITY_PREFIX)].copy()
    if len(eth) != EXPECTED_WARDS:
        raise RuntimeError(
            f"expected {EXPECTED_WARDS} eThekwini wards, found {len(eth)}; "
            "the ward product or the prefix assumption changed"
        )
    eth["ward_number"] = eth["ward_code"].str[-3:].astype(int)
    eth["municipality_code"] = "ETH"
    eth = eth.sort_values("ward_code").reset_index(drop=True)

    summary = {
        "source": SOURCE,
        "national_ward_count": national_wards,
        "municipality_code": "ETH",
        "ward_count": int(len(eth)),
        "population_total": round(float(eth["population_total"].sum()), 1),
        "boundary_ward_count": 110,
        "boundary_mismatch": (
            "Census 2022 ward product has 111 eThekwini wards; the ADM4 boundary "
            "layer has 110. No ward-level join is performed."
        ),
    }
    return eth, summary


def _read(path: Path, sheet: str) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name=sheet)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def _normalise(frame: pd.DataFrame, ward_column: str) -> pd.DataFrame:
    if ward_column not in frame.columns:
        raise RuntimeError(f"census sheet missing {ward_column!r} column")
    frame = frame.rename(columns={ward_column: "ward_code"})
    frame["ward_code"] = frame["ward_code"].astype(str).str.strip()
    # The final row is a national total, not a ward.
    frame = frame[frame["ward_code"].str.fullmatch(r"\d{8}")].copy()
    if frame["ward_code"].duplicated().any():
        raise RuntimeError("census sheet has duplicate ward codes")
    return frame


def _check_totals(frame: pd.DataFrame) -> None:
    group = pd.to_numeric(frame["population_total"], errors="coerce")
    sex = pd.to_numeric(frame["sex_total"], errors="coerce")
    age_columns = [c for c in frame.columns if c.startswith("age_") and c != "age_total"]
    age = frame[age_columns].apply(pd.to_numeric, errors="coerce").sum(axis=1)

    for name, series in (("population group", group), ("sex", sex), ("age", age)):
        if series.isna().any():
            raise RuntimeError(f"census {name} totals contain missing values")
        if (series < 0).any():
            raise RuntimeError(f"census {name} totals contain negative values")

    spread = pd.concat([group, sex, age], axis=1).max(axis=1) - pd.concat(
        [group, sex, age], axis=1
    ).min(axis=1)
    if float(spread.max()) > 1.0:
        raise RuntimeError(
            f"census cross-tab totals disagree by up to {float(spread.max()):.2f} persons"
        )
