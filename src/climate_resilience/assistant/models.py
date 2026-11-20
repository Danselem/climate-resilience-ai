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
    """``measurement`` is a mart row_key; ``document`` is a chunk id.

    There is deliberately no free-text ``note``. Models filled it with a
    sentence per citation, which was a third of the output tokens and added
    nothing the envelope does not already hold.
    """

    reference: str


class Answer(BaseModel):
    """What the model produces: prose and, if it must refuse, the gap.

    Citations are deliberately absent. Asking the model to transcribe row_keys
    cost ~150 output tokens per answer and produced a retry whenever it forgot,
    which is a validation failure caused by asking the wrong component to do
    the work. Citations are derived from the evidence the run actually used.
    """

    text: str
    abstained: bool = False
    missing: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refusal_names_the_gap(self) -> Answer:
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
    """One published value, trimmed to what an answer may restate and cite.

    Provenance that is identical for every row -- method, datasets, licences,
    resolution and caveats -- is hoisted to the response, because repeating it
    per row was 37% of the prompt and identical every time.
    """

    row_key: str
    indicator_id: str
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
    coverage_pct: float

    @classmethod
    def from_envelope(cls, row_key: str, envelope: EvidenceEnvelope) -> Measurement:
        return cls(
            row_key=row_key,
            indicator_id=envelope.indicator_id,
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
            coverage_pct=envelope.quality.coverage_pct,
        )


class Source(BaseModel):
    """A dataset behind the values, stated once."""

    id: str
    version: str
    licence: str


class MethodRef(BaseModel):
    id: str
    version: str


class MeasurementResult(BaseModel):
    status: Literal["ok", "insufficient"] = "ok"
    measurements: list[Measurement] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    method: MethodRef | None = None
    native_resolution: str | None = None
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
    citations: list[Citation] = Field(default_factory=list)
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
