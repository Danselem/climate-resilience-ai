"""pgvector storage for document chunks.

The vector index holds prose only. It is deliberately a different store from
the mart: measurements need exact keys and provenance, prose needs similarity
search, and mixing them would let a nearest-neighbour result masquerade as a
calculated value.

Ten documents produce a few thousand chunks, so a single table with an HNSW
index is enough. Nothing here is sized for millions of rows, and the schema
says so rather than implying scale it does not have.
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from .chunking import Chunk

SCHEMA = """
create extension if not exists vector;

create table if not exists document_chunk (
    chunk_id     text primary key,
    document_id  text not null,
    version      text not null,
    chunk_index  integer not null,
    text         text not null,
    context      text not null,
    page_no      integer,
    headings     text[] not null default '{{}}',
    scope_level  text not null,
    scope_ids    text[] not null default '{{}}',
    embedding    vector({dimension}) not null
);

create index if not exists ix_document_chunk_document
    on document_chunk (document_id);
create index if not exists ix_document_chunk_scope
    on document_chunk (scope_level);
create index if not exists ix_document_chunk_fts
    on document_chunk using gin (to_tsvector('english', text));
create index if not exists ix_document_chunk_embedding
    on document_chunk using hnsw (embedding vector_cosine_ops);
"""


def connect(dsn: str) -> psycopg.Connection:
    connection = psycopg.connect(dsn, row_factory=dict_row)
    register_vector(connection)
    return connection


def ensure_schema(connection: psycopg.Connection, *, dimension: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA.format(dimension=int(dimension)))
    connection.commit()


def replace_document(
    connection: psycopg.Connection,
    *,
    document_id: str,
    chunks: Sequence[Chunk],
    embeddings: Sequence[Sequence[float]],
) -> int:
    """Replace every chunk of one document, atomically.

    Scoped by document id, not by version: two versions of the same document
    must not both be retrievable, or a citation can point at text that has been
    superseded.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"{document_id}: {len(chunks)} chunks but {len(embeddings)} embeddings"
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "delete from document_chunk where document_id = %s", (document_id,)
        )
        cursor.executemany(
            """
            insert into document_chunk (
                chunk_id, document_id, version, chunk_index, text, context,
                page_no, headings, scope_level, scope_ids, embedding
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.version,
                    chunk.index,
                    chunk.text,
                    chunk.context,
                    chunk.page_no,
                    list(chunk.headings),
                    chunk.scope_level,
                    list(chunk.scope_ids),
                    Vector(list(vector)),
                )
                for chunk, vector in zip(chunks, embeddings, strict=True)
            ],
        )
    connection.commit()
    return len(chunks)


def count(connection: psycopg.Connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("select count(*) as n from document_chunk")
        row = cursor.fetchone()
    return int(row["n"]) if row else 0


def documents(connection: psycopg.Connection) -> list[dict[str, object]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select document_id, version, count(*) as chunks
            from document_chunk group by document_id, version
            order by document_id
            """
        )
        return [dict(row) for row in cursor.fetchall()]
