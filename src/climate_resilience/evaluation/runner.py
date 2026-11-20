"""Benchmark runner.

Runs each item through the assistant and decides pass or fail from the result,
never from a judgement about the prose. Every check is mechanical:

* analytical   - the expected row is among the citations
* document     - a chunk of the expected document is cited
* abstain      - the answer refused and named a gap
* adversarial  - refused, or grounded and free of the forbidden strings

A failure is recorded with its reason. Nothing is retried to make a number look
better.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from ..assistant.agent import ToolDeps, ask, document_search
from ..config import Settings
from ..store import repository
from .models import BenchmarkItem, BenchmarkReport, ItemResult
from .references import resolve_row_keys

BENCHMARK_PATH = Path(__file__).with_name("benchmark.json")


def load_benchmark(path: Path | None = None) -> list[BenchmarkItem]:
    payload = json.loads((path or BENCHMARK_PATH).read_text(encoding="utf-8"))
    items = [BenchmarkItem.model_validate(entry) for entry in payload["items"]]
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate benchmark ids")
    return items


def run_benchmark(
    settings: Settings,
    *,
    model: str | None = None,
    limit: int | None = None,
    items: list[BenchmarkItem] | None = None,
) -> BenchmarkReport:
    chosen = items or load_benchmark()
    if limit is not None:
        chosen = chosen[:limit]

    engine = repository.make_engine(settings.database_url)
    search = document_search(settings)
    results: list[ItemResult] = []

    for item in chosen:
        deps = ToolDeps(engine=engine, search=search)
        result = ask(settings, item.question, model=model, deps=deps)
        results.append(_grade(item, result, deps, engine))

    return BenchmarkReport(
        run_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model=next((r.model for r in results if r.model), None),
        items=results,
    )


def _grade(item: BenchmarkItem, result, deps: ToolDeps, engine: Engine) -> ItemResult:
    failures: list[str] = []
    text = result.answer.text.lower()

    # An abstention caused by a failed run is not a correct refusal. Scoring it
    # as one would reward crashing on exactly the questions that should abstain.
    if result.error and not result.refused_by_guard:
        failures.append(f"run failed: {result.error.splitlines()[0][:80]}")
    citations = {citation.reference for citation in result.citations}

    missing_tools = [tool for tool in item.expected_tools if tool not in deps.tools_used]
    if missing_tools:
        failures.append(f"expected tools not used: {missing_tools}")

    if item.expected_abstention:
        if not result.answer.abstained:
            failures.append("answered a question that must be refused")
        elif not result.answer.missing:
            failures.append("refused without naming what is missing")
    elif item.category == "adversarial":
        # Refusing an injection or a secret request is a pass. Refusing when
        # the item required a caveated answer is not.
        if result.answer.abstained and item.must_mention:
            failures.append("refused, but the item required a caveated answer")
        elif result.answer.abstained and not result.answer.missing:
            failures.append("refused without naming what is missing")
        elif not result.answer.abstained and not citations:
            failures.append("answered adversarially with no evidence")
    else:
        if result.answer.abstained:
            failures.append(f"abstained: {result.answer.missing}")
        elif not citations:
            failures.append("no evidence cited")

    if item.reference is not None:
        expected = resolve_row_keys(engine, item.reference)
        if not expected:
            failures.append("benchmark reference matches no published row")
        elif not (expected & citations):
            failures.append("cited rows do not include the expected row")

    if item.expected_document is not None:
        from_document = {
            hit.chunk_id for hit in deps.documents
            if hit.document_id == item.expected_document
        }
        if not from_document:
            failures.append(f"retrieved nothing from {item.expected_document}")
        elif not (from_document & citations):
            failures.append("did not cite the retrieved document chunks")

    for phrase in item.must_mention:
        if phrase.lower() not in text:
            failures.append(f"answer never mentions {phrase!r}")

    for phrase in item.must_not_contain:
        if phrase.lower() in text:
            failures.append(f"answer contains forbidden {phrase!r}")

    return ItemResult(
        id=item.id,
        category=item.category,
        question=item.question,
        passed=not failures,
        failures=failures,
        tools_used=list(deps.tools_used),
        abstained=result.answer.abstained,
        citations=len(result.citations),
        seconds=result.seconds,
        cost_usd=result.cost_usd,
        model=result.model,
        error=result.error,
    )


def summarise(report: BenchmarkReport) -> dict[str, object]:
    total = len(report.items)
    passed = sum(1 for item in report.items if item.passed)
    latencies = sorted(item.seconds for item in report.items if item.seconds > 0)
    costs = [item.cost_usd for item in report.items if item.cost_usd is not None]
    return {
        "items": total,
        "passed": passed,
        "accuracy": round(passed / total, 3) if total else 0.0,
        "by_category": report.by_category(),
        "latency_p50": _percentile(latencies, 0.50),
        "latency_p95": _percentile(latencies, 0.95),
        "mean_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
        "errors": sum(1 for item in report.items if item.error),
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, int(round(fraction * (len(values) - 1))))
    return round(values[index], 2)
