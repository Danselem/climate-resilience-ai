"""Read-only analytical tools over the indicator mart.

These are the functions the assistant and the API both call -- one
implementation, two callers. The model never sees SQL: it chooses a tool and
its arguments, and Python returns envelopes.

Two rules are enforced here rather than in a prompt:

* Riverine and coastal flood values are never ranked or summed together.
* A flood ranking must state its return period, because 10-year and 100-year
  exposure are different questions and neither is a safe default.
"""

from __future__ import annotations

import re

from sqlalchemy import Engine, Select, extract, select

from ..envelope import EvidenceEnvelope
from ..indicators import REGISTRY
from ..store.models import boundary, boundary_crosswalk, indicator_value
from .models import Available, ScopeRef, ToolOutput

MAX_RANK_LIMIT = 200
WARD_PATTERN = re.compile(r"ward\s*0*(\d{1,3})", re.IGNORECASE)
# Presentation order, not priority: riverine is the mechanism that produces
# non-zero exposure here, so it should not sit below a column of coastal zeros.
MECHANISM_ORDER = ("riverine", "coastal")


def _rows(engine: Engine, stmt: Select) -> list[dict[str, object]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]


def _envelopes(rows: list[dict[str, object]]) -> list[EvidenceEnvelope]:
    envelopes: list[EvidenceEnvelope] = []
    for row in rows:
        raw = row.get("envelope_json")
        if not raw:
            raise RuntimeError(
                f"row {str(row['row_key'])[:12]} carries no envelope_json; "
                "rebuild the mart with `climate-resilience mart`"
            )
        envelopes.append(EvidenceEnvelope.model_validate_json(str(raw)))
    return envelopes


def _available(engine: Engine, indicator_id: str | None = None) -> Available:
    stmt = select(indicator_value)
    if indicator_id is not None:
        stmt = stmt.where(indicator_value.c.indicator_id == indicator_id)
    rows = _rows(engine, stmt)
    return Available(
        indicators=sorted({str(row["indicator_id"]) for row in rows}),
        scope_levels=sorted({str(row["scope_level"]) for row in rows}),
        periods=sorted(
            {
                f"{row['period_start']}..{row['period_end']}"
                for row in rows
            }
        ),
        mechanisms=sorted(
            {str(row["mechanism"]) for row in rows if row["mechanism"]}
        ),
        return_periods=sorted(
            {
                int(row["return_period_years"])
                for row in rows
                if row["return_period_years"] is not None
            }
        ),
        rows=len(rows),
    )


def _filtered(
    indicator_id: str,
    *,
    scope_level: str | None = None,
    scope_id: str | None = None,
    mechanism: str | None = None,
    return_period_years: int | None = None,
    period_year: int | None = None,
) -> Select:
    stmt = select(indicator_value).where(
        indicator_value.c.indicator_id == indicator_id
    )
    if scope_level is not None:
        stmt = stmt.where(indicator_value.c.scope_level == scope_level)
    if scope_id is not None:
        stmt = stmt.where(indicator_value.c.scope_id == scope_id)
    if mechanism is not None:
        stmt = stmt.where(indicator_value.c.mechanism == mechanism)
    if return_period_years is not None:
        stmt = stmt.where(
            indicator_value.c.return_period_years == return_period_years
        )
    if period_year is not None:
        stmt = stmt.where(
            extract("year", indicator_value.c.period_start) == period_year
        )
    return stmt.order_by(
        indicator_value.c.scope_level,
        indicator_value.c.scope_id,
        indicator_value.c.return_period_years,
        indicator_value.c.period_start,
    )


def get_indicator(
    engine: Engine,
    *,
    indicator_id: str,
    scope_id: str | None = None,
    scope_level: str | None = None,
    mechanism: str | None = None,
    return_period_years: int | None = None,
    period_year: int | None = None,
) -> ToolOutput:
    """One indicator for one scope, as evidence envelopes."""
    if indicator_id not in REGISTRY:
        return ToolOutput.insufficient(
            f"{indicator_id!r} is not a registered indicator",
            missing=[f"one of: {', '.join(sorted(REGISTRY))}"],
            available=_available(engine),
        )

    rows = _rows(
        engine,
        _filtered(
            indicator_id,
            scope_level=scope_level,
            scope_id=scope_id,
            mechanism=mechanism,
            return_period_years=return_period_years,
            period_year=period_year,
        ),
    )
    if not rows:
        return ToolOutput.insufficient(
            f"no published {indicator_id} matches that scope, period or parameter",
            missing=["a published scope, period and parameter combination"],
            available=_available(engine, indicator_id),
        )

    envelopes = _envelopes(rows)
    mechanisms = {envelope.mechanism for envelope in envelopes if envelope.mechanism}
    message = None
    if len(mechanisms) > 1:
        message = (
            "riverine and coastal rows are separate and must never be summed "
            "into one flood metric"
        )
    return ToolOutput.evidence(envelopes, message=message)


def rank_scopes(
    engine: Engine,
    *,
    indicator_id: str,
    limit: int = 10,
    order: str = "desc",
    scope_level: str = "ward",
    mechanism: str | None = None,
    return_period_years: int | None = None,
    period_year: int | None = None,
) -> ToolOutput:
    """Rank scopes by an indicator, within one period and one hazard parameterisation."""
    spec = REGISTRY.get(indicator_id)
    if spec is None:
        return ToolOutput.insufficient(
            f"{indicator_id!r} is not a registered indicator",
            missing=[f"one of: {', '.join(sorted(REGISTRY))}"],
            available=_available(engine),
        )
    if order not in {"desc", "asc"}:
        return ToolOutput.insufficient("order must be 'desc' or 'asc'")
    if limit < 1:
        return ToolOutput.insufficient("limit must be at least 1")

    if spec.hazard_type == "flood" and return_period_years is None:
        return ToolOutput.insufficient(
            "a flood ranking needs a return period; 10-year and 100-year "
            "exposure answer different questions and neither is a default",
            missing=["return_period_years"],
            available=_available(engine, indicator_id),
        )

    rows = _rows(
        engine,
        _filtered(
            indicator_id,
            scope_level=scope_level,
            mechanism=mechanism,
            return_period_years=return_period_years,
            period_year=period_year,
        ),
    )
    if not rows:
        return ToolOutput.insufficient(
            f"no published {indicator_id} matches that scope level or parameter",
            missing=["a published scope level, period and parameter combination"],
            available=_available(engine, indicator_id),
        )

    notes: list[str] = []
    if period_year is None and spec.hazard_type != "flood":
        latest = max(row["period_start"] for row in rows)
        rows = [row for row in rows if row["period_start"] == latest]
        notes.append(
            f"ranked on the latest published period ({latest.year})"
        )

    chosen: list[dict[str, object]]
    if spec.hazard_type == "flood" and mechanism is None:
        # Rank inside each mechanism. Sorting the union would silently compare
        # a riverine depth cell with a coastal one and invite a sum.
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            grouped.setdefault(str(row["mechanism"]), []).append(row)
        chosen = []
        for name in sorted(grouped, key=_mechanism_sort_key):
            chosen.extend(_rank(grouped[name], order)[: min(limit, MAX_RANK_LIMIT)])
        notes.append(
            f"up to {limit} rows per mechanism; riverine and coastal are ranked "
            "separately and must never be added together"
        )
    else:
        chosen = _rank(rows, order)[: min(limit, MAX_RANK_LIMIT)]

    return ToolOutput.evidence(_envelopes(chosen), message="; ".join(notes) or None)


def _rank(rows: list[dict[str, object]], order: str) -> list[dict[str, object]]:
    return sorted(
        rows, key=lambda row: float(row["value"]), reverse=order == "desc"
    )


def _mechanism_sort_key(name: str) -> tuple[int, str]:
    if name in MECHANISM_ORDER:
        return (MECHANISM_ORDER.index(name), name)
    return (len(MECHANISM_ORDER), name)


def explain(engine: Engine, *, row_key: str) -> ToolOutput:
    """The full provenance of one published number."""
    rows = _rows(
        engine,
        select(indicator_value).where(indicator_value.c.row_key == row_key),
    )
    if not rows:
        return ToolOutput.insufficient(
            f"no published row with key {row_key!r}",
            missing=["a valid row_key from a previous tool result"],
        )
    return ToolOutput.evidence(_envelopes(rows))


def resolve_scope(engine: Engine, *, query: str) -> ToolOutput:
    """Turn 'ward 75', a ward id or a place name into a published scope."""
    text = query.strip()
    if not text:
        return ToolOutput.insufficient("the scope query is empty")

    lowered = text.lower()
    boundaries = _rows(engine, select(boundary))
    crosswalk = {
        str(row["ward_id"]): row
        for row in _rows(engine, select(boundary_crosswalk))
    }

    matches = [
        row
        for row in boundaries
        if lowered in {str(row["boundary_id"]).lower(), str(row["name"]).lower()}
    ]
    if not matches:
        ward = WARD_PATTERN.search(lowered)
        if ward:
            number = int(ward.group(1))
            matches = [
                row
                for row in boundaries
                if (crosswalk.get(str(row["boundary_id"])) or {}).get("ward_number")
                == number
            ]
    if not matches:
        matches = [row for row in boundaries if lowered in str(row["name"]).lower()]
    if not matches:
        return ToolOutput.insufficient(
            f"no published scope matches {query!r}",
            missing=["a ward number, ward id or municipality name"],
            available=_available(engine),
        )

    scopes = [
        ScopeRef(
            level=str(row["level"]),  # type: ignore[arg-type]
            id=str(row["boundary_id"]),
            name=str(row["name"]),
            ward_number=(crosswalk.get(str(row["boundary_id"])) or {}).get(
                "ward_number"
            ),
            area_km2=float(row["area_km2"]),
        )
        for row in matches
    ]
    return ToolOutput(status="ok", scopes=scopes)


def coverage(
    engine: Engine, *, indicator_id: str | None = None, scope_id: str | None = None
) -> ToolOutput:
    """What the mart holds, so the assistant can refuse precisely."""
    available = _available(engine, indicator_id)
    if available.rows == 0:
        return ToolOutput.insufficient(
            "the mart holds no published rows; run `climate-resilience mart`",
            missing=["a built indicator mart"],
        )
    if scope_id is not None:
        rows = _rows(
            engine,
            select(indicator_value).where(indicator_value.c.scope_id == scope_id),
        )
        if not rows:
            return ToolOutput.insufficient(
                f"no published value for scope {scope_id!r}",
                missing=["a scope present in the mart"],
                available=available,
            )
    return ToolOutput(
        status="ok",
        available=available,
        message=(
            f"{available.rows} published rows across "
            f"{len(available.indicators)} indicators"
        ),
    )
