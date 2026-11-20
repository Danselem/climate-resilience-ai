"""The assistant: a model that selects tools and explains their results.

It never computes. Every number is a mart row, every quotation is a document
chunk, and every answer either cites what it used or states what is missing.
"""

from __future__ import annotations

from .agent import (
    ToolDeps,
    ask,
    build_agent,
    default_model,
    document_search,
    model_candidates,
)
from .guard import Refusal, preflight
from .models import (
    Answer,
    AssistantResult,
    Citation,
    DocumentHit,
    DocumentResult,
    Measurement,
    MeasurementResult,
)

__all__ = [
    "Answer",
    "AssistantResult",
    "Citation",
    "DocumentHit",
    "DocumentResult",
    "Measurement",
    "MeasurementResult",
    "Refusal",
    "ToolDeps",
    "ask",
    "build_agent",
    "default_model",
    "document_search",
    "model_candidates",
    "preflight",
]
