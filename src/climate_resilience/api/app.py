"""HTTP surface over the same typed tools the assistant uses.

The interface layer never computes a metric. Every endpoint calls one of the
functions in ``climate_resilience.tools`` and returns its result unchanged, with
the evidence envelope attached. That is what makes the API and the assistant
the same system rather than two implementations that can disagree.

Failure follows §9.2 of the specification: an unavailable value is a typed
``insufficient`` result, not an exception. A malformed parameter — a return
period that is not 10, 50 or 100 — is rejected by request validation with 422,
because no tool should have to defend itself against a type error.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from ..assistant.agent import ToolDeps, ask, document_search
from ..assistant.models import AssistantResult, DocumentResult
from ..config import Settings, get_settings
from ..store import repository
from ..tools import mart_tools
from ..tools.models import ToolOutput

logger = logging.getLogger("climate_resilience.api")

# A Literal of ints does not coerce from "100", so the closed set is checked by
# a dependency that raises 422 with a message a caller can act on.
RETURN_PERIODS = (10, 50, 100)
Mechanism = Literal["riverine", "coastal"]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    model: str | None = None


class ReportRequest(BaseModel):
    scope_id: str = Field(min_length=2)
    # Rendering inline keeps the pilot to one process. The queue exists for the
    # worker path and for SQS; nothing in the UI depends on which is used.
    process_now: bool = True


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    search: Callable[[str, str | None, int], DocumentResult] | None = None,
) -> FastAPI:
    """Build the app. Tests inject an engine; production builds one from settings."""
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved
        app.state.engine = engine or repository.make_engine(resolved.database_url)
        app.state.search = search or document_search(resolved)
        logger.info("api ready", extra={"database": resolved.database_url})
        yield

    app = FastAPI(
        title="Climate Resilience Intelligence Platform",
        version="0.1.0",
        summary="Published climate indicators for eThekwini, with provenance.",
        description=(
            "Every value is a precomputed mart row carrying its dataset versions, "
            "method, period, scope and caveats. Nothing here is calculated at "
            "request time.\n\n"
            "An unavailable value returns HTTP 200 with `status: insufficient` and "
            "a reason, so a client cannot mistake an absence for a zero."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = request_id
        logger.info(
            "%s %s %s %sms rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        """No key configured means local use. A key configured is required."""
        if resolved.api_key and x_api_key != resolved.api_key:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    def return_period(
        value: Annotated[int | None, Query(alias="return_period_years")] = None,
    ) -> int | None:
        if value is not None and value not in RETURN_PERIODS:
            raise HTTPException(
                status_code=422,
                detail="return_period_years must be one of 10, 50 or 100",
            )
        return value

    guard = [Depends(require_key)]
    rp = Depends(return_period)

    def current_engine(request: Request) -> Engine:
        return request.app.state.engine

    @app.get("/health", tags=["system"])
    def health(request: Request) -> dict[str, object]:
        engine: Engine = request.app.state.engine
        rows = mart_tools.coverage(engine)
        return {
            "status": "ok" if rows.ok else "degraded",
            "mart_rows": rows.available.rows if rows.available else 0,
            "documents": "configured" if request.app.state.search else "absent",
        }

    @app.get("/coverage", response_model=ToolOutput, tags=["read"], dependencies=guard)
    def coverage(engine: Annotated[Engine, Depends(current_engine)]) -> ToolOutput:
        """Indicators, periods, mechanisms and return periods that exist."""
        return mart_tools.coverage(engine)

    @app.get("/scopes", response_model=ToolOutput, tags=["read"], dependencies=guard)
    def resolve_scope(
        q: Annotated[str, Query(min_length=1, description="ward number, id or city name")],
        engine: Annotated[Engine, Depends(current_engine)],
    ) -> ToolOutput:
        """Resolve 'ward 75', 'Durban' or 'ethekwini-075' to a published scope."""
        return mart_tools.resolve_scope(engine, query=q)

    @app.get(
        "/indicators/{indicator_id}",
        response_model=ToolOutput,
        tags=["read"],
        dependencies=guard,
    )
    def indicator(
        indicator_id: str,
        engine: Annotated[Engine, Depends(current_engine)],
        scope_id: Annotated[str | None, Query()] = None,
        mechanism: Annotated[Mechanism | None, Query()] = None,
        return_period_years: Annotated[int | None, rp] = None,
        period_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    ) -> ToolOutput:
        """Published values for one indicator. Flood values need a mechanism and
        a return period; a missing one is reported, never defaulted."""
        return mart_tools.get_indicator(
            engine,
            indicator_id=indicator_id,
            scope_id=scope_id,
            mechanism=mechanism,
            return_period_years=return_period_years,
            period_year=period_year,
        )

    @app.get("/rank", response_model=ToolOutput, tags=["read"], dependencies=guard)
    def rank(
        indicator_id: str,
        engine: Annotated[Engine, Depends(current_engine)],
        limit: Annotated[int, Query(ge=1, le=200)] = 10,
        order: Annotated[Literal["asc", "desc"], Query()] = "desc",
        scope_level: Annotated[Literal["ward", "municipality"], Query()] = "ward",
        mechanism: Annotated[Mechanism | None, Query()] = None,
        return_period_years: Annotated[int | None, rp] = None,
        period_year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    ) -> ToolOutput:
        """Rank wards or the municipality by one indicator."""
        return mart_tools.rank_scopes(
            engine,
            indicator_id=indicator_id,
            limit=limit,
            order=order,
            scope_level=scope_level,
            mechanism=mechanism,
            return_period_years=return_period_years,
            period_year=period_year,
        )

    @app.get("/rows/{row_key}", response_model=ToolOutput, tags=["read"], dependencies=guard)
    def explain(
        row_key: str, engine: Annotated[Engine, Depends(current_engine)]
    ) -> ToolOutput:
        """Full provenance for one published row, including its warnings."""
        return mart_tools.explain(engine, row_key=row_key)

    @app.get(
        "/documents/search",
        response_model=DocumentResult,
        tags=["documents"],
        dependencies=guard,
    )
    def documents(
        request: Request,
        q: Annotated[str, Query(min_length=1)],
        scope_id: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=10)] = 5,
    ) -> DocumentResult:
        """Passages from municipal plans. Evidence of what a document says, never
        of a measured value."""
        search: Callable[[str, str | None, int], DocumentResult] = request.app.state.search
        return search(q, scope_id, limit)

    @app.post("/ask", response_model=AssistantResult, tags=["assistant"], dependencies=guard)
    def assistant(request: Request, body: AskRequest) -> AssistantResult:
        """Ask in plain language. The model selects tools and restates their
        results; it cannot calculate. Guarded refusals make zero model calls."""
        engine: Engine = request.app.state.engine
        deps = ToolDeps(engine=engine, search=request.app.state.search)
        return ask(request.app.state.settings, body.question, model=body.model, deps=deps)

    @app.post("/reports", status_code=201, tags=["reports"], dependencies=guard)
    def request_report(
        request: Request, body: ReportRequest
    ) -> dict[str, object]:
        """Queue a PDF report for a scope, optionally rendering it now."""
        from ..reports import RendererUnavailable, claim, enqueue, fail, finish, process

        engine: Engine = request.app.state.engine
        job_id = enqueue(engine, body.scope_id)
        if not body.process_now:
            return {"job_id": job_id, "status": "queued"}
        job = claim(engine)
        if job is None:
            raise HTTPException(status_code=409, detail="queue is empty after enqueue")
        try:
            path = process(engine, request.app.state.settings, job)
        except RendererUnavailable as exc:
            fail(engine, job.job_id, str(exc))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LookupError as exc:
            fail(engine, job.job_id, str(exc))
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finish(engine, job.job_id, path)
        return {"job_id": job.job_id, "status": "done", "artifact": str(path)}

    @app.get("/reports/{job_id}", tags=["reports"], dependencies=guard)
    def report_status(request: Request, job_id: str) -> dict[str, object]:
        from sqlalchemy import text

        engine: Engine = request.app.state.engine
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "select job_id, scope_id, status, artifact, error, requested_at, "
                    "finished_at from report_job where job_id = :job_id"
                ),
                {"job_id": job_id},
            ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="no such report job")
        return dict(row._mapping)

    @app.get("/reports/{job_id}/file", tags=["reports"], dependencies=guard)
    def report_file(request: Request, job_id: str) -> FileResponse:
        from pathlib import Path

        from sqlalchemy import text

        engine: Engine = request.app.state.engine
        with engine.connect() as connection:
            row = connection.execute(
                text("select artifact from report_job where job_id = :job_id"),
                {"job_id": job_id},
            ).first()
        if row is None or not row[0] or not Path(row[0]).exists():
            raise HTTPException(status_code=404, detail="report is not ready")
        return FileResponse(row[0], media_type="application/pdf", filename=f"{job_id}.pdf")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak a stack trace or a connection string to a client.
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal error; the request id is in the response header"},
        )

    return app


app = create_app()
