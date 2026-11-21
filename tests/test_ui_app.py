"""The app renders, and its absence states are states rather than blanks.

These run the real Streamlit script. One test points it at a dead port to check
the page explains itself; the other supplies a stub client so the Overview is
rendered without a server or a model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

# Relative paths resolve against this file, not the working directory.
APP = str(Path(__file__).resolve().parents[1] / "src/climate_resilience/ui/run.py")
MART = Path("data/mart.db")


def envelope(
    *,
    value: float,
    mechanism: str | None,
    return_period: int | None = None,
    indicator: str = "flood_exposed_area_pct",
    scope: dict | None = None,
) -> dict:
    return {
        "indicator_id": indicator,
        "value": value,
        "unit": "percent" if indicator.endswith("_pct") else "persons",
        "mechanism": mechanism,
        "return_period_years": return_period,
        "scope": scope
        or {"id": "ethekwini-075", "name": "eThekwini 075", "level": "ward"},
        "period": {
            "start": "1960-01-01",
            "end": "1999-12-31",
            "basis": "modelled_estimate",
        },
        "quality": {
            "native_resolution": "1 km",
            "coverage_pct": 100.0,
            "warnings": ["riverine and coastal flooding only; pluvial is not modelled"],
        },
        "datasets": [
            {
                "id": "aqueduct_floods",
                "version": "v2-historical-baseline",
                "licence": "CC BY 4.0 (WRI)",
            }
        ],
        "method_id": "aqueduct_inundation_area_share",
        "method_version": "1.0.0",
    }


class StubClient:
    """The smallest API that can render the Overview for one ward."""

    def coverage(self) -> dict:
        return {"status": "ok", "envelopes": [], "scopes": [], "row_keys": []}

    def health(self) -> dict:
        return {"status": "ok", "mart_rows": 1707}

    def rank(self, indicator_id: str, **params: object) -> dict:
        return {
            "status": "ok",
            "envelopes": [
                {
                    **envelope(value=27591, mechanism=None, indicator="population_count_worldpop"),
                }
            ],
            "row_keys": ["k"],
        }

    def indicator(self, indicator_id: str, **params: object) -> dict:
        if indicator_id == "hot_days_tmax_ge_35c":
            return {"status": "insufficient", "envelopes": [], "row_keys": [], "message": "none"}
        if indicator_id == "flood_exposed_population":
            return {
                "status": "ok",
                "envelopes": [
                    envelope(value=17577, mechanism="riverine", return_period=100,
                             indicator="flood_exposed_population")
                ],
                "row_keys": ["p"],
            }
        periods = [params.get("return_period_years") or 100]
        mechanisms = [params["mechanism"]] if params.get("mechanism") else ["riverine", "coastal"]
        return {
            "status": "ok",
            "envelopes": [
                envelope(
                    value=83.588 if mechanism == "riverine" else 0.0,
                    mechanism=mechanism,
                    return_period=int(period),
                )
                for mechanism in mechanisms
                for period in periods
            ],
            "row_keys": ["a"],
        }


def test_the_page_explains_an_unreachable_api(monkeypatch) -> None:
    monkeypatch.setenv("CRP_API_URL", "http://127.0.0.1:9")

    app = AppTest.from_file(APP, default_timeout=30).run()

    assert any("Cannot reach the data" in element.value for element in app.markdown)
    assert any("make api" in element.value for element in app.markdown)


def test_the_overview_states_the_flood_figure_and_its_caveat(monkeypatch) -> None:
    pytest.importorskip("climate_resilience.ui.app")
    from climate_resilience.ui import app as app_module

    monkeypatch.setattr(app_module, "client_from_env", lambda: StubClient())

    run = AppTest.from_file(APP, default_timeout=30).run()
    text = " ".join(element.value for element in run.markdown)

    assert "83.59%" in text
    assert "100-year riverine" in text
    assert "Coastal zero" in text


def test_ward_level_heat_is_named_as_unavailable(monkeypatch) -> None:
    pytest.importorskip("climate_resilience.ui.app")
    from climate_resilience.ui import app as app_module

    monkeypatch.setattr(app_module, "client_from_env", lambda: StubClient())

    run = AppTest.from_file(APP, default_timeout=30).run()
    text = " ".join(element.value for element in run.markdown)

    assert "Not published at ward level" in text
    assert "five cells across the metro" in text
