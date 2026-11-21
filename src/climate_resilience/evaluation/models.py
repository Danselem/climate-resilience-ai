"""Benchmark items and results.

An item states what a correct answer must contain, in terms a machine can check
without asking the system under test. Analytical items name a published row by
its parameters; the runner resolves the expected row independently.

Items come in four kinds, and the kind decides what "pass" means:

* ``analytical``    - must cite the expected mart row
* ``document``      - must cite a chunk from the expected document
* ``abstain``       - must refuse and name a gap
* ``adversarial``   - must refuse or stay grounded, and must not leak
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["analytical", "document", "abstain", "adversarial"]


class Reference(BaseModel):
    """How to find the expected row, without naming its row_key.

    The runner resolves this with raw SQL, so the expectation does not come
    from the tools being tested.
    """

    indicator_id: str
    scope_id: str | None = None
    scope_level: str | None = None
    mechanism: str | None = None
    return_period_years: int | None = None
    period_year: int | None = None


class BenchmarkItem(BaseModel):
    id: str
    question: str
    category: Category
    expected_tools: list[str] = Field(default_factory=list)
    reference: Reference | None = None
    expected_document: str | None = None
    expected_abstention: bool = False
    # Substrings the answer must contain: "pluvial" for a flood caveat, a place
    # name for a scope check.
    must_mention: list[str] = Field(default_factory=list)
    # Substrings whose presence is a failure: leaked secrets, injected text,
    # a claimed risk score.
    must_not_contain: list[str] = Field(default_factory=list)
    notes: str | None = None


class ItemResult(BaseModel):
    id: str
    category: Category
    question: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    abstained: bool = False
    citations: int = 0
    seconds: float = 0.0
    cost_usd: float | None = None
    model: str | None = None
    error: str | None = None


class BenchmarkReport(BaseModel):
    run_at: str
    model: str | None
    items: list[ItemResult]
    # Retrieval quality is measured against labelled passages and reported
    # beside answer quality, never folded into it.
    retrieval: dict[str, object] | None = None

    def by_category(self) -> dict[str, tuple[int, int]]:
        totals: dict[str, list[int]] = {}
        for item in self.items:
            bucket = totals.setdefault(item.category, [0, 0])
            bucket[0] += 1
            bucket[1] += 1 if item.passed else 0
        return {key: (value[0], value[1]) for key, value in totals.items()}

    def failures(self) -> list[ItemResult]:
        return [item for item in self.items if not item.passed]
