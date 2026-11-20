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
    DocumentResult,
    Measurement,
    ToolDeps,
    ask,
    build_agent,
    default_model,
    model_candidates,
    preflight,
)
from climate_resilience.assistant.agent import FLOOD_CAVEAT, MAX_ROWS
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


def answer_part(text: str, references: list[str] | None = None) -> ToolCallPart:
    return ToolCallPart(
        "final_result",
        {"text": text, "abstained": False, "missing": []},
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


def test_citations_are_derived_not_transcribed() -> None:
    from climate_resilience.assistant.agent import _citations

    deps_ = deps()
    deps_.seen.append(
        Measurement(
            row_key="row-1",
            indicator_id=HEAT,
            value=1.0,
            unit="days",
            scope_level="ward",
            scope_id="ethekwini-001",
            scope_name="Ward 1",
            period_start="2020-01-01",
            period_end="2020-12-31",
            hazard_type="heat",
            basis="reanalysis",
            coverage_pct=100.0,
        )
    )

    citations = _citations(deps_)

    assert [(c.kind, c.reference) for c in citations] == [("measurement", "row-1")]


def test_an_abstention_must_name_what_is_missing() -> None:
    with pytest.raises(ValueError, match="missing"):
        Answer(text="I cannot answer that.", abstained=True, missing=[])


def test_an_answer_carries_no_citation_field() -> None:
    answer = Answer(text="8.89% of the municipal area is exposed.")

    assert "citations" not in answer.model_dump()


def flood_measurement(value: float, mechanism: str = "riverine") -> Measurement:
    return Measurement(
        row_key="row-flood",
        indicator_id="flood_exposed_area_pct",
        value=value,
        unit="percent",
        scope_level="ward",
        scope_id="ethekwini-075",
        scope_name="eThekwini 075",
        period_start="1960-01-01",
        period_end="1999-12-31",
        hazard_type="flood",
        mechanism=mechanism,
        return_period_years=100,
        depth_threshold_m=0.0,
        basis="modelled_estimate",
        coverage_pct=100.0,
    )


def test_a_no_risk_claim_beside_positive_exposure_is_caught() -> None:
    from climate_resilience.assistant.agent import _contradicts_evidence

    answer = Answer(text="Ward 75 has no flood risk.")

    found = _contradicts_evidence(answer, [flood_measurement(83.588)])

    assert found is not None
    assert found.value == 83.588


def test_a_no_risk_claim_beside_zero_exposure_is_allowed() -> None:
    from climate_resilience.assistant.agent import _contradicts_evidence

    answer = Answer(text="The coast has no flood risk in this model.")

    assert _contradicts_evidence(answer, [flood_measurement(0.0, "coastal")]) is None


def test_an_abstention_is_never_treated_as_a_contradiction() -> None:
    from climate_resilience.assistant.agent import _contradicts_evidence

    answer = Answer(text="I cannot say it is safe.", abstained=True, missing=["data"])

    assert _contradicts_evidence(answer, [flood_measurement(83.588)]) is None


def test_an_ordinary_negative_sentence_is_not_flagged() -> None:
    from climate_resilience.assistant.agent import _contradicts_evidence

    answer = Answer(text="83.6% of ward 75 is exposed; this is not a small share.")

    assert _contradicts_evidence(answer, [flood_measurement(83.588)]) is None


# --- configuration ---------------------------------------------------------


def test_model_ids_get_the_provider_prefix(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_SYNTHESIS", "anthropic/claude-sonnet-4")
    monkeypatch.delenv("LLM_MODEL_INTENT", raising=False)

    assert default_model() == "openrouter:anthropic/claude-sonnet-4"


def test_an_explicit_provider_is_not_rewritten(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_SYNTHESIS", "openrouter:meta/llama-3")

    assert default_model() == "openrouter:meta/llama-3"


def test_an_unconfigured_system_uses_the_default_pair(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODELS", raising=False)
    monkeypatch.delenv("LLM_MODEL_SYNTHESIS", raising=False)
    monkeypatch.delenv("LLM_MODEL_INTENT", raising=False)

    assert model_candidates() == [
        "openrouter:amazon/nova-micro-v1",
        "openrouter:particle-ai/particle-1:free",
    ]


def test_a_free_suffix_is_not_mistaken_for_a_provider_prefix(monkeypatch) -> None:
    monkeypatch.setenv(
        "LLM_MODELS",
        "particle-ai/particle-1:free, openrouter:google/gemma-4-31b-it:free",
    )

    assert model_candidates() == [
        "openrouter:particle-ai/particle-1:free",
        "openrouter:google/gemma-4-31b-it:free",
    ]


def test_two_candidates_become_a_fallback_chain(monkeypatch) -> None:
    from pydantic_ai.models.fallback import FallbackModel

    from climate_resilience.assistant.agent import _model_chain

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    chain = _model_chain(["openrouter:a/b", "openrouter:c/d"])

    assert isinstance(chain, FallbackModel)


def test_one_candidate_is_passed_through_unwrapped() -> None:
    from climate_resilience.assistant.agent import _model_chain

    assert _model_chain(["openrouter:a/b"]) == "openrouter:a/b"


def test_cost_comes_from_published_prices(monkeypatch) -> None:
    from climate_resilience.assistant import pricing

    monkeypatch.setattr(pricing, "_prices", lambda: {"x/y": (1e-6, 2e-6)})

    assert pricing.estimate_cost("openrouter:x/y", 1000, 500) == pytest.approx(0.002)


def test_an_unpriced_model_reports_no_cost_rather_than_zero(monkeypatch) -> None:
    from climate_resilience.assistant import pricing

    monkeypatch.setattr(pricing, "_prices", lambda: {})

    assert pricing.estimate_cost("unknown/model", 100, 100) is None


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
    assert result.citations, "citations come from the evidence the run used"
    assert result.citations[0].kind == "measurement"
    assert result.citations[0].reference in {str(row["row_key"]) for row in rows}
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


def test_more_than_five_rows_are_truncated_with_a_note() -> None:
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

    assert len(result.measurements) == MAX_ROWS
    assert result.message is not None
    assert "narrow the request" in result.message
    assert result.caveats, "caveats are hoisted, not dropped"
    assert result.sources, "sources are hoisted, not dropped"
    assert result.method is not None


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
