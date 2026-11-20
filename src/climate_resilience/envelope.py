"""The evidence envelope.

One structure for every published number. Traceability, citation and
abstention all follow from it: if a field is null, the answer must say so
rather than fill the gap.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Basis = Literal["observation", "reanalysis", "projection", "modelled_estimate", "derived"]
HazardType = Literal["heat", "flood", "fire", "drought", "none"]
Mechanism = Literal["riverine", "coastal"]
ScopeLevel = Literal["ward", "municipality", "grid_cell"]


class Scope(BaseModel):
    level: ScopeLevel
    id: str
    name: str
    geometry_ref: str | None = None


class Period(BaseModel):
    start: date
    end: date
    basis: Basis

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end < self.start:
            raise ValueError("period end precedes start")
        return self


class DatasetRef(BaseModel):
    id: str
    version: str
    checksum: str
    source_url: str
    licence: str


class Uncertainty(BaseModel):
    type: str
    lower: float
    upper: float


class Quality(BaseModel):
    n_samples: int
    coverage_pct: float
    missing_pct: float
    native_resolution: str
    warnings: list[str] = Field(default_factory=list)


class RunRef(BaseModel):
    git_commit: str
    run_id: str
    created_at: datetime
    inputs_hash: str


class EvidenceEnvelope(BaseModel):
    """A single published metric with full provenance."""

    value: float
    unit: str

    indicator_id: str
    method_id: str
    method_version: str

    hazard_type: HazardType
    return_period_years: int | None = None
    depth_threshold_m: float | None = None
    mechanism: Mechanism | None = None

    scope: Scope
    period: Period

    scenario: str | None = None
    model: str | None = None
    baseline_period: Period | None = None

    datasets: list[DatasetRef]
    uncertainty: Uncertainty | None = None
    quality: Quality
    run: RunRef

    @model_validator(mode="after")
    def _hazard_contract(self) -> EvidenceEnvelope:
        """I4: a flood value is meaningless without its mechanism and parameters."""
        if self.hazard_type == "flood":
            missing = [
                name
                for name, val in (
                    ("return_period_years", self.return_period_years),
                    ("depth_threshold_m", self.depth_threshold_m),
                    ("mechanism", self.mechanism),
                )
                if val is None
            ]
            if missing:
                raise ValueError(f"flood envelope missing required fields: {', '.join(missing)}")
        else:
            if any(
                v is not None
                for v in (self.return_period_years, self.depth_threshold_m, self.mechanism)
            ):
                raise ValueError("flood parameters set on a non-flood envelope")
        return self

    @model_validator(mode="after")
    def _projection_contract(self) -> EvidenceEnvelope:
        """I3: a projection must declare scenario, model and baseline."""
        if self.period.basis == "projection":
            if self.scenario is None or self.model is None or self.baseline_period is None:
                raise ValueError(
                    "projection requires scenario, model and baseline_period"
                )
        elif self.scenario is not None or self.model is not None:
            raise ValueError("scenario/model set on a non-projection envelope")
        return self


class InsufficientData(BaseModel):
    """Typed refusal. Returned instead of a number, never raised for control flow."""

    reason: Literal[
        "unknown_scope",
        "unknown_indicator",
        "outside_coverage",
        "low_coverage",
        "unregistered_dataset",
        "pluvial_not_modelled",
        "ambiguous_scope",
    ]
    message: str
    indicator_id: str | None = None
    scope: Scope | None = None


def now_utc() -> datetime:
    return datetime.now(UTC)
