"""Heat indicators.

Definitions are explicit and testable. Missing days are counted, not
interpolated; a year below the coverage threshold is withheld rather than
published with a caveat.
"""

from __future__ import annotations

import calendar

import pandas as pd

DAY_COUNT_COLUMNS = [
    "year",
    "days",
    "n_obs",
    "days_in_year",
    "coverage",
    "complete",
    "status",
]


def annual_extreme_day_counts(
    daily_tmax: pd.Series,
    *,
    threshold_c: float,
    min_coverage: float = 0.90,
) -> pd.DataFrame:
    """Count days per year where daily Tmax >= threshold.

    Args:
        daily_tmax: Series indexed by date (one value per calendar day).
        threshold_c: Absolute threshold in degrees Celsius. Comparison is
            inclusive: a value exactly at the threshold counts.
        min_coverage: Minimum fraction of the year's days with observations
            before the year is published.

    A year is published only if it is *complete* -- its observations span
    1 January to 31 December -- and meets ``min_coverage``. Coverage alone is
    not sufficient: a series that stops in November can still cover 90% of the
    year while being, unmistakably, not a full year.

    Returns:
        DataFrame with one row per year present in the input.
    """
    if daily_tmax.empty:
        return pd.DataFrame(columns=DAY_COUNT_COLUMNS)

    if not isinstance(daily_tmax.index, pd.DatetimeIndex):
        raise TypeError("daily_tmax must have a DatetimeIndex")

    series = daily_tmax.copy()
    series.index = series.index.tz_localize(None) if series.index.tz is not None else series.index
    series = series.sort_index()

    if series.index.has_duplicates:
        duplicates = list(series.index[series.index.duplicated()].unique()[:5])
        raise ValueError(f"duplicate dates in daily series: {duplicates}")

    series = pd.to_numeric(series, errors="coerce")

    if series.empty:
        return pd.DataFrame(columns=DAY_COUNT_COLUMNS)

    frame = pd.DataFrame({"tmax": series, "year": series.index.year})
    grouped = frame.groupby("year", sort=True)["tmax"]

    result = pd.DataFrame(
        {
            "days": grouped.apply(lambda s: int((s >= threshold_c).sum())),
            "n_obs": grouped.apply(lambda s: int(s.notna().sum())),
            # Completeness is about the observation window, not the count:
            # a series that stops in November is not a calendar year even if
            # every day it contains has a value.
            "complete": grouped.apply(
                lambda s: (s.index.min().month, s.index.min().day) == (1, 1)
                and (s.index.max().month, s.index.max().day) == (12, 31)
            ),
        }
    ).reset_index()

    result["days_in_year"] = result["year"].map(
        lambda y: 366 if calendar.isleap(int(y)) else 365
    )
    result["coverage"] = result["n_obs"] / result["days_in_year"]
    result["complete"] = result["complete"].astype(bool)
    result["status"] = [
        "ok" if complete and cov >= min_coverage else "withheld"
        for cov, complete in zip(result["coverage"], result["complete"], strict=True)
    ]
    return result[DAY_COUNT_COLUMNS]


def area_weighted_mean(values: list[float], weights: list[float]) -> float:
    """Weighted mean, ignoring pairs where the value is not published."""
    total_weight = 0.0
    total = 0.0
    for value, weight in zip(values, weights, strict=True):
        if value is None or pd.isna(value):
            continue
        total += float(value) * float(weight)
        total_weight += float(weight)
    if total_weight <= 0:
        raise ValueError("no published values to aggregate")
    return total / total_weight
