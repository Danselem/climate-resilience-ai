"""Hybrid retrieval: dense vectors plus lexical ranking, fused by rank.

Neither alone is enough for this corpus. Dense search finds paraphrase ("sea
level rise" for "coastal inundation") but misses exact identifiers a planner
types -- a ward number, "RCP8.5", a programme name. Lexical search does the
opposite. Reciprocal rank fusion combines them without a learned weight, which
would be unjustifiable with ten documents.

Scope filtering is deliberately asymmetric: asking about ward 75 admits
municipal text and ward-75 text, and excludes other wards. It does not relabel
municipal text as ward evidence; every hit carries its own scope so the caller
can say which it is.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from pgvector import Vector

from .embeddings import Embedder

RRF_K = 60
DEFAULT_POOL = 30

_SELECT = """
select chunk_id, document_id, text, context, page_no, headings,
       scope_level, scope_ids
from document_chunk
"""

_SCOPE = """
  and (scope_level = 'municipality' or %(scope)s = any(scope_ids))
"""


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    document_id: str
    text: str
    context: str
    page_no: int | None
    headings: tuple[str, ...]
    scope_level: str
    scope_ids: tuple[str, ...]
    score: float
    dense_rank: int | None = None
    lexical_rank: int | None = None


def hybrid_search(
    connection: psycopg.Connection,
    embedder: Embedder,
    query: str,
    *,
    k: int = 8,
    scope_id: str | None = None,
    pool: int = DEFAULT_POOL,
) -> list[Hit]:
    if not query.strip():
        return []
    vector = embedder.embed([query])[0]
    dense = _dense(connection, vector, limit=pool, scope_id=scope_id)
    lexical = _lexical(connection, query, limit=pool, scope_id=scope_id)
    return fuse(dense, lexical, k=k)


def _dense(
    connection: psycopg.Connection,
    vector: Sequence[float],
    *,
    limit: int,
    scope_id: str | None,
) -> list[dict[str, Any]]:
    sql = (
        _SELECT
        + "where true"
        + (_SCOPE if scope_id else "")
        + " order by embedding <=> %(vec)s limit %(limit)s"
    )
    parameters: dict[str, Any] = {"vec": Vector(list(vector)), "limit": limit}
    if scope_id:
        parameters["scope"] = scope_id
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return [dict(row) for row in cursor.fetchall()]


def _lexical(
    connection: psycopg.Connection,
    query: str,
    *,
    limit: int,
    scope_id: str | None,
) -> list[dict[str, Any]]:
    sql = (
        _SELECT
        + "where to_tsvector('english', text) @@ plainto_tsquery('english', %(q)s)"
        + (_SCOPE if scope_id else "")
        + """
        order by ts_rank_cd(to_tsvector('english', text),
                            plainto_tsquery('english', %(q)s)) desc
        limit %(limit)s
        """
    )
    parameters: dict[str, Any] = {"q": query, "limit": limit}
    if scope_id:
        parameters["scope"] = scope_id
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return [dict(row) for row in cursor.fetchall()]


def fuse(
    dense: Iterable[dict[str, Any]],
    lexical: Iterable[dict[str, Any]],
    *,
    k: int,
    rrf_k: int = RRF_K,
) -> list[Hit]:
    """Reciprocal rank fusion: score = sum(1 / (rrf_k + rank))."""
    dense = list(dense)
    lexical = list(lexical)

    scores: dict[str, float] = {}
    payload: dict[str, dict[str, Any]] = {}
    dense_rank: dict[str, int] = {}
    lexical_rank: dict[str, int] = {}

    for rank, row in enumerate(dense, start=1):
        key = str(row["chunk_id"])
        payload.setdefault(key, row)
        dense_rank[key] = rank
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)

    for rank, row in enumerate(lexical, start=1):
        key = str(row["chunk_id"])
        payload.setdefault(key, row)
        lexical_rank[key] = rank
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)

    ordered = sorted(
        scores.items(),
        key=lambda item: (-item[1], dense_rank.get(item[0], 10**6), item[0]),
    )[:k]

    hits: list[Hit] = []
    for chunk_id, score in ordered:
        row = payload[chunk_id]
        hits.append(
            Hit(
                chunk_id=chunk_id,
                document_id=str(row["document_id"]),
                text=str(row["text"]),
                context=str(row["context"]),
                page_no=int(row["page_no"]) if row["page_no"] is not None else None,
                headings=tuple(row["headings"] or ()),
                scope_level=str(row["scope_level"]),
                scope_ids=tuple(row["scope_ids"] or ()),
                score=score,
                dense_rank=dense_rank.get(chunk_id),
                lexical_rank=lexical_rank.get(chunk_id),
            )
        )
    return hits
