"""Indicator registry.

Every published number comes from a registered definition. Definitions are
versioned: changing a method means a new version, so old results stay
interpretable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..envelope import HazardType


@dataclass(frozen=True)
class IndicatorSpec:
    indicator_id: str
    hazard_type: HazardType
    unit: str
    description: str
    method_id: str
    method_version: str
    default_threshold: float | None = None
    citation: str = ""


HEAT_SPEC = IndicatorSpec(
    indicator_id="hot_days_tmax_ge_35c",
    hazard_type="heat",
    unit="days",
    description="Number of days per calendar year with daily maximum temperature >= threshold",
    method_id="annual_extreme_day_count",
    method_version="1.0.0",
    default_threshold=35.0,
    citation="ETCCDI warm-day variant; threshold fixed at 35 degC (absolute, not percentile)",
)

POPULATION_SPEC = IndicatorSpec(
    indicator_id="population_count_worldpop",
    hazard_type="none",
    unit="persons",
    description="Resident population allocated to a scope from the WorldPop 1 km grid",
    method_id="worldpop_areal_allocation",
    method_version="1.0.0",
    citation="WorldPop 2020 UN-adjusted, 1 km aggregated, CC BY 4.0",
)

REGISTRY: dict[str, IndicatorSpec] = {
    HEAT_SPEC.indicator_id: HEAT_SPEC,
    POPULATION_SPEC.indicator_id: POPULATION_SPEC,
}


def get(indicator_id: str) -> IndicatorSpec:
    try:
        return REGISTRY[indicator_id]
    except KeyError as exc:
        raise KeyError(f"indicator not registered: {indicator_id}") from exc
