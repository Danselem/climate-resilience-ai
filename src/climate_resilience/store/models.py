"""Persistence for published metrics.

The schema mirrors the evidence envelope. A surrogate ``row_key`` is the
primary key because PostgreSQL does not permit NULL columns inside a
composite primary key, while ``scenario`` and ``model`` are legitimately null
for non-projection records.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
)

metadata = MetaData()

indicator_value = Table(
    "indicator_value",
    metadata,
    Column("row_key", Text, primary_key=True),
    Column("indicator_id", Text, nullable=False),
    Column("method_version", Text, nullable=False),
    Column("scope_level", Text, nullable=False),
    Column("scope_id", Text, nullable=False),
    Column("scope_name", Text, nullable=False),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("hazard_type", Text, nullable=False),
    Column("return_period_years", Integer, nullable=True),
    Column("depth_threshold_m", Float, nullable=True),
    Column("mechanism", Text, nullable=True),
    Column("basis", Text, nullable=False),
    Column("scenario", Text, nullable=True),
    Column("model", Text, nullable=True),
    Column("baseline_start", Date, nullable=True),
    Column("baseline_end", Date, nullable=True),
    Column("value", Float, nullable=False),
    Column("unit", Text, nullable=False),
    Column("uncertainty_lower", Float, nullable=True),
    Column("uncertainty_upper", Float, nullable=True),
    Column("n_samples", Integer, nullable=False),
    Column("coverage_pct", Float, nullable=False),
    Column("missing_pct", Float, nullable=False),
    Column("native_resolution", Text, nullable=False),
    Column("warnings", Text, nullable=False, server_default="[]"),
    Column("dataset_version", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
    # The full evidence envelope, verbatim. The flattened columns above are a
    # projection of it; this keeps what a citation needs and a flat row cannot
    # carry: dataset ids, source URLs, licences, checksums, the method id and
    # the run's git commit. Nullable only so an existing database can be
    # migrated in place; every row written by `to_row` populates it.
    Column("envelope_json", Text, nullable=True),
)

Index(
    "ix_indicator_lookup",
    indicator_value.c.indicator_id,
    indicator_value.c.method_version,
    indicator_value.c.scope_level,
    indicator_value.c.scope_id,
    indicator_value.c.period_start,
)

Index(
    "ix_indicator_dataset",
    indicator_value.c.indicator_id,
    indicator_value.c.dataset_version,
)

boundary = Table(
    "boundary",
    metadata,
    Column("boundary_id", Text, primary_key=True),
    Column("level", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("code", Integer, nullable=True),
    Column("parent_id", Text, nullable=True),
    Column("vintage", Text, nullable=False),
    Column("dataset_id", Text, nullable=False),
    Column("dataset_version", Text, nullable=False),
    Column("crs", Text, nullable=False),
    Column("area_km2", Float, nullable=False),
    Column("geometry_wkt", Text, nullable=False),
)

Index("ix_boundary_level", boundary.c.level, boundary.c.vintage)

boundary_crosswalk = Table(
    "boundary_crosswalk",
    metadata,
    Column("ward_id", Text, primary_key=True),
    Column("vintage", Text, primary_key=True),
    Column("ward_name", Text, nullable=False),
    Column("ward_number", Integer, nullable=True),
    Column("municipality_id", Text, nullable=False),
    Column("municipality_name", Text, nullable=False),
    Column("inside_fraction", Float, nullable=False),
    Column("area_km2", Float, nullable=False),
)
