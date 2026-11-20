"""Indicator correctness: reference values, boundaries and withholding."""

from __future__ import annotations

import pandas as pd
import pytest

from climate_resilience.indicators.heat import annual_extreme_day_counts, area_weighted_mean


def series(values: dict[str, list[float]]) -> pd.Series:
    """Build a daily series from {year: [values]} with a complete calendar."""
    parts = []
    for year_text, daily in values.items():
        year = int(year_text)
        index = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        assert len(index) == len(daily), "one value per day required"
        parts.append(pd.Series(daily, index=index))
    return pd.concat(parts)


def test_counts_days_at_or_above_threshold() -> None:
    year = 2021
    index = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    values = [34.9] * len(index)
    for position in (10, 11, 12):
        values[position] = 35.0  # exactly at threshold counts
    for position in (20, 21):
        values[position] = 41.2

    result = annual_extreme_day_counts(pd.Series(values, index=index), threshold_c=35.0)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["days"] == 5
    assert row["n_obs"] == 365
    assert row["status"] == "ok"


def test_leap_year_uses_366_day_denominator() -> None:
    index = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    result = annual_extreme_day_counts(pd.Series(30.0, index=index), threshold_c=35.0)
    assert result.iloc[0]["days_in_year"] == 366


def test_missing_days_are_counted_not_interpolated() -> None:
    index = pd.date_range("2021-01-01", "2021-12-31", freq="D")
    values = pd.Series(30.0, index=index)
    values.iloc[:100] = float("nan")

    result = annual_extreme_day_counts(values, threshold_c=35.0, min_coverage=0.90)
    row = result.iloc[0]

    assert row["n_obs"] == 265
    assert row["coverage"] == pytest.approx(265 / 365)
    assert row["status"] == "withheld"


def test_low_coverage_threshold_is_configurable() -> None:
    index = pd.date_range("2021-01-01", "2021-12-31", freq="D")
    values = pd.Series(30.0, index=index)
    values.iloc[:100] = float("nan")

    result = annual_extreme_day_counts(values, threshold_c=35.0, min_coverage=0.70)
    assert result.iloc[0]["status"] == "ok"


def test_multiple_years_are_separate_rows() -> None:
    frame = series({"2020": [36.0] * 366, "2021": [30.0] * 365})
    result = annual_extreme_day_counts(frame, threshold_c=35.0)
    assert list(result["year"]) == [2020, 2021]
    assert list(result["days"]) == [366, 0]


def test_unsorted_index_is_sorted_before_counting() -> None:
    index = pd.date_range("2021-01-01", "2021-12-31", freq="D")
    values = pd.Series(30.0, index=index)
    values.iloc[[100, 200, 300]] = 40.0
    shuffled = values.sample(frac=1.0, random_state=0)

    result = annual_extreme_day_counts(shuffled, threshold_c=35.0)
    assert result.iloc[0]["days"] == 3


def test_duplicate_dates_fail_loudly() -> None:
    index = pd.date_range("2021-01-01", "2021-12-31", freq="D")
    values = pd.Series(30.0, index=index)
    duplicated = pd.concat([values, pd.Series([40.0], index=[pd.Timestamp("2021-06-01")])])

    with pytest.raises(ValueError, match="duplicate dates"):
        annual_extreme_day_counts(duplicated, threshold_c=35.0)


def test_empty_series_returns_empty_frame() -> None:
    result = annual_extreme_day_counts(pd.Series(dtype="float64"), threshold_c=35.0)
    assert result.empty
    assert list(result.columns) == [
        "year",
        "days",
        "n_obs",
        "days_in_year",
        "coverage",
        "status",
    ]


def test_requires_datetime_index() -> None:
    with pytest.raises(TypeError):
        annual_extreme_day_counts(pd.Series([35.0, 36.0]), threshold_c=35.0)


def test_area_weighted_mean_skips_unpublished_cells() -> None:
    assert area_weighted_mean([10.0, None, 20.0], [1.0, 1.0, 1.0]) == pytest.approx(15.0)


def test_area_weighted_mean_respects_weights() -> None:
    assert area_weighted_mean([10.0, 20.0], [3.0, 1.0]) == pytest.approx(12.5)


def test_area_weighted_mean_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        area_weighted_mean([None], [1.0])
