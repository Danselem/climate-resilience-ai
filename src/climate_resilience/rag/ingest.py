"""Turn catalogue entries into indexed chunks.

The checksum is verified before extraction, not after: indexing a file that no
longer matches its catalogue entry would silently detach every citation from
the text it refers to.

Documents are replaced whole. Two versions of the same plan must not be
retrievable at once, or a citation can point at a superseded target.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..manifest import sha256_file
from . import catalogue, chunking, embeddings, store


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    chunks: int
    checksum: str


def ingest_all(
    settings: Settings,
    *,
    only: str | None = None,
    rebuild: bool = False,
) -> list[IngestResult]:
    catalogue_path = settings.catalogue_dir / "documents.json"
    documents = catalogue.load(catalogue_path)
    embedder = embeddings.get_embedder()
    connection = store.connect(settings.documents_dsn)
    try:
        if rebuild:
            store.reset(connection)
        store.ensure_schema(connection, dimension=embedder.dimension)
        results: list[IngestResult] = []
        for document in documents.active():
            if only is not None and document.id != only:
                continue
            path = settings.data_dir / str(document.artifact)
            if not path.exists():
                raise FileNotFoundError(
                    f"{document.id}: artefact missing at {path}; acquire it before ingesting"
                )
            checksum = sha256_file(path)
            if document.checksum and checksum != document.checksum:
                raise RuntimeError(
                    f"{document.id}: checksum mismatch "
                    f"(catalogue {document.checksum[:12]}…, file {checksum[:12]}…)"
                )
            chunks = chunking.chunk_document(path, document)
            vectors = embedder.embed([chunk.context for chunk in chunks])
            store.replace_document(
                connection,
                document_id=document.id,
                chunks=chunks,
                embeddings=vectors,
            )
            results.append(
                IngestResult(document.id, len(chunks), checksum)
            )
        if only is None:
            # A document removed from the catalogue must stop being retrievable.
            # Ingest only ever replaces what it is handed, so a deactivated plan
            # would otherwise keep answering questions for years.
            store.drop_documents_except(
                connection, [document.id for document in documents.active()]
            )
        return results
    finally:
        connection.close()
