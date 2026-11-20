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

FLOOD_AREA_SPEC = IndicatorSpec(
    indicator_id="flood_exposed_area_pct",
    hazard_type="flood",
    unit="percent",
    description="Share of a scope's area with modelled inundation depth at or above the threshold",
    method_id="aqueduct_inundation_area_share",
    method_version="1.0.0",
    default_threshold=0.0,
    citation="WRI Aqueduct Floods v2 hazard maps; riverine and coastal only, never summed",
)

FLOOD_POPULATION_SPEC = IndicatorSpec(
    indicator_id="flood_exposed_population",
    hazard_type="flood",
    unit="persons",
    description=(
        "WorldPop persons in 1 km hazard cells with inundation depth at or above "
        "the threshold"
    ),
    method_id="aqueduct_population_in_zone",
    method_version="1.0.0",
    default_threshold=0.0,
    citation="WRI Aqueduct Floods v2 hazard maps; population areally interpolated from WorldPop",
)

REGISTRY: dict[str, IndicatorSpec] = {
    HEAT_SPEC.indicator_id: HEAT_SPEC,
    POPULATION_SPEC.indicator_id: POPULATION_SPEC,
    FLOOD_AREA_SPEC.indicator_id: FLOOD_AREA_SPEC,
    FLOOD_POPULATION_SPEC.indicator_id: FLOOD_POPULATION_SPEC,
}


def get(indicator_id: str) -> IndicatorSpec:
    try:
        return REGISTRY[indicator_id]
    except KeyError as exc:
        raise KeyError(f"indicator not registered: {indicator_id}") from exc
