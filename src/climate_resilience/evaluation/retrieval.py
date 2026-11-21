"""Retrieval metrics over labelled ground truth.

The assistant's document items only prove that the right document was cited.
They cannot say whether the *right passage* came back, because nobody labelled
which passages are right. This module turns those labels into numbers:

* ``recall@k``  -- of the passages that answer the question, how many are in the
  top k. Missing one is a completeness failure.
* ``mrr``       -- 1/rank of the first relevant passage. High when the best
  passage is first.
* ``ndcg@5``    -- rank-weighted gain with binary relevance, so a relevant
  passage in position 1 counts more than the same passage in position 5.

Recall and nDCG answer different questions: a system can retrieve every relevant
passage (recall 1.0) and still bury the best one (nDCG low). Both are reported.

Labels are human judgements and single-annotator. That is a limitation of the
number, not of the code, and it is stated wherever the number appears.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import Settings
from ..rag.embeddings import get_embedder
from ..rag.retrieval import hybrid_search
from ..rag.store import connect

LABELS_PATH = Path(__file__).with_name("relevance.json")


class QuestionMetrics(BaseModel):
    id: str
    question: str
    relevant: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_5: float
    retrieved: list[str] = Field(default_factory=list)


class RetrievalReport(BaseModel):
    """Retrieval quality, reported separately from answer quality."""

    questions: int
    k: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_5: float
    label_source: str
    per_question: list[QuestionMetrics] = Field(default_factory=list)


@dataclass(frozen=True)
class LabelledQuestion:
    id: str
    question: str
    relevant: frozenset[str]


def load_labels(path: Path | None = None) -> list[LabelledQuestion]:
    payload = json.loads((path or LABELS_PATH).read_text(encoding="utf-8"))
    questions = [
        LabelledQuestion(
            id=entry["id"],
            question=entry["question"],
            relevant=frozenset(entry["relevant"]),
        )
        for entry in payload["questions"]
    ]
    ids = [item.id for item in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate relevance labels")
    for item in questions:
        if not item.relevant:
            raise ValueError(f"{item.id} has no relevant chunks")
    return questions


def recall_at_k(ranked: list[str], relevant: frozenset[str], k: int) -> float:
    """Share of relevant passages present in the top k."""
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: frozenset[str]) -> float:
    """1/rank of the first relevant passage, or 0 if none is retrieved."""
    for position, chunk_id in enumerate(ranked, start=1):
        if chunk_id in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: frozenset[str], k: int) -> float:
    """Rank-weighted score with binary relevance.

    Ideal DCG assumes every relevant passage could occupy the top of the list,
    which is what makes the score comparable across questions that have
    different numbers of relevant passages.
    """
    if not relevant:
        return 0.0
    gain = sum(
        1.0 / math.log2(position + 1)
        for position, chunk_id in enumerate(ranked[:k], start=1)
        if chunk_id in relevant
    )
    ideal = sum(
        1.0 / math.log2(position + 1)
        for position in range(1, min(len(relevant), k) + 1)
    )
    return gain / ideal if ideal else 0.0


def evaluate(settings: Settings, *, k: int = 10) -> RetrievalReport:
    """Retrieve for every labelled question and average the metrics.

    Retrieval only: no model, no tool selection, no prose. Mixing it with
    answer quality would hide which half broke.
    """
    labels = load_labels()
    embedder = get_embedder()
    per_question: list[QuestionMetrics] = []

    with connect(settings.documents_dsn) as connection:
        for item in labels:
            hits = hybrid_search(
                connection, embedder, item.question, k=k, scope_id=None
            )
            ranked = [hit.chunk_id for hit in hits]
            per_question.append(
                QuestionMetrics(
                    id=item.id,
                    question=item.question,
                    relevant=len(item.relevant),
                    recall_at_5=round(recall_at_k(ranked, item.relevant, 5), 3),
                    recall_at_10=round(recall_at_k(ranked, item.relevant, 10), 3),
                    mrr=round(reciprocal_rank(ranked, item.relevant), 3),
                    ndcg_at_5=round(ndcg_at_k(ranked, item.relevant, 5), 3),
                    retrieved=ranked[:k],
                )
            )

    return RetrievalReport(
        questions=len(per_question),
        k=k,
        recall_at_5=_mean(per_question, "recall_at_5"),
        recall_at_10=_mean(per_question, "recall_at_10"),
        mrr=_mean(per_question, "mrr"),
        ndcg_at_5=_mean(per_question, "ndcg_at_5"),
        label_source=(
            "single annotator, labelled from the document text before running "
            "retrieval; sees every chunk in the corpus"
        ),
        per_question=per_question,
    )


def _mean(rows: list[QuestionMetrics], key: str) -> float:
    values = [float(getattr(row, key)) for row in rows]
    return round(sum(values) / len(values), 3) if values else 0.0
