"""Document ingestion: licence gates, chunk provenance and ward scope."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from climate_resilience.rag import (
    DocumentCatalogue,
    DocumentEntry,
    chunk_document,
    load,
)


def active(**overrides) -> dict:
    base = {
        "id": "cap-2019",
        "title": "Durban Climate Action Plan",
        "publisher": "eThekwini Municipality",
        "source_url": "https://example.invalid/cap.pdf",
        "licence": "public municipal document; cited, not redistributed",
        "version": "2019",
        "status": "active",
        "retrieved_at": date(2026, 11, 20),
        "checksum": "a" * 64,
        "artifact": "raw/documents/cap-2019.pdf",
    }
    base.update(overrides)
    return base


def test_an_active_document_must_be_traceable() -> None:
    with pytest.raises(ValueError, match="checksum"):
        DocumentEntry.model_validate(active(checksum=None))


def test_an_excluded_document_needs_no_artefact() -> None:
    entry = DocumentEntry.model_validate(
        {
            "id": "greenbook",
            "title": "GreenBook",
            "publisher": "CSIR",
            "source_url": "https://example.invalid",
            "licence": "CC BY-NC-SA 3.0 ZA",
            "version": "2019",
            "status": "excluded",
        }
    )

    assert entry.status == "excluded"


def test_duplicate_document_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        DocumentCatalogue.model_validate(
            {"documents": [active(), active()]}
        )


def test_only_active_documents_are_ingested() -> None:
    catalogue = DocumentCatalogue.model_validate(
        {
            "documents": [
                active(),
                active(id="other", status="excluded", checksum=None),
            ]
        }
    )

    assert [document.id for document in catalogue.active()] == ["cap-2019"]


def test_the_shipped_catalogue_is_valid() -> None:
    catalogue = load(Path("data/catalogue/documents.json"))

    assert catalogue.documents
    assert any(document.id.startswith("greenbook") for document in catalogue.documents)


def test_chunks_keep_headings_and_ward_scope(tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text(
        "# Durban Climate Action Plan\n\n"
        "## Adaptation\n\n"
        "Sea level rise threatens the coast. Wards 75 and 39 are priorities.\n\n"
        "## Water\n\n"
        "Demand management applies across the municipality.\n",
        encoding="utf-8",
    )
    document = DocumentEntry.model_validate(active())

    chunks = chunk_document(path, document)

    assert chunks
    assert all(chunk.document_id == "cap-2019" for chunk in chunks)
    assert any("Adaptation" in chunk.headings for chunk in chunks)
    ward_chunks = [chunk for chunk in chunks if chunk.scope_level == "ward"]
    assert ward_chunks
    assert "ethekwini-075" in ward_chunks[0].scope_ids
    assert "ethekwini-039" in ward_chunks[0].scope_ids


def test_a_chunk_without_a_ward_stays_municipal(tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text(
        "# Plan\n\n## Water\n\nDemand management applies across the municipality.\n",
        encoding="utf-8",
    )
    document = DocumentEntry.model_validate(active())

    chunks = chunk_document(path, document)

    assert chunks
    assert all(chunk.scope_level == "municipality" for chunk in chunks)
    assert all("ethekwini" in chunk.scope_ids for chunk in chunks)


def test_chunk_ids_are_stable_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text("# Plan\n\n## Water\n\nOne paragraph.\n", encoding="utf-8")
    document = DocumentEntry.model_validate(active())

    first = [chunk.chunk_id for chunk in chunk_document(path, document)]
    second = [chunk.chunk_id for chunk in chunk_document(path, document)]

    assert first == second


def test_the_ward_pattern_reads_plurals_and_lists() -> None:
    from climate_resilience.rag.chunking import ward_numbers

    assert ward_numbers("ward 7") == [7]
    assert ward_numbers("Ward 075") == [75]
    assert ward_numbers("wards 12, 14 and 16") == [12, 14, 16]
    assert ward_numbers("Wards 75 and 39 are priorities") == [39, 75]
    assert ward_numbers("award ceremony") == []
    assert ward_numbers("no numbers here") == []
