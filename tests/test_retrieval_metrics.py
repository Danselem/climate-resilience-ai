"""Retrieval metrics, checked against hand-computed values.

These numbers decide whether the document half of the system works, so they are
tested with rankings whose scores can be worked out on paper, not with whatever
the retriever happens to return.
"""

from __future__ import annotations

import math

import pytest

from climate_resilience.evaluation.retrieval import (
    load_labels,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

RELEVANT = frozenset({"a", "d"})


def test_recall_counts_only_relevant_passages_in_the_top_k() -> None:
    ranked = ["a", "b", "c", "d", "e", "f"]

    assert recall_at_k(ranked, RELEVANT, 3) == 0.5
    assert recall_at_k(ranked, RELEVANT, 5) == 1.0


def test_recall_is_zero_when_nothing_relevant_is_retrieved() -> None:
    assert recall_at_k(["b", "c"], RELEVANT, 5) == 0.0


def test_reciprocal_rank_uses_the_first_relevant_position() -> None:
    assert reciprocal_rank(["b", "c", "a"], RELEVANT) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a", "b"], RELEVANT) == 1.0
    assert reciprocal_rank(["b", "c"], RELEVANT) == 0.0


def test_ndcg_is_one_for_a_perfect_ranking() -> None:
    assert ndcg_at_k(["a", "d"], RELEVANT, 5) == pytest.approx(1.0)


def test_ndcg_penalises_a_relevant_passage_pushed_down() -> None:
    # One relevant passage, retrieved second: gain 1/log2(3), ideal 1.
    assert ndcg_at_k(["b", "a"], frozenset({"a"}), 5) == pytest.approx(
        1 / math.log2(3)
    )


def test_ndcg_uses_the_ideal_ordering_available_for_that_question() -> None:
    # Two relevant passages, retrieved at positions 2 and 4.
    gain = 1 / math.log2(3) + 1 / math.log2(5)
    ideal = 1 + 1 / math.log2(3)

    assert ndcg_at_k(["x", "a", "y", "d"], RELEVANT, 5) == pytest.approx(
        gain / ideal
    )


def test_ndcg_ignores_relevant_passages_below_k() -> None:
    # "d" is at position 6, outside the top 5, so it earns nothing and does not
    # change the score. The ideal still counts both relevant passages, which is
    # why a missing one is penalised rather than ignored.
    with_d = ndcg_at_k(["a", "b", "c", "e", "f", "d"], RELEVANT, 5)
    without = ndcg_at_k(["a", "b", "c", "e", "f"], RELEVANT, 5)

    assert with_d == pytest.approx(without)
    assert with_d == pytest.approx(1 / (1 + 1 / math.log2(3)))


def test_the_shipped_labels_are_well_formed() -> None:
    labels = load_labels()

    assert len(labels) >= 20
    assert all(item.relevant for item in labels)
    assert all(item.question.strip().endswith("?") for item in labels)
