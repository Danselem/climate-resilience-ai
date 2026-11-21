"""API contract tests.

These check the properties the specification promises, not just that a route
returns 200: unknown values are typed failures rather than 404-with-nothing,
flood questions cannot be answered without naming a mechanism, and no endpoint
accepts a parameter the tools would have to defend themselves against.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from climate_resilience.api.app import create_app
from climate_resilience.config import Settings

MART = Path("data/mart.db")
pytestmark = pytest.mark.skipif(
    not MART.exists(), reason="run `climate-resilience mart` to build data/mart.db"
)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    settings = Settings(database_url=f"sqlite:///{MART}")
    with TestClient(create_app(settings, search=lambda *a: None)) as test_client:  # type: ignore[arg-type]
        yield test_client


def test_health_reports_the_mart_is_populated(client: TestClient) -> None:
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["mart_rows"] > 1000


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["x-request-id"]


def test_a_supplied_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health", headers={"x-request-id": "abc123"})

    assert response.headers["x-request-id"] == "abc123"


def test_an_indicator_returns_envelopes_with_provenance(client: TestClient) -> None:
    body = client.get(
        "/indicators/hot_days_tmax_ge_35c",
        params={"scope_id": "ethekwini", "period_year": 2025},
    ).json()

    assert body["status"] == "ok"
    envelope = body["envelopes"][0]
    assert envelope["datasets"][0]["licence"]
    assert envelope["run"]["git_commit"]
    assert envelope["method_version"]


def test_a_flood_value_without_a_mechanism_returns_both_labelled(
    client: TestClient,
) -> None:
    """No mechanism means every mechanism, each labelled — never a total."""
    body = client.get(
        "/indicators/flood_exposed_area_pct",
        params={"scope_id": "ethekwini", "return_period_years": 100},
    ).json()

    assert body["status"] == "ok"
    mechanisms = {envelope["mechanism"] for envelope in body["envelopes"]}
    assert mechanisms == {"riverine", "coastal"}
    assert all(envelope["return_period_years"] == 100 for envelope in body["envelopes"])
    assert "must never be summed" in (body["message"] or "")


def test_an_unknown_indicator_is_a_typed_failure_not_a_500(
    client: TestClient,
) -> None:
    response = client.get("/indicators/coastal_erosion_rate")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient"
    assert body["available"]["indicators"]


def test_an_invalid_return_period_is_rejected_before_any_tool_runs(
    client: TestClient,
) -> None:
    response = client.get(
        "/indicators/flood_exposed_area_pct",
        params={"return_period_years": 7},
    )

    assert response.status_code == 422


def test_rank_refuses_a_flood_ranking_without_a_return_period(
    client: TestClient,
) -> None:
    body = client.get(
        "/rank", params={"indicator_id": "flood_exposed_area_pct", "mechanism": "riverine"}
    ).json()

    assert body["status"] == "insufficient"
    assert "return_period_years" in body["missing"]


def test_rank_returns_wards_in_descending_order(client: TestClient) -> None:
    body = client.get(
        "/rank",
        params={
            "indicator_id": "flood_exposed_area_pct",
            "mechanism": "riverine",
            "return_period_years": 100,
            "limit": 5,
        },
    ).json()

    assert body["status"] == "ok"
    values = [envelope["value"] for envelope in body["envelopes"]]
    assert values == sorted(values, reverse=True)
    assert len(values) == 5


def test_a_scope_is_resolvable_by_the_name_a_planner_uses(
    client: TestClient,
) -> None:
    body = client.get("/scopes", params={"q": "Durban"}).json()

    assert body["status"] == "ok"
    assert body["scopes"][0]["id"] == "ethekwini"


def test_coverage_lists_what_exists_so_a_refusal_can_be_specific(
    client: TestClient,
) -> None:
    body = client.get("/coverage").json()

    assert "flood_exposed_area_pct" in body["available"]["indicators"]
    assert body["available"]["return_periods"] == [10, 50, 100]


def test_a_row_explains_itself_and_an_unknown_key_does_not(client: TestClient) -> None:
    listed = client.get(
        "/indicators/flood_exposed_area_pct",
        params={
            "scope_id": "ethekwini",
            "mechanism": "riverine",
            "return_period_years": 100,
        },
    ).json()
    row_key = listed["row_keys"][0]

    explained = client.get(f"/rows/{row_key}").json()
    missing = client.get("/rows/not-a-row").json()

    assert explained["status"] == "ok"
    assert missing["status"] == "insufficient"


def test_openapi_lists_every_published_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert {
        "/health",
        "/coverage",
        "/scopes",
        "/indicators/{indicator_id}",
        "/rank",
        "/rows/{row_key}",
        "/documents/search",
        "/ask",
    } <= set(paths)


def test_a_configured_key_is_required_and_an_unset_one_is_not() -> None:
    settings = Settings(database_url=f"sqlite:///{MART}", api_key="secret-key")
    with TestClient(create_app(settings, search=lambda *a: None)) as guarded:  # type: ignore[arg-type]
        assert guarded.get("/health").status_code == 200
        assert guarded.get("/coverage").status_code == 401
        assert (
            guarded.get("/coverage", headers={"x-api-key": "secret-key"}).status_code
            == 200
        )
        assert (
            guarded.get("/coverage", headers={"x-api-key": "wrong"}).status_code == 401
        )


def test_the_ask_endpoint_validates_the_question_before_calling_a_model(
    client: TestClient,
) -> None:
    response = client.post("/ask", json={"question": "x"})

    assert response.status_code == 422


def test_the_ask_endpoint_refuses_pluvial_at_zero_cost(client: TestClient) -> None:
    body = client.post(
        "/ask", json={"question": "How many people are exposed to pluvial flooding?"}
    ).json()

    assert body["refused_by_guard"] is True
    assert body["requests"] == 0
