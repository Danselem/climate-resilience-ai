"""Store access. Portable SQL: SQLite for tests, PostgreSQL/PostGIS in deployment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, delete, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool

from .models import boundary, boundary_crosswalk, indicator_value, metadata


def make_engine(database_url: str) -> Engine:
    """Build an engine that is safe to use from worker threads.

    Tool calls run outside the request thread, and SQLite refuses a connection
    used from a thread other than the one that created it. ``check_same_thread``
    is therefore disabled deliberately, and an in-memory database uses a single
    shared connection so every thread sees the same tables.
    """
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return create_engine(database_url, future=True)

    connect_args = {"check_same_thread": False}
    if url.database in (None, "", ":memory:"):
        return create_engine(
            database_url,
            future=True,
            connect_args=connect_args,
            poolclass=StaticPool,
        )
    Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, future=True, connect_args=connect_args)


def ensure_schema(engine: Engine) -> None:
    """Create the schema, then add columns introduced after a database existed.

    The mart is derived and rebuildable, but it is not dropped silently: a
    column added by a later version is ALTERed in, so an existing database
    keeps its rows and the next rebuild populates the new field.
    """
    metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(indicator_value.name):
        return
    present = {column["name"] for column in inspector.get_columns(indicator_value.name)}
    for column in indicator_value.columns:
        if column.name in present:
            continue
        if not column.nullable and column.server_default is None:
            raise RuntimeError(
                f"cannot add the NOT NULL column {column.name!r} to an existing "
                "indicator_value table; rebuild the mart instead"
            )
        ddl = column.type.compile(dialect=engine.dialect)
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE {indicator_value.name} ADD COLUMN {column.name} {ddl}")
            )


def replace_build(
    engine: Engine,
    rows: list[dict[str, Any]],
    *,
    indicator_id: str,
    method_version: str,
) -> int:
    """Replace all live rows for one indicator/method pair, atomically.

    Rebuilding is explicit and idempotent: the previous build of the same
    indicator and method is removed, whatever dataset version produced it.
    Scoping the delete by ``dataset_version`` would leave stale rows behind
    whenever the input version changed -- exactly the case where two versions
    of the same number must not both be live. Old results stay interpretable
    through their immutable snapshots and manifests, not as duplicate mart rows.
    """
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(
            delete(indicator_value).where(
                indicator_value.c.indicator_id == indicator_id,
                indicator_value.c.method_version == method_version,
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
