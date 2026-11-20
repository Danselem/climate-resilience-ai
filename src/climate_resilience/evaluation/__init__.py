"""Evaluation: mechanical checks over a fixed gold set.

Retrieval and analytical correctness are scored separately, because they fail
for different reasons and a single blended number hides which half broke.
"""

from __future__ import annotations

from .models import BenchmarkItem, BenchmarkReport, ItemResult, Reference
from .runner import load_benchmark, run_benchmark, summarise

__all__ = [
    "BenchmarkItem",
    "BenchmarkReport",
    "ItemResult",
    "Reference",
    "load_benchmark",
    "run_benchmark",
    "summarise",
]
