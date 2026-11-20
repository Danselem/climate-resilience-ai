"""Hybrid retrieval: fusion logic offline, storage against a live pgvector."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from climate_resilience.rag import store
from climate_resilience.rag.chunking import Chunk
from climate_resilience.rag.embeddings import DIMENSION, HashingEmbedder
from climate_resilience.rag.retrieval import fuse, hybrid_search

DSN = os.environ.get(
    "CRP_DOCUMENTS_DSN", "postgresql://crp:crp@localhost:5433/crp"
)


def row(chunk_id: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "chunk_id": chunk_id,
        "document_id": "doc",
        "text": f"text {chunk_id}",
        "context": f"context {chunk_id}",
        "page_no": 1,
        "headings": ["Adaptation"],
        "scope_level": "municipality",
        "scope_ids": ["ethekwini"],
    }
    base.update(overrides)
    return base


def test_agreement_between_retrievers_wins() -> None:
    """A chunk found by both dense and lexical outranks one found by either."""
    hits = fuse(
        [row("a"), row("b"), row("c")],
        [row("c"), row("d")],
        k=4,
    )

    assert hits[0].chunk_id == "c"
    assert hits[0].dense_rank == 3
    assert hits[0].lexical_rank == 1


def test_fusion_scores_follow_reciprocal_rank() -> None:
    hits = fuse([row("a")], [], k=1)

    assert hits[0].score == pytest.approx(1 / 61)


def test_fusion_keeps_a_chunk_found_by_only_one_retriever() -> None:
    hits = fuse([row("dense-only")], [row("lexical-only")], k=5)

    assert {hit.chunk_id for hit in hits} == {"dense-only", "lexical-only"}


def test_fusion_respects_k() -> None:
    hits = fuse([row(str(index)) for index in range(10)], [], k=3)

    assert len(hits) == 3


@pytest.fixture
def connection() -> Iterator[Any]:
    try:
        conn = store.connect(DSN)
    except Exception as error:  # noqa: BLE001 - skipped, not swallowed
        pytest.skip(f"pgvector database unavailable: {error}")
    store.ensure_schema(conn, dimension=DIMENSION)
    _clean(conn)
    try:
        yield conn
    finally:
        _clean(conn)
        conn.close()


def _clean(conn: Any) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "delete from document_chunk where document_id like 'test-%'"
        )
    conn.commit()


def chunk(
    chunk_id: str,
    text: str,
    *,
    scope_level: str = "municipality",
    scope_ids: tuple[str, ...] = ("ethekwini",),
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="test-plan",
        version="2026",
        index=0,
        text=text,
        context=text,
        page_no=3,
        headings=("Adaptation",),
        scope_level=scope_level,
        scope_ids=scope_ids,
    )


def test_round_trip_and_hybrid_search(connection) -> None:
    embedder = HashingEmbedder()
    chunks = [
        chunk("test-1", "Sea level rise threatens the coastal zone"),
        chunk("test-2", "Solid waste collection runs weekly"),
        chunk(
            "test-3",
            "Sea level rise is acute at ward 75",
            scope_level="ward",
            scope_ids=("ethekwini-075",),
        ),
    ]
    store.replace_document(
        connection,
        document_id="test-plan",
        chunks=chunks,
        embeddings=embedder.embed([item.text for item in chunks]),
    )

    hits = hybrid_search(connection, embedder, "sea level rise", k=3)

    assert {hit.chunk_id for hit in hits} >= {"test-1", "test-3"}
    assert all(hit.document_id == "test-plan" for hit in hits)
    assert all(hit.page_no == 3 for hit in hits)


def test_scope_filter_admits_municipal_text_but_not_other_wards(connection) -> None:
    embedder = HashingEmbedder()
    chunks = [
        chunk("test-1", "Sea level rise threatens the coastal zone"),
        chunk(
            "test-2",
            "Sea level rise is acute at ward 75",
            scope_level="ward",
            scope_ids=("ethekwini-075",),
        ),
        chunk(
            "test-3",
            "Sea level rise is acute at ward 90",
            scope_level="ward",
            scope_ids=("ethekwini-090",),
        ),
    ]
    store.replace_document(
        connection,
        document_id="test-plan",
        chunks=chunks,
        embeddings=embedder.embed([item.text for item in chunks]),
    )

    hits = hybrid_search(connection, embedder, "sea level rise", k=5, scope_id="ethekwini-075")

    ids = {hit.chunk_id for hit in hits}
    assert "test-1" in ids, "municipal context is admitted"
    assert "test-2" in ids, "the requested ward is admitted"
    assert "test-3" not in ids, "another ward is excluded"


def test_replacing_a_document_removes_its_old_chunks(connection) -> None:
    embedder = HashingEmbedder()
    store.replace_document(
        connection,
        document_id="test-plan",
        chunks=[chunk("test-old", "obsolete text")],
        embeddings=embedder.embed(["obsolete text"]),
    )
    store.replace_document(
        connection,
        document_id="test-plan",
        chunks=[chunk("test-new", "current text")],
        embeddings=embedder.embed(["current text"]),
    )

    rows = store.documents(connection)

    assert [entry["document_id"] for entry in rows] == ["test-plan"]
    assert rows[0]["chunks"] == 1


def test_an_empty_query_returns_nothing(connection) -> None:
    assert hybrid_search(connection, HashingEmbedder(), "   ") == []
