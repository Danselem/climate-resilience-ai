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
import threading
import time
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
from . import pricing
from .guard import preflight
from .models import (
    Answer,
    AssistantResult,
    Citation,
    DocumentHit,
    DocumentResult,
    Measurement,
    MeasurementResult,
    MethodRef,
    Source,
)
from .prompts import SYSTEM_PROMPT

MAX_ROWS = 5
# The specification caps output at 300 tokens; 500 leaves room for the caveat
# without letting a model write an essay that doubles latency.
MAX_OUTPUT_TOKENS = 1200
MAX_DOCUMENTS = 6
# A ceiling, not a target: most questions finish in two. It is three because a
# model that self-corrects would otherwise fail outright, and a third call
# costs ~$0.0001.
MAX_REQUESTS = 3
MAX_TOOL_CALLS = 3

# A free endpoint first, because it is free and it works; a cheap paid model
# second, because free endpoints disappear without notice. Both are OpenRouter
# ids and both are priced at run time.
#
# Ordered by measured latency, not by price. nova-micro finishes a question in
# 1.6-3.8 s on 2 requests for ~$0.0002; particle-1 is free but 10-18 s. The
# free endpoint stays as the fallback because it costs nothing when it is
# healthy, not because it is fast.
#
# Both were verified to finish within the request budget. That is not a
# property of price or of tool-calling support: mistral-nemo and llama-3.1-8b
# both call tools correctly and still needed a third round, and gpt-oss-20b
# refused to call a tool at all. Model choice here has to be measured.
DEFAULT_MODELS = ("amazon/nova-micro-v1", "particle-ai/particle-1:free")

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
    documents: list[DocumentHit] = field(default_factory=list)


def default_model() -> str:
    """First configured model. Kept for callers that want one string."""
    return model_candidates()[0]


def model_candidates() -> list[str]:
    """Models to try in order, each with an explicit provider prefix.

    ``LLM_MODELS`` is a comma-separated list. A single ``LLM_MODEL_SYNTHESIS``
    and the built-in pair are the fallbacks. Free endpoints disappear without
    notice, so the list is the unit of configuration, not one model id.
    """
    raw = os.environ.get("LLM_MODELS")
    if raw:
        names = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        single = os.environ.get("LLM_MODEL_SYNTHESIS") or os.environ.get("LLM_MODEL_INTENT")
        names = [single] if single else list(DEFAULT_MODELS)
    return [_qualify(name) for name in names]


def _qualify(name: str) -> str:
    """Add ``openrouter:`` unless a provider prefix is already present.

    ``particle-ai/particle-1:free`` contains a colon that is part of the model
    id, not a provider prefix, so the test is whether the text before the first
    colon looks like a provider (no slash).
    """
    head, separator, _ = name.partition(":")
    if separator and "/" not in head:
        return name
    return f"openrouter:{name}"


def _model_chain(candidates: list[str]) -> str | Model:
    if len(candidates) == 1:
        return candidates[0]
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(candidates[0], *candidates[1:])


_warm_lock = threading.Lock()
_warm_started = False


def warm_documents() -> None:
    """Load the embedding model in the background, once per process."""

    def _load() -> None:
        try:
            from ..rag.embeddings import get_embedder

            get_embedder()
        except Exception:  # noqa: BLE001 - a failed warm-up is not fatal
            pass

    global _warm_started
    with _warm_lock:
        if _warm_started:
            return
        _warm_started = True
    threading.Thread(target=_load, daemon=True, name="embedder-warmup").start()


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


def _model_settings() -> dict[str, object] | None:
    """OpenRouter routing preferences.

    Default routing balances price, latency and reliability; ``sort`` pins one.
    It is configurable because pinning latency can route to a provider that is
    faster per token and worse per tool call, which is a regression, not an
    optimisation.
    """
    settings: dict[str, object] = {"max_tokens": MAX_OUTPUT_TOKENS}
    sort = os.environ.get("LLM_PROVIDER_SORT", "latency").strip()
    if sort:
        settings["extra_body"] = {"provider": {"sort": sort}}
    return settings


def build_agent(
    model: str | Model | list[str] | None = None,
) -> Agent[ToolDeps, Answer]:
    if model is None:
        resolved: str | Model = _model_chain(model_candidates())
    elif isinstance(model, list):
        resolved = _model_chain(model)
    else:
        resolved = model
    agent: Agent[ToolDeps, Answer] = Agent(
        resolved,
        name="climate_resilience_agent",
        deps_type=ToolDeps,
        output_type=Answer,
        instructions=SYSTEM_PROMPT,
        capabilities=[Caching()],
        model_settings=_model_settings(),
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

        For a single year of a heat series pass period_year; omit it to get the
        whole series. Format values are already exact: do not re-query to check.
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
        limit: int = 5,
        order: str = "desc",
        mechanism: str | None = None,
        return_period_years: int | None = None,
        period_year: int | None = None,
    ) -> MeasurementResult:
        """Rank wards or grid cells by an indicator, highest first by default.

        Use this for "which wards have the most / least". A flood ranking
        requires return_period_years. Riverine and coastal are always ranked
        separately and must never be combined.

        Do not pass period_year: rankings use the latest published period, and
        a flood layer has exactly one baseline period. One call is enough.
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
        result = ctx.deps.search(query, scope_id, max(1, min(limit, MAX_DOCUMENTS)))
        ctx.deps.documents.extend(result.hits)
        return result


def _measurements(output: ToolOutput, deps: ToolDeps) -> MeasurementResult:
    """Project a tool result into the prompt-sized shape.

    Caveats, sources, method and resolution are identical across rows, so they
    are sent once. Repeating them per row was 37% of the prompt.
    """
    if not output.ok:
        return MeasurementResult(
            status="insufficient",
            message=output.message,
            missing=output.missing,
            available=output.available,
        )

    pairs = list(zip(output.row_keys, output.envelopes, strict=True))
    truncated = len(pairs) > MAX_ROWS
    if truncated:
        pairs = pairs[:MAX_ROWS]

    caveats: list[str] = []
    sources: dict[tuple[str, str, str], Source] = {}
    method: MethodRef | None = None
    resolution: str | None = None
    measurements: list[Measurement] = []

    for row_key, envelope in pairs:
        measurements.append(Measurement.from_envelope(row_key, envelope))
        for warning in envelope.quality.warnings:
            if warning not in caveats:
                caveats.append(warning)
        for dataset in envelope.datasets:
            sources[(dataset.id, dataset.version, dataset.licence)] = Source(
                id=dataset.id, version=dataset.version, licence=dataset.licence
            )
        method = method or MethodRef(
            id=envelope.method_id, version=envelope.method_version
        )
        resolution = resolution or envelope.quality.native_resolution

    deps.seen.extend(measurements)
    message = output.message
    if truncated:
        note = (
            f"showing {MAX_ROWS} of {len(output.envelopes)} rows; "
            "narrow the request for the rest"
        )
        message = f"{message}; {note}" if message else note
    return MeasurementResult(
        measurements=measurements,
        caveats=caveats,
        sources=list(sources.values()),
        method=method,
        native_resolution=resolution,
        message=message,
    )


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

    # Loading the embedding model costs ~8 s. Starting it now overlaps that
    # with the first model call instead of stalling the document tool.
    warm_documents()

    started = time.perf_counter()
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
            seconds=round(time.perf_counter() - started, 3),
            error=f"{type(exc).__name__}: {exc}",
        )

    seconds = time.perf_counter() - started
    answer = _with_flood_caveat(result.output, deps.seen)
    citations = _citations(deps)
    usage = result.usage
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    served = getattr(result.response, "model_name", None)
    return AssistantResult(
        question=question,
        answer=answer,
        citations=citations,
        model=served,
        seconds=round(seconds, 3),
        cost_usd=pricing.estimate_cost(served, input_tokens, output_tokens),
        requests=int(getattr(usage, "requests", 0) or 0),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _citations(deps: ToolDeps) -> list[Citation]:
    """Every measurement and document the run actually used, in order.

    The model does not transcribe identifiers: it is the least reliable place
    to keep them and the most expensive to correct.
    """
    citations = [
        Citation(kind="measurement", reference=measurement.row_key)
        for measurement in deps.seen
    ]
    seen: set[str] = set()
    for hit in deps.documents:
        if hit.chunk_id in seen:
            continue
        seen.add(hit.chunk_id)
        citations.append(Citation(kind="document", reference=hit.chunk_id))
    return citations


def _with_flood_caveat(answer: Answer, seen: list[Measurement]) -> Answer:
    """A flood answer without the mechanism caveat is not a valid answer."""
    if answer.abstained:
        return answer
    if not any(measurement.hazard_type == "flood" for measurement in seen):
        return answer
    if "pluvial" in answer.text.lower():
        return answer
    return answer.model_copy(update={"text": f"{answer.text}\n\n{FLOOD_CAVEAT}"})
