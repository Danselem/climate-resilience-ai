"""Docling extraction and hybrid chunking.

Tables matter here: municipal plans put targets, budgets and ward lists in
tables, and a chunker that flattens them loses the evidence silently. Docling
keeps document structure and derives headings, so a retrieved chunk can say
which section it came from and on which page.

Scope is decided per chunk, from the text. Most of a municipal plan is
city-wide, so the default is ``municipality``; a chunk only becomes ward-scoped
when it names a ward, and that is what stops a city-wide sentence being cited
as evidence about one ward.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .catalogue import DocumentEntry

TOKENIZER_ID = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 512
# "Ward 75", "Wards 75 and 39", "wards 12, 14 and 16". The trailing group
# captures the list so a chunk is scoped to every ward it names, not just the
# first one.
WARD_PATTERN = re.compile(
    r"\bwards?\s+((?:\d{1,3}(?:\s*(?:,|and|&)\s*)?)+)", re.IGNORECASE
)
NUMBER_PATTERN = re.compile(r"\d{1,3}")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    version: str
    index: int
    text: str
    # Headings prepended for embedding and citation, e.g.
    # "Durban Climate Action Plan > Adaptation > Sea level rise".
    context: str
    page_no: int | None
    headings: tuple[str, ...]
    scope_level: str
    scope_ids: tuple[str, ...]


def chunk_document(path: Path, document: DocumentEntry) -> list[Chunk]:
    """Convert one document and split it into citable chunks."""
    from docling.chunking import HybridChunker
    from docling.document_converter import DocumentConverter

    converted = DocumentConverter().convert(str(path))
    chunker = HybridChunker(tokenizer=_tokenizer())

    chunks: list[Chunk] = []
    for index, raw in enumerate(chunker.chunk(converted.document)):
        text = raw.text.strip()
        if not text:
            continue
        headings = _headings(raw)
        scope_level, scope_ids = _scope(text, document)
        chunks.append(
            Chunk(
                chunk_id=_chunk_id(document.id, index, text),
                document_id=document.id,
                version=document.version,
                index=index,
                text=text,
                context=chunker.contextualize(raw).strip(),
                page_no=_page(raw),
                headings=headings,
                scope_level=scope_level,
                scope_ids=scope_ids,
            )
        )
    if not chunks:
        raise RuntimeError(f"{document.id}: no text extracted from {path}")
    return chunks


def _headings(raw: object) -> tuple[str, ...]:
    meta = getattr(raw, "meta", None)
    headings = getattr(meta, "headings", None) or []
    return tuple(str(heading) for heading in headings)


def _page(raw: object) -> int | None:
    meta = getattr(raw, "meta", None)
    items = getattr(meta, "doc_items", None) or []
    for item in items:
        provenance = getattr(item, "prov", None) or []
        for entry in provenance:
            page = getattr(entry, "page_no", None)
            if page is not None:
                return int(page)
    return None


def _chunk_id(document_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{document_id}:{index}:{text}".encode()).hexdigest()
    return digest[:32]


@lru_cache(maxsize=1)
def _tokenizer():
    """Load the chunker's tokenizer once.

    It is the embedding model's tokenizer, so chunk boundaries and the model's
    context window cannot drift apart.
    """
    from docling_core.transforms.chunker.tokenizer.huggingface import (
        HuggingFaceTokenizer,
    )

    return HuggingFaceTokenizer.from_pretrained(
        model_name=TOKENIZER_ID, max_tokens=MAX_TOKENS
    )


def ward_numbers(text: str) -> list[int]:
    """Every ward number the text names, in order, without duplicates."""
    numbers: set[int] = set()
    for match in WARD_PATTERN.finditer(text):
        for raw in NUMBER_PATTERN.findall(match.group(1)):
            numbers.add(int(raw))
    return sorted(numbers)


def _scope(text: str, document: DocumentEntry) -> tuple[str, tuple[str, ...]]:
    """Ward scope only when the text names wards; otherwise inherited."""
    if document.scope_level == "ward" and document.scope_ids:
        return "ward", tuple(document.scope_ids)
    numbers = ward_numbers(text)
    if numbers:
        return "ward", tuple(f"ethekwini-{number:03d}" for number in numbers)
    return "municipality", tuple(document.scope_ids or ["ethekwini"])
