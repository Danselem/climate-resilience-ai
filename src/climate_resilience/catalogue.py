"""Machine-readable data catalogue.

One entry per dataset, with the fields a reader needs to judge whether a
number may be trusted: licence, version, checksum, units, CRS, coverage,
time basis, and known gaps. Validated by a test so the catalogue cannot rot.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Basis = Literal["observation", "reanalysis", "projection", "modelled_estimate", "derived"]
Status = Literal["active", "blocked", "not_implemented", "planned", "context_only"]


class DatasetEntry(BaseModel):
    id: str
    name: str
    role: str
    source_url: str
    licence: str
    version: str
    checksum: str | None = None
    basis: Basis
    units: str
    crs: str
    native_resolution: str
    spatial_coverage: str
    temporal_coverage: str
    time_basis: str
    status: Status
    retrieved_at: date | None = None
    # Path to the acquired file, relative to the data directory. `checksum` is
    # the sha256 of this artifact, so a reader can verify what is on disk.
    artifact: str | None = None
    # True when a published indicator cannot be produced without this dataset.
    # A missing optional source is recorded and skipped; a missing required one
    # fails the run.
    required: bool = False
    known_gaps: list[str] = Field(default_factory=list)
    processing_steps: list[str] = Field(default_factory=list)


class Catalogue(BaseModel):
    version: int
    datasets: list[DatasetEntry]

    def by_status(self, status: Status) -> list[DatasetEntry]:
        return [d for d in self.datasets if d.status == status]


def load(path: Path) -> Catalogue:
    return Catalogue.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def validate(catalogue: Catalogue) -> list[str]:
    """Return a list of problems. Empty means the catalogue is coherent."""
    problems: list[str] = []
    ids = [entry.id for entry in catalogue.datasets]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        problems.append(f"duplicate dataset ids: {sorted(duplicates)}")

    for entry in catalogue.datasets:
        if entry.status == "active" and not entry.checksum:
            problems.append(f"{entry.id}: active dataset has no checksum")
        if entry.status == "active" and entry.retrieved_at is None:
            problems.append(f"{entry.id}: active dataset has no retrieval date")
        if not entry.known_gaps and entry.status == "active":
            problems.append(f"{entry.id}: active dataset should record known gaps explicitly")
        if entry.status == "active" and not entry.artifact:
            problems.append(f"{entry.id}: active dataset declares no artifact path")
        if entry.required and entry.status != "active":
            problems.append(
                f"{entry.id}: required dataset is not active (status={entry.status}); "
                "a required source must be acquired, not merely planned"
            )
    return problems
