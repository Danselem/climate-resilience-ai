"""Presentation helpers and client error handling.

The UI's promise is that a unit is never dropped and an absence is never shown
as a zero. Those are text decisions, so they are tested as text — no browser,
no network.
"""

from __future__ import annotations

import httpx
import pytest

from climate_resilience.ui import presentation
from climate_resilience.ui.client import (
    ApiClient,
    ApiTimeout,
    ApiUnauthorized,
    ApiUnavailable,
    client_from_env,
)


def envelope(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "indicator_id": "flood_exposed_area_pct",
        "value": 83.588,
        "unit": "percent",
        "mechanism": "riverine",
        "return_period_years": 100,
        "period": {"start": "1960-01-01", "end": "1999-12-31", "basis": "modelled_estimate"},
        "scope": {"id": "ethekwini-075", "name": "eThekwini 075", "level": "ward"},
        "quality": {"native_resolution": "1 km", "coverage_pct": 100.0, "warnings": []},
        "datasets": [],
        "method_id": "aqueduct_inundation_area_share",
        "method_version": "1.0.0",
    }
    base.update(overrides)
    return base


def test_the_hero_states_mechanism_and_return_period() -> None:
    sentence = presentation.hero_sentence(
        "Ward 75",
        area_pct=83.588,
        mechanism="riverine",
        return_period=100,
        people_exposed=17577,
    )

    assert "83.59%" in sentence
    assert "100-year riverine" in sentence
    assert "17,577" in sentence


def test_the_hero_says_what_is_missing_instead_of_leaving_a_hole() -> None:
    sentence = presentation.hero_sentence(
        "Ward 75", area_pct=None, mechanism=None, return_period=None, people_exposed=None
    )

    assert "No flood exposure value" in sentence


def test_a_bar_never_overflows_its_track() -> None:
    html = presentation.bar_html("Riverine", 108.0, maximum=100, colour="#0E5A6B")

    assert "width:100.0%" in html


def test_a_bar_renders_a_zero_as_empty_not_as_a_missing_bar() -> None:
    html = presentation.bar_html("Coastal", 0.0, maximum=100, colour="#B07A1E")

    assert "width:0.0%" in html
    assert "0.00%" in html


def test_a_single_point_series_says_so_rather_than_drawing_a_line() -> None:
    assert "Not enough years" in presentation.sparkline([(2025, 2.7)])


def test_quantile_bins_are_monotonic() -> None:
    edges = presentation.quantile_bins([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

    assert edges == sorted(edges)
    assert len(edges) == 4


def test_a_missing_ward_stays_grey_rather_than_taking_a_colour() -> None:
    assert presentation.shade(0.0, [], "#0E5A6B") == "#E4E6E1"


def test_the_client_reads_configuration_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("CRP_API_URL", "http://example.test:9000")
    monkeypatch.delenv("CRP_API_KEY", raising=False)

    client = client_from_env()

    assert client.base_url == "http://example.test:9000"
    assert client.api_key is None


def test_a_refused_connection_becomes_an_instruction(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "request", refuse)

    with pytest.raises(ApiUnavailable, match="make api"):
        ApiClient().coverage()


def test_a_timeout_names_the_seconds(monkeypatch) -> None:
    def slow(*args, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "request", slow)

    with pytest.raises(ApiTimeout, match="15 s"):
        ApiClient().coverage()


def test_a_keyed_deployment_explains_itself(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx, "request", lambda *a, **k: httpx.Response(401, request=httpx.Request("GET", "http://x"))
    )

    with pytest.raises(ApiUnauthorized, match="CRP_API_KEY"):
        ApiClient().coverage()
