"""Typed tool contracts.

A tool either returns evidence or a typed refusal that names what is missing.
It never raises an error the model has to interpret, and it never returns a
bare number: the envelope travels with the value, so a citation can name the
dataset, its licence, the method and the run.

The alternative -- returning a float and trusting the prompt to add provenance
-- is how a plausible but unsourced figure reaches a report.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..envelope import EvidenceEnvelope


class ScopeRef(BaseModel):
    level: Literal["ward", "municipality", "grid_cell"]
    id: str
    name: str
    ward_number: int | None = None
    area_km2: float | None = None


class Available(BaseModel):
    """What the mart actually holds, so a refusal can be specific."""

    indicators: list[str] = Field(default_factory=list)
    scope_levels: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    mechanisms: list[str] = Field(default_factory=list)
    return_periods: list[int] = Field(default_factory=list)
    rows: int = 0


class ToolOutput(BaseModel):
    status: Literal["ok", "insufficient"] = "ok"
    envelopes: list[EvidenceEnvelope] = Field(default_factory=list)
    scopes: list[ScopeRef] = Field(default_factory=list)
    available: Available | None = None
    message: str | None = None
    missing: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @classmethod
    def insufficient(
        cls,
        reason: str,
        *,
        missing: list[str] | None = None,
        available: Available | None = None,
    ) -> ToolOutput:
        return cls(
            status="insufficient",
            message=reason,
            missing=missing or [],
            available=available,
        )

    @classmethod
    def evidence(
        cls, envelopes: list[EvidenceEnvelope], *, message: str | None = None
    ) -> ToolOutput:
        if not envelopes:
            return cls.insufficient("no published row matches the request")
        return cls(status="ok", envelopes=envelopes, message=message)
