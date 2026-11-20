"""Document catalogue.

A retrieved sentence is only as citable as the file it came from, so documents
get the same treatment as datasets: licence, version, checksum, retrieval date
and scope are recorded before any text is indexed.

Licence status is a first-class field because it decides whether a document may
be ingested at all. GreenBook is CC BY-NC-SA: usable for reading, not for a
commercial derived index. That is an exclusion, and it is written down here
rather than discovered later.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DocumentStatus = Literal["active", "blocked", "excluded"]
ScopeLevel = Literal["municipality", "ward"]


class DocumentEntry(BaseModel):
    id: str
    title: str
    publisher: str
    source_url: str
    licence: str
    version: str
    status: DocumentStatus = "active"
    retrieved_at: date | None = None
    checksum: str | None = None
    artifact: str | None = None
    # Municipal plans are city-wide unless the text names wards. Defaulting to
    # municipality keeps a city-wide sentence from being read as ward evidence.
    scope_level: ScopeLevel = "municipality"
    scope_ids: list[str] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _active_documents_are_traceable(self) -> DocumentEntry:
        if self.status != "active":
            return self
        missing = [
            name
            for name, value in (
                ("licence", self.licence),
                ("checksum", self.checksum),
                ("retrieved_at", self.retrieved_at),
                ("artifact", self.artifact),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"{self.id}: an active document must record {', '.join(missing)}"
            )
        return self


class DocumentCatalogue(BaseModel):
    documents: list[DocumentEntry]

    @model_validator(mode="after")
    def _identifiers_are_unique(self) -> DocumentCatalogue:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for document in self.documents:
            if document.id in seen:
                duplicates.add(document.id)
            seen.add(document.id)
        if duplicates:
            raise ValueError(f"duplicate document ids: {sorted(duplicates)}")
        return self

    def active(self) -> list[DocumentEntry]:
        return [document for document in self.documents if document.status == "active"]

    def get(self, document_id: str) -> DocumentEntry:
        for document in self.documents:
            if document.id == document_id:
                return document
        raise KeyError(f"no document {document_id!r} in the catalogue")


def load(path: Path) -> DocumentCatalogue:
    return DocumentCatalogue.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
