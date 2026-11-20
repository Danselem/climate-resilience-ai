"""Census ward population: official codes, validated totals, no geometry join."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from climate_resilience.ingestion.census import FILES, _parse


def codes(count: int = 111) -> list[str]:
    return [f"595{index:05d}" for index in range(1, count + 1)] + ["19100001"]


def workbooks(tmp_path: Path, *, sex_total_override: int | None = None) -> dict[str, Path]:
    ward_codes = codes()
    total = [100] * 111 + [50]
    if sex_total_override is not None:
        total[-1] = sex_total_override

    population = pd.DataFrame(
        {
            "Ward_Code": ward_codes,
            "Black African": [60] * 111 + [30],
            "Coloured": [10] * 111 + [5],
            "Indian/Asian": [10] * 111 + [5],
            "White": [10] * 111 + [5],
            "Other": [10] * 111 + [5],
            "Total": [100] * 111 + [50],
        }
    )
    sex = pd.DataFrame(
        {
            "WARD_CODE": ward_codes,
            "Male": [49] * 111 + [24],
            "Female": [51] * 111 + [26],
            "Total": total,
        }
    )
    age = pd.DataFrame(
        {
            "Ward_Code": ward_codes,
            "0-4": [20] * 111 + [10],
            "5-9": [20] * 111 + [10],
            "10-14": [20] * 111 + [10],
            "15-19": [20] * 111 + [10],
            "20-24": [20] * 111 + [10],
            "Total": [100] * 111 + [50],
        }
    )

    frames = {"population_group": population, "sex": sex, "age_group": age}
    sheets = {"population_group": "Wards", "sex": "Wards_Sex", "age_group": "Age_group"}
    paths: dict[str, Path] = {}
    for label, frame in frames.items():
        path = tmp_path / FILES[label]
        frame.to_excel(path, sheet_name=sheets[label], index=False)
        paths[label] = path
    return paths


def test_only_ethekwini_wards_are_kept(tmp_path: Path) -> None:
    frame, summary = _parse(workbooks(tmp_path))

    assert len(frame) == 111
    assert summary["ward_count"] == 111
    assert summary["national_ward_count"] == 112
    assert summary["population_total"] == pytest.approx(11100.0)
    assert set(frame["ward_code"].str[:3]) == {"595"}
    assert frame["ward_number"].min() == 1
    assert frame["ward_number"].max() == 111


def test_the_boundary_mismatch_is_recorded_in_the_summary(tmp_path: Path) -> None:
    _, summary = _parse(workbooks(tmp_path))
    assert summary["boundary_ward_count"] == 110
    assert "111" in str(summary["boundary_mismatch"])
    assert "110" in str(summary["boundary_mismatch"])


def test_cross_tab_totals_must_agree(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="disagree"):
        _parse(workbooks(tmp_path, sex_total_override=200))


def test_workbooks_must_cover_the_same_ward_codes(tmp_path: Path) -> None:
    paths = workbooks(tmp_path)
    sex = pd.read_excel(paths["sex"], sheet_name="Wards_Sex")
    sex = sex.iloc[1:]
    sex.to_excel(paths["sex"], sheet_name="Wards_Sex", index=False)

    with pytest.raises(RuntimeError, match="disagree on ward codes"):
        _parse(paths)
