"""Structured assistant output.

The answer model is where grounding stops being a prompt instruction. A
non-abstained answer cannot be constructed without at least one citation, and
an abstention cannot be constructed without naming what is missing. The model
can still be wrong; it cannot be silently unsourced.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..envelope import EvidenceEnvelope
from ..tools.models import Available

CitationKind = Literal["measurement", "document"]


class Citation(BaseModel):
    kind: CitationKind
    """``measurement`` is a mart row_key; ``document`` is a chunk id."""

    reference: str
    note: str | None = None


class Answer(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    missing: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _grounded(self) -> Answer:
        if not self.abstained and not self.citations:
            raise ValueError(
                "a non-abstained answer must cite a measurement or a document"
            )
        if self.abstained and not self.missing:
            raise ValueError(
                "an abstention must state what is missing; 'I don't know' is not enough"
            )
        return self


class DocumentHit(BaseModel):
    chunk_id: str
    document_id: str
    page_no: int | None = None
    headings: list[str] = Field(default_factory=list)
    scope_level: str
    scope_ids: list[str] = Field(default_factory=list)
    text: str
    score: float


class Measurement(BaseModel):
    """A published value, trimmed to what an answer may restate and cite.

    The full envelope stays in the mart and is reachable with ``explain``. This
    projection keeps the citation key, the parameters that change the meaning
    (mechanism, return period, threshold, period) and the licences, and drops
    the fields a reader never needs per row.
    """

    row_key: str
    indicator_id: str
    method_id: str
    method_version: str
    value: float
    unit: str
    scope_level: str
    scope_id: str
    scope_name: str
    period_start: str
    period_end: str
    hazard_type: str
    mechanism: str | None = None
    return_period_years: int | None = None
    depth_threshold_m: float | None = None
    basis: str
    dataset_versions: list[str] = Field(default_factory=list)
    licences: list[str] = Field(default_factory=list)
    native_resolution: str
    coverage_pct: float
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_envelope(cls, row_key: str, envelope: EvidenceEnvelope) -> Measurement:
        return cls(
            row_key=row_key,
            indicator_id=envelope.indicator_id,
            method_id=envelope.method_id,
            method_version=envelope.method_version,
            value=envelope.value,
            unit=envelope.unit,
            scope_level=envelope.scope.level,
            scope_id=envelope.scope.id,
            scope_name=envelope.scope.name,
            period_start=envelope.period.start.isoformat(),
            period_end=envelope.period.end.isoformat(),
            hazard_type=envelope.hazard_type,
            mechanism=envelope.mechanism,
            return_period_years=envelope.return_period_years,
            depth_threshold_m=envelope.depth_threshold_m,
            basis=envelope.period.basis,
            dataset_versions=[dataset.version for dataset in envelope.datasets],
            licences=[dataset.licence for dataset in envelope.datasets],
            native_resolution=envelope.quality.native_resolution,
            coverage_pct=envelope.quality.coverage_pct,
            warnings=list(envelope.quality.warnings),
        )


class MeasurementResult(BaseModel):
    status: Literal["ok", "insufficient"] = "ok"
    measurements: list[Measurement] = Field(default_factory=list)
    message: str | None = None
    missing: list[str] = Field(default_factory=list)
    available: Available | None = None


class DocumentResult(BaseModel):
    status: Literal["ok", "insufficient"] = "ok"
    hits: list[DocumentHit] = Field(default_factory=list)
    message: str | None = None

    @classmethod
    def nothing(cls, reason: str) -> DocumentResult:
        return cls(status="insufficient", message=reason)


class AssistantResult(BaseModel):
    question: str
    answer: Answer
    refused_by_guard: bool = False
    # Which model actually served the run. With a fallback chain this is not
    # knowable from configuration, and a latency figure is meaningless without
    # it.
    model: str | None = None
    seconds: float = 0.0
    cost_usd: float | None = None
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    available: Available | None = None
    error: str | None = None
