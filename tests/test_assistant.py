"""The assistant: budget, grounding, abstention and the flood caveat.

Every test here runs offline. FunctionModel scripts the model's decisions, so
the orchestration, the tool budget and the answer contract are exercised
without spending a token.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from test_mart import build, frame

from climate_resilience.assistant import (
    Answer,
    Citation,
    DocumentResult,
    ToolDeps,
    ask,
    build_agent,
    default_model,
    preflight,
)
from climate_resilience.assistant.agent import FLOOD_CAVEAT, MAX_ENVELOPES
from climate_resilience.config import Settings
from climate_resilience.envelope import (
    DatasetRef,
    EvidenceEnvelope,
    Period,
    Quality,
    RunRef,
    Scope,
)
from climate_resilience.store import repository

HEAT = "hot_days_tmax_ge_35c"


def settings() -> Settings:
    return Settings(database_url="sqlite://")


def engine_with_heat():
    engine = repository.make_engine("sqlite://")
    repository.ensure_schema(engine)
    rows = build(frame())
    repository.replace_build(engine, rows, indicator_id=HEAT, method_version="1.0.0")
    return engine, rows


def deps(engine=None) -> ToolDeps:
    engine = engine or engine_with_heat()[0]
    return ToolDeps(
        engine=engine,
        search=lambda query, scope_id, limit: DocumentResult.nothing("no corpus"),
    )


def requests_so_far(messages: list[Any]) -> int:
    return sum(1 for message in messages if isinstance(message, ModelRequest))


def answer_part(text: str, references: list[str]) -> ToolCallPart:
    return ToolCallPart(
        "final_result",
        {
            "text": text,
            "citations": [
                {"kind": "measurement", "reference": reference}
                for reference in references
            ],
            "abstained": False,
            "missing": [],
        },
    )


# --- guard -----------------------------------------------------------------


def test_pluvial_measurement_is_refused() -> None:
    refusal = preflight(
        "How many people are exposed to pluvial flooding in ward 75?"
    )

    assert refusal is not None
    assert "pluvial" in refusal.text.lower()
    assert refusal.missing


def test_a_pluvial_document_question_is_allowed() -> None:
    assert preflight(
        "What does the Climate Action Plan say about pluvial flooding?"
    ) is None


def test_projection_measurements_are_refused() -> None:
    refusal = preflight(
        "Which wards are projected to see longer dry spells by 2050 under RCP8.5?"
    )

    assert refusal is not None
    assert refusal.missing


def test_vulnerability_measurements_are_refused() -> None:
    refusal = preflight(
        "How many wards combine high heat exposure with socioeconomic vulnerability?"
    )

    assert refusal is not None
    assert "vulnerability" in refusal.text.lower()


def test_answerable_flood_questions_pass_the_guard() -> None:
    assert preflight(
        "Which wards have the largest share of area exposed to a 1-in-100-year riverine flood?"
    ) is None
    assert preflight(
        "How many people live in flood-exposed areas under a 1-in-100-year event?"
    ) is None


def test_an_empty_question_is_refused() -> None:
    assert preflight("   ") is not None


# --- answer contract -------------------------------------------------------


def test_an_uncited_answer_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="cite"):
        Answer(text="About 8.9% of the municipality floods.", citations=[])


def test_an_abstention_must_name_what_is_missing() -> None:
    with pytest.raises(ValueError, match="missing"):
        Answer(text="I cannot answer that.", abstained=True, missing=[])


def test_a_sourced_answer_is_valid() -> None:
    answer = Answer(
        text="8.89% of the municipal area is exposed.",
        citations=[Citation(kind="measurement", reference="abc123")],
    )

    assert answer.citations[0].reference == "abc123"


# --- configuration ---------------------------------------------------------


def test_model_ids_get_the_provider_prefix(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_SYNTHESIS", "anthropic/claude-sonnet-4")
    monkeypatch.delenv("LLM_MODEL_INTENT", raising=False)

    assert default_model() == "openrouter:anthropic/claude-sonnet-4"


def test_an_explicit_provider_is_not_rewritten(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_SYNTHESIS", "openrouter:meta/llama-3")

    assert default_model() == "openrouter:meta/llama-3"


def test_a_missing_model_is_an_explicit_error(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL_SYNTHESIS", raising=False)
    monkeypatch.delenv("LLM_MODEL_INTENT", raising=False)

    with pytest.raises(RuntimeError, match="LLM_MODEL_SYNTHESIS"):
        default_model()


def test_a_missing_api_key_abstains_without_calling_a_model(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = ask(settings(), "How many hot days in 2021?")

    assert result.answer.abstained
    assert result.requests == 0
    assert result.error == "missing OPENROUTER_API_KEY"


# --- end to end, offline ---------------------------------------------------


def test_the_agent_calls_a_tool_then_answers(monkeypatch) -> None:
    monkeypatch.setattr("climate_resilience.assistant.agent.default_model", lambda: "test")
    engine, rows = engine_with_heat()
    row_key = str(rows[0]["row_key"])

    def script(messages: list[Any], info: AgentInfo) -> ModelResponse:
        if requests_so_far(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "get_indicator",
                        {
                            "indicator_id": HEAT,
                            "scope_id": "cell_coastal",
                            "period_year": 2021,
                        },
                    )
                ]
            )
        return ModelResponse(parts=[answer_part("365 hot days.", [row_key])])

    model = FunctionModel(script)
    result = ask(
        settings(),
        "How many hot days at the coastal cell in 2021?",
        model=model,
        deps=deps(engine),
    )

    assert not result.answer.abstained
    assert result.answer.citations[0].reference == row_key
    assert result.requests == 2


def test_the_budget_stops_a_model_that_keeps_calling_tools(monkeypatch) -> None:
    monkeypatch.setattr("climate_resilience.assistant.agent.default_model", lambda: "test")
    engine, _ = engine_with_heat()

    def script(messages: list[Any], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("coverage", {})])

    result = ask(
        settings(),
        "How many hot days in 2021?",
        model=FunctionModel(script),
        deps=deps(engine),
    )

    assert result.answer.abstained
    assert result.error is not None
    assert result.answer.missing


def test_a_flood_answer_gains_the_caveat_when_the_model_omits_it(monkeypatch) -> None:
    monkeypatch.setattr("climate_resilience.assistant.agent.default_model", lambda: "test")
    engine = repository.make_engine("sqlite://")
    repository.ensure_schema(engine)

    envelope = EvidenceEnvelope(
        value=8.89,
        unit="percent",
        indicator_id="flood_exposed_area_pct",
        method_id="aqueduct_inundation_area_share",
        method_version="1.0.0",
        hazard_type="flood",
        return_period_years=100,
        depth_threshold_m=0.0,
        mechanism="riverine",
        scope=Scope(level="municipality", id="ethekwini", name="eThekwini"),
        period=Period(
            start=datetime(1960, 1, 1).date(),
            end=datetime(1999, 12, 31).date(),
            basis="modelled_estimate",
        ),
        datasets=[
            DatasetRef(
                id="aqueduct_floods",
                version="v2",
                checksum="abc",
                source_url="https://example.invalid",
                licence="CC BY 4.0",
            )
        ],
        quality=Quality(
            n_samples=317,
            coverage_pct=95.68,
            missing_pct=4.32,
            native_resolution="1 km",
            warnings=[],
        ),
        run=RunRef(
            git_commit="deadbeef",
            run_id="run",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            inputs_hash="inputs",
        ),
    )
    from climate_resilience.mart.build import to_row

    row = to_row(envelope)
    repository.replace_build(
        engine, [row], indicator_id="flood_exposed_area_pct", method_version="1.0.0"
    )

    def script(messages: list[Any], info: AgentInfo) -> ModelResponse:
        if requests_so_far(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "get_indicator",
                        {
                            "indicator_id": "flood_exposed_area_pct",
                            "scope_id": "ethekwini",
                            "mechanism": "riverine",
                            "return_period_years": 100,
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[answer_part("8.89% of the municipality is exposed.", [str(row["row_key"])])]
        )

    result = ask(
        settings(),
        "How much of the municipality is exposed to the 100-year riverine flood?",
        model=FunctionModel(script),
        deps=deps(engine),
    )

    assert FLOOD_CAVEAT in result.answer.text


def test_more_than_ten_rows_are_truncated_with_a_note() -> None:
    from climate_resilience.assistant.agent import _measurements
    from climate_resilience.tools.models import ToolOutput

    engine, rows = engine_with_heat()
    envelopes = [
        EvidenceEnvelope.model_validate_json(str(row["envelope_json"]))
        for row in rows
    ]
    keys = [f"key-{index}" for index in range(12)]
    output = ToolOutput(
        status="ok",
        envelopes=[envelopes[index % len(envelopes)] for index in range(12)],
        row_keys=keys,
    )

    result = _measurements(output, deps(engine))

    assert len(result.measurements) == MAX_ENVELOPES
    assert result.message is not None
    assert "narrow the request" in result.message


def test_the_agent_exposes_six_tools_and_structured_output() -> None:
    seen: set[str] = set()

    def script(messages: list[Any], info: AgentInfo) -> ModelResponse:
        seen.update(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[answer_part("ok", ["reference"])])

    agent = build_agent("test")
    with agent.override(model=FunctionModel(script)):
        result = agent.run_sync("question", deps=deps())

    assert seen == {
        "get_indicator",
        "rank_scopes",
        "resolve_scope",
        "coverage",
        "explain",
        "search_documents",
    }
    assert isinstance(result.output, Answer)
    assert result.output.citations[0].reference == "reference"
