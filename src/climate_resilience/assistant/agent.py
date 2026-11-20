"""The assistant: one model, two tool families, a hard budget.

The budget is not advice in a prompt. ``UsageLimits(request_limit=2,
tool_calls_limit=3)`` is enforced by the runtime, because Pydantic AI's default
is a tool loop and a loop is what the specification forbids.

Two calls is exactly the design: the first request selects tools, the second
synthesises from their results. A model that wants a third round is stopped and
the run is reported as incomplete rather than silently costing more.

The answer is post-checked for the flood caveat. That is belt-and-braces: the
prompt requires it, but a prompt is not a guarantee.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Caching
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from sqlalchemy import Engine

from ..config import Settings
from ..store import repository
from ..tools import mart_tools
from ..tools.models import ToolOutput
from .guard import preflight
from .models import (
    Answer,
    AssistantResult,
    DocumentHit,
    DocumentResult,
    Measurement,
    MeasurementResult,
)
from .prompts import SYSTEM_PROMPT

MAX_ENVELOPES = 10
MAX_DOCUMENTS = 6
MAX_REQUESTS = 2
MAX_TOOL_CALLS = 3

FLOOD_CAVEAT = (
    "Caveat: riverine and coastal flooding only. Pluvial (surface-water) "
    "flooding is not modelled."
)


@dataclass
class ToolDeps:
    engine: Engine
    search: Callable[[str, str | None, int], DocumentResult]
    # Everything a tool returned this run, for the post-check. Not sent to the
    # model; it is the ground truth the answer is checked against.
    seen: list[Measurement] = field(default_factory=list)


def default_model() -> str:
    """Model id from the environment, with the provider prefix applied once."""
    model = os.environ.get("LLM_MODEL_SYNTHESIS") or os.environ.get("LLM_MODEL_INTENT")
    if not model:
        raise RuntimeError(
            "No model configured. Set LLM_MODEL_SYNTHESIS (and OPENROUTER_API_KEY) "
            "in .env or the environment."
        )
    return model if ":" in model else f"openrouter:{model}"


def document_search(settings: Settings) -> Callable[[str, str | None, int], DocumentResult]:
    """pgvector-backed search, connected lazily so a mart-only run never touches it."""

    def search(query: str, scope_id: str | None, limit: int) -> DocumentResult:
        from ..rag.embeddings import get_embedder
        from ..rag.retrieval import hybrid_search
        from ..rag.store import connect

        try:
            connection = connect(settings.documents_dsn)
        except Exception as exc:  # noqa: BLE001 - reported as a typed result
            return DocumentResult.nothing(f"document index unavailable: {exc}")
        try:
            hits = hybrid_search(
                connection, get_embedder(), query, k=limit, scope_id=scope_id
            )
        finally:
            connection.close()
        if not hits:
            return DocumentResult.nothing(
                "no document text matched; the corpus may not cover this topic"
            )
        return DocumentResult(
            hits=[
                DocumentHit(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    page_no=hit.page_no,
                    headings=list(hit.headings),
                    scope_level=hit.scope_level,
                    scope_ids=list(hit.scope_ids),
                    text=hit.text,
                    score=hit.score,
                )
                for hit in hits
            ]
        )

    return search


def build_agent(model: str | None = None) -> Agent[ToolDeps, Answer]:
    agent: Agent[ToolDeps, Answer] = Agent(
        model or default_model(),
        name="climate_resilience_agent",
        deps_type=ToolDeps,
        output_type=Answer,
        instructions=SYSTEM_PROMPT,
        capabilities=[Caching()],
    )
    _register(agent)
    return agent


def _register(agent: Agent[ToolDeps, Answer]) -> None:
    @agent.tool
    def get_indicator(
        ctx: RunContext[ToolDeps],
        indicator_id: str,
        scope_id: str | None = None,
        mechanism: str | None = None,
        return_period_years: int | None = None,
        period_year: int | None = None,
    ) -> MeasurementResult:
        """Published values for one indicator and scope.

        indicator_id must be one of: hot_days_tmax_ge_35c,
        population_count_worldpop, flood_exposed_area_pct,
        flood_exposed_population. For flood indicators, pass mechanism
        ("riverine" or "coastal") and return_period_years (10, 50 or 100).
        """
        output = mart_tools.get_indicator(
            ctx.deps.engine,
            indicator_id=indicator_id,
            scope_id=scope_id,
            mechanism=mechanism,
            return_period_years=return_period_years,
            period_year=period_year,
        )
        return _measurements(output, ctx.deps)

    @agent.tool
    def rank_scopes(
        ctx: RunContext[ToolDeps],
        indicator_id: str,
        limit: int = 10,
        order: str = "desc",
        mechanism: str | None = None,
        return_period_years: int | None = None,
        period_year: int | None = None,
    ) -> MeasurementResult:
        """Rank wards or grid cells by an indicator, highest first by default.

        Use this for "which wards have the most / least". A flood ranking
        requires return_period_years. Riverine and coastal are always ranked
        separately and must never be combined.
        """
        output = mart_tools.rank_scopes(
            ctx.deps.engine,
            indicator_id=indicator_id,
            limit=limit,
            order=order,
            mechanism=mechanism,
            return_period_years=return_period_years,
            period_year=period_year,
        )
        return _measurements(output, ctx.deps)

    @agent.tool
    def resolve_scope(ctx: RunContext[ToolDeps], query: str) -> ToolOutput:
        """Turn "ward 75", a ward id or a place name into a published scope id."""
        return mart_tools.resolve_scope(ctx.deps.engine, query=query)

    @agent.tool
    def coverage(ctx: RunContext[ToolDeps]) -> ToolOutput:
        """List the indicators, periods, mechanisms and return periods available.

        Call this before concluding that something is unavailable, so the
        refusal names what does exist.
        """
        return mart_tools.coverage(ctx.deps.engine)

    @agent.tool
    def explain(ctx: RunContext[ToolDeps], row_key: str) -> MeasurementResult:
        """Full provenance for one published row, including its warnings."""
        output = mart_tools.explain(ctx.deps.engine, row_key=row_key)
        return _measurements(output, ctx.deps)

    @agent.tool
    def search_documents(
        ctx: RunContext[ToolDeps],
        query: str,
        scope_id: str | None = None,
        limit: int = 5,
    ) -> DocumentResult:
        """Search municipal plans and strategies for what they say about a topic.

        Returns prose with document id, page and headings. This is evidence of
        what a document states, never of a measured value. A hit labelled
        scope_level "municipality" is city-wide and says nothing about a ward.
        """
        return ctx.deps.search(query, scope_id, max(1, min(limit, MAX_DOCUMENTS)))


def _measurements(output: ToolOutput, deps: ToolDeps) -> MeasurementResult:
    if not output.ok:
        return MeasurementResult(
            status="insufficient",
            message=output.message,
            missing=output.missing,
            available=output.available,
        )
    measurements = [
        Measurement.from_envelope(row_key, envelope)
        for row_key, envelope in zip(
            output.row_keys, output.envelopes, strict=True
        )
    ]
    truncated = len(measurements) > MAX_ENVELOPES
    if truncated:
        measurements = measurements[:MAX_ENVELOPES]
    deps.seen.extend(measurements)
    message = output.message
    if truncated:
        note = (
            f"showing {MAX_ENVELOPES} rows; narrow the request for the rest"
        )
        message = f"{message}; {note}" if message else note
    return MeasurementResult(measurements=measurements, message=message)


def ask(
    settings: Settings,
    question: str,
    *,
    model: str | Model | None = None,
    deps: ToolDeps | None = None,
) -> AssistantResult:
    refusal = preflight(question)
    if refusal is not None:
        return AssistantResult(
            question=question,
            answer=Answer(
                text=refusal.text,
                abstained=True,
                missing=refusal.missing,
            ),
            refused_by_guard=True,
        )

    if model is None and not os.environ.get("OPENROUTER_API_KEY"):
        return AssistantResult(
            question=question,
            answer=Answer(
                text=(
                    "The assistant is not configured: OPENROUTER_API_KEY is unset, "
                    "so no model call was made."
                ),
                abstained=True,
                missing=["OPENROUTER_API_KEY in the environment"],
            ),
            error="missing OPENROUTER_API_KEY",
        )

    deps = deps or ToolDeps(
        engine=repository.make_engine(settings.database_url),
        search=document_search(settings),
    )

    try:
        result = build_agent(model).run_sync(
            question,
            deps=deps,
            usage_limits=UsageLimits(
                request_limit=MAX_REQUESTS, tool_calls_limit=MAX_TOOL_CALLS
            ),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a typed result
        return AssistantResult(
            question=question,
            answer=Answer(
                text=(
                    "The assistant could not complete this question within its "
                    f"budget or the run failed ({type(exc).__name__})."
                ),
                abstained=True,
                missing=["a completed tool run within 2 model requests"],
            ),
            error=f"{type(exc).__name__}: {exc}",
        )

    answer = _with_flood_caveat(result.output, deps.seen)
    usage = result.usage
    return AssistantResult(
        question=question,
        answer=answer,
        requests=int(getattr(usage, "requests", 0) or 0),
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def _with_flood_caveat(answer: Answer, seen: list[Measurement]) -> Answer:
    """A flood answer without the mechanism caveat is not a valid answer."""
    if answer.abstained:
        return answer
    if not any(measurement.hazard_type == "flood" for measurement in seen):
        return answer
    if "pluvial" in answer.text.lower():
        return answer
    return answer.model_copy(update={"text": f"{answer.text}\n\n{FLOOD_CAVEAT}"})
