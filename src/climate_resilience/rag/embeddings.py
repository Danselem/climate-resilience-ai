"""Local sentence embeddings.

Chosen over a hosted embedding endpoint for three reasons: no per-query cost,
~20 ms latency inside a 6 s budget, and document text never leaves the machine.
The trade is a one-off model download and a torch dependency, which is recorded
rather than hidden.

``all-MiniLM-L6-v2`` is 384-dimensional and English-only. The corpus is English,
and a multilingual model would cost ~5x the memory for no measured gain here.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Protocol

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384


class Embedder(Protocol):
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """SentenceTransformer wrapper with normalised output."""

    dimension = DIMENSION

    def __init__(self, model_id: str = MODEL_ID) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_id = model_id
        self._model = SentenceTransformer(model_id)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]


class HashingEmbedder:
    """Deterministic stand-in for tests: no model download, no network.

    It is not semantically meaningful, so it is only used to exercise storage
    and ranking plumbing. Retrieval quality is never measured with it.
    """

    dimension = DIMENSION

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        import hashlib
        import math

        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:2], "big") % self.dimension
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


_embedder: LocalEmbedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> LocalEmbedder:
    """Load the model once, even when a warm-up thread races the first query."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = LocalEmbedder()
    return _embedder
