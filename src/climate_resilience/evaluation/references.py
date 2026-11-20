"""Independent resolution of expected answers.

The benchmark must not learn the right answer from the code it is testing, so
expected rows are located by querying ``indicator_value`` directly with the
published parameters. No tool, no envelope, no method registry.
"""

from __future__ import annotations

from sqlalchemy import Engine, extract, select

from ..store.models import indicator_value
from .models import Reference


def resolve_row_keys(engine: Engine, reference: Reference) -> set[str]:
    """The row_keys a correct answer must cite, or an empty set."""
    query = select(indicator_value.c.row_key).where(
        indicator_value.c.indicator_id == reference.indicator_id
    )
    if reference.scope_id is not None:
        query = query.where(indicator_value.c.scope_id == reference.scope_id)
    if reference.scope_level is not None:
        query = query.where(indicator_value.c.scope_level == reference.scope_level)
    if reference.mechanism is not None:
        query = query.where(indicator_value.c.mechanism == reference.mechanism)
    if reference.return_period_years is not None:
        query = query.where(
            indicator_value.c.return_period_years == reference.return_period_years
        )
    if reference.period_year is not None:
        query = query.where(
            extract("year", indicator_value.c.period_start) == reference.period_year
        )
    with engine.connect() as connection:
        return {str(row[0]) for row in connection.execute(query)}
