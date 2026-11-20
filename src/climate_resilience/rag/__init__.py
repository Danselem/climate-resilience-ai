"""Document retrieval (RAG) as a supporting capability.

The vector index holds prose about plans, strategies and metadata. It never
holds measurements: those stay in the mart, where a query returns an exact
value with its envelope.
"""

from __future__ import annotations

from .catalogue import DocumentCatalogue, DocumentEntry, load
from .chunking import Chunk, chunk_document

__all__ = [
    "Chunk",
    "DocumentCatalogue",
    "DocumentEntry",
    "chunk_document",
    "load",
]
