"""Store access. Portable SQL: SQLite for tests, PostgreSQL/PostGIS in deployment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, delete, func, select
from sqlalchemy.engine import make_url

from .models import boundary, boundary_crosswalk, indicator_value, metadata


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.drivername.startswith("sqlite") and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, future=True)


def ensure_schema(engine: Engine) -> None:
    metadata.create_all(engine)


def replace_build(
    engine: Engine,
    rows: list[dict[str, Any]],
    *,
    indicator_id: str,
    method_version: str,
    dataset_version: str,
) -> int:
    """Replace all rows for one indicator build, atomically.

    Rebuilding is explicit and idempotent: the previous build of the same
    indicator/method/dataset is removed, so a partial write cannot leave two
    versions of the same number in the mart.
    """
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(
            delete(indicator_value).where(
                indicator_value.c.indicator_id == indicator_id,
                indicator_value.c.method_version == method_version,
                indicator_value.c.dataset_version == dataset_version,
            )
        )
        conn.execute(indicator_value.insert(), rows)
    return len(rows)


def fetch(
    engine: Engine, *, indicator_id: str, scope_level: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(indicator_value).where(indicator_value.c.indicator_id == indicator_id)
    if scope_level:
        stmt = stmt.where(indicator_value.c.scope_level == scope_level)
    stmt = stmt.order_by(
        indicator_value.c.scope_level,
        indicator_value.c.scope_id,
        indicator_value.c.period_start,
    )
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]


def count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(indicator_value)).scalar_one())


def replace_boundaries(engine: Engine, rows: list[dict[str, Any]]) -> int:
    """Replace the boundary rows identified by the incoming ids, atomically.

    Deletion is keyed on ``boundary_id``, not on ``dataset_version``: one layer
    mixes dataset versions (a municipal polygon from ADM2 plus wards from
    ADM4), so scoping deletion by version would leave stale rows behind and
    collide on the next insert.
    """
    if not rows:
        return 0
    ids = [row["boundary_id"] for row in rows]
    with engine.begin() as conn:
        conn.execute(delete(boundary).where(boundary.c.boundary_id.in_(ids)))
        conn.execute(boundary.insert(), rows)
    return len(rows)


def replace_crosswalk(engine: Engine, rows: list[dict[str, Any]], *, vintage: str) -> int:
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(delete(boundary_crosswalk).where(boundary_crosswalk.c.vintage == vintage))
        conn.execute(boundary_crosswalk.insert(), rows)
    return len(rows)


def fetch_boundaries(engine: Engine, *, level: str | None = None) -> list[dict[str, Any]]:
    stmt = select(boundary)
    if level:
        stmt = stmt.where(boundary.c.level == level)
    stmt = stmt.order_by(boundary.c.boundary_id)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]


def fetch_crosswalk(engine: Engine, *, municipality_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(boundary_crosswalk)
    if municipality_id:
        stmt = stmt.where(boundary_crosswalk.c.municipality_id == municipality_id)
    stmt = stmt.order_by(boundary_crosswalk.c.ward_number)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]
