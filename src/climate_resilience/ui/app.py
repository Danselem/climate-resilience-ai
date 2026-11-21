"""The interface: one sheet, four views.

Every number on this page came from the API, which got it from the mart. The UI
does not import the tools, does not read the database, and cannot compute. That
is why the page can promise what it promises.

Run with `make ui` (the API must be up: `make api`).
"""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from .client import ApiClient, ApiError, client_from_env
from .presentation import (
    bar_html,
    hero_sentence,
    mechanism_colour,
    pct,
    people,
    sparkline,
)
from .theme import COASTAL, MUTED, RIVERINE, inject
from .ward_map import build as build_map

HEAT = "hot_days_tmax_ge_35c"
POPULATION = "population_count_worldpop"
FLOOD_AREA = "flood_exposed_area_pct"
FLOOD_POPULATION = "flood_exposed_population"

EXAMPLES = [
    "Which wards have the largest share of area exposed to a 100-year riverine flood?",
    "How many people are exposed to the 100-year riverine flood in eThekwini?",
    "What does the Climate Action Plan say about sea level rise?",
]


def main(client: ApiClient | None = None) -> None:
    st.set_page_config(
        page_title="eThekwini climate evidence",
        page_icon="◼",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject()
    api = client or client_from_env()

    if "view" not in st.session_state:
        st.session_state.view = "Overview"

    try:
        coverage = api.coverage()
        scopes = _scopes(api)
    except ApiError as error:
        _header(None)
        st.markdown(f"<div class='stamp'><b>Cannot reach the data.</b> {escape(str(error))}</div>",
                    unsafe_allow_html=True)
        return

    scope_id, scope_label = _header(scopes)
    view = st.segmented_control(
        "View",
        options=["Overview", "Explorer", "Ask", "Report"],
        default=st.session_state.view,
        label_visibility="collapsed",
    )
    st.session_state.view = view or "Overview"
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)

    try:
        if st.session_state.view == "Overview":
            _overview(api, scope_id, scope_label, coverage)
        elif st.session_state.view == "Explorer":
            _explorer(api, scope_id)
        elif st.session_state.view == "Ask":
            _ask(api)
        else:
            _report(api, scope_id)
    except ApiError as error:
        st.markdown(
            f"<div class='refusal'><div class='what'>{escape(str(error))}</div></div>",
            unsafe_allow_html=True,
        )


# --- frame -----------------------------------------------------------------


def _header(scopes: list[tuple[str, str]] | None) -> tuple[str, str]:
    brand, picker = st.columns([2, 1], vertical_alignment="bottom")
    with brand:
        st.markdown(
            "<div class='sheet-head'><div class='brand'>eThekwini climate evidence"
            "<span> · published indicators</span></div>"
            "<div class='scope-line'>riverine · coastal · heat · population</div></div>",
            unsafe_allow_html=True,
        )
    with picker:
        if not scopes:
            st.markdown(
                "<div class='scope-line'>scope unavailable</div>", unsafe_allow_html=True
            )
            return "ethekwini", ""
        labels = dict(scopes)
        selected = st.selectbox(
            "Scope",
            options=[scope_id for scope_id, _ in scopes],
            format_func=lambda scope_id: labels[scope_id],
            label_visibility="collapsed",
        )
    return selected, labels[selected]


def _scopes(api: ApiClient) -> list[tuple[str, str]]:
    """Municipality and every ward that publishes a population value."""
    ranked = api.rank(POPULATION, limit=200)
    scopes = [("ethekwini", "eThekwini (municipality)")]
    for envelope in ranked.get("envelopes", []):
        scope = envelope["scope"]
        if scope["level"] == "ward":
            number = scope.get("id", "").rsplit("-", 1)[-1]
            scopes.append((scope["id"], f"Ward {int(number)} · {scope['name']}"))
    return scopes


def _title_block(health: dict[str, Any], meta: str) -> None:
    st.markdown(
        "<div class='titleblock'>"
        f"<span>{escape(meta)}</span>"
        f"<span>{health.get('mart_rows', 0):,} published rows</span>"
        "<span>EPSG:4326 · computed in EPSG:32736</span>"
        "</div>",
        unsafe_allow_html=True,
    )


# --- overview --------------------------------------------------------------


def _overview(
    api: ApiClient, scope_id: str, scope_label: str, coverage: dict[str, Any]
) -> None:
    name = scope_label.split(" · ")[-1] if scope_label else "eThekwini"
    name = name.replace(" (municipality)", "")

    flood: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
    for return_period in (10, 50, 100):
        result = api.indicator(
            FLOOD_AREA, scope_id=scope_id, return_period_years=return_period
        )
        for envelope in result.get("envelopes", []):
            flood.setdefault(envelope["mechanism"], {})[return_period] = envelope
    exposed = api.indicator(
        FLOOD_POPULATION, scope_id=scope_id, return_period_years=100
    )

    riverine = flood.get("riverine", {}).get(100)
    coastal = flood.get("coastal", {}).get(100)
    headline_mechanism = riverine or coastal

    st.markdown(
        "<h1 class='hero'>"
        + hero_sentence(
            name,
            area_pct=headline_mechanism["value"] if headline_mechanism else None,
            mechanism=headline_mechanism["mechanism"] if headline_mechanism else None,
            return_period=100,
            people_exposed=_people_for(exposed, "riverine" if riverine else "coastal"),
        )
        + "</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='hero-sub'>Modelled extent, baseline conditions 1960–1999. "
        "Exposure is not risk.</div>",
        unsafe_allow_html=True,
    )

    narrative, margin = st.columns([2, 1], gap="large")
    with narrative:
        st.markdown("<h2 class='sec'>Flood exposure at 100 years</h2>", unsafe_allow_html=True)
        bars = []
        for mechanism, colour in (("riverine", RIVERINE), ("coastal", COASTAL)):
            envelope = flood.get(mechanism, {}).get(100)
            value = envelope["value"] if envelope else 0.0
            bars.append(bar_html(mechanism.capitalize(), value, maximum=100, colour=colour))
        st.markdown("".join(bars), unsafe_allow_html=True)
        if _identical_across_periods(flood):
            st.markdown(
                "<div class='ev' style='color:#5F6660; margin-top:.6rem'>"
                "Identical at 10, 50 and 100 years: the 5′ hazard grid resolves the "
                "same area at each return period. Read this as modelled extent, not "
                "as return-period sensitivity.</div>",
                unsafe_allow_html=True,
            )
        if coastal is not None and coastal["value"] == 0:
            st.markdown(
                "<div class='stamp'><b>Coastal zero.</b> The layer does not resolve "
                "inside this boundary at 1 km. Zero means not detected at this "
                "resolution, not no risk.</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<h2 class='sec'>Hot days</h2>", unsafe_allow_html=True)
        heat = api.indicator(HEAT, scope_id=scope_id)
        if heat.get("envelopes"):
            points = [
                (envelope["period"]["start"][:4], envelope["value"])
                for envelope in heat["envelopes"]
            ]
            points = [(int(year), value) for year, value in points]
            st.markdown(sparkline(points), unsafe_allow_html=True)
            st.markdown(
                f"<div class='ev' style='color:{MUTED}'>Days per calendar year with "
                f"daily maximum at or above 35 °C · {len(points)} complete years</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='refusal'><div class='what'>Not published at ward level."
                "</div><div class='missing'>The ERA5 grid is 0.25°, five cells across "
                "the metro, so a ward figure would describe which cell the ward falls "
                "in. The municipal series is published.</div></div>",
                unsafe_allow_html=True,
            )

    with margin:
        st.markdown("<h2 class='sec'>Evidence</h2>", unsafe_allow_html=True)
        st.markdown(_evidence(flood, exposed), unsafe_allow_html=True)

    _limitations(flood, exposed, heat)
    _title_block(api.health(), f"{name} · generated for this session")


def _people_for(population: dict[str, Any], mechanism: str) -> float | None:
    for envelope in population.get("envelopes", []):
        if envelope.get("mechanism") == mechanism and envelope.get("return_period_years") == 100:
            return envelope["value"]
    return None


def _identical_across_periods(flood: dict[str, Any]) -> bool:
    for series in flood.values():
        values = {round(envelope["value"], 3) for envelope in series.values()}
        if len(values) == 1 and next(iter(values)) > 0 and len(series) == 3:
            return True
    return False


def _evidence(flood: dict[str, Any], exposed: dict[str, Any]) -> str:
    envelope = next(
        (env for series in flood.values() for env in series.values()), None
    )
    if envelope is None:
        return "<dl class='ev'><dd class='absent'>No flood row is published here.</dd></dl>"
    quality = envelope["quality"]
    period = envelope["period"]
    scope = envelope["scope"]
    datasets = {d["id"]: d for d in envelope["datasets"]}
    rows = [
        ("Scope", f"{scope['name']} · {scope['level']}"),
        ("Period", f"{period['start']} to {period['end']}"),
        ("Basis", period["basis"].replace("_", " ")),
        ("Resolution", quality["native_resolution"]),
        ("Coverage", pct(quality["coverage_pct"], 0)),
        ("Method", f"{envelope['method_id']} v{envelope['method_version']}"),
    ]
    for dataset in datasets.values():
        rows.append((dataset["id"], f"{dataset['version']} · {dataset['licence']}"))
    for exposed_envelope in [
        env
        for env in exposed.get("envelopes", [])
        if env.get("mechanism") == "riverine"
    ][:1]:
        rows.append(
            (
                f"People in {exposed_envelope['mechanism']} "
                f"{exposed_envelope['return_period_years']}-year extent",
                people(exposed_envelope["value"]),
            )
        )
    terms = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in rows
    )
    return f"<dl class='ev'>{terms}</dl>"


def _limitations(*payloads: dict[str, Any]) -> None:
    seen: list[str] = []
    for payload in payloads:
        for envelope in payload.get("envelopes", []):
            for warning in envelope["quality"]["warnings"]:
                if warning not in seen:
                    seen.append(warning)
    if not seen:
        return
    st.markdown("<h2 class='sec'>Limitations</h2>", unsafe_allow_html=True)
    with st.expander(f"{len(seen)} recorded limitations", expanded=False):
        st.markdown(
            "".join(f"<div class='ev' style='margin:.35rem 0'>· {escape(text)}</div>"
                    for text in seen),
            unsafe_allow_html=True,
        )


# --- explorer --------------------------------------------------------------


def _explorer(api: ApiClient, scope_id: str) -> None:
    controls = st.columns([1, 1, 1], vertical_alignment="bottom")
    with controls[0]:
        mechanism = st.selectbox("Mechanism", ["riverine", "coastal"])
    with controls[1]:
        return_period = st.selectbox("Return period", [100, 50, 10])
    with controls[2]:
        focus = st.selectbox(
            "Focus ward",
            options=[""] + [f"ethekwini-{n:03d}" for n in range(1, 111)],
            format_func=lambda value: "whole municipality" if not value else f"Ward {value[-3:]}",
        )

    ranked = api.rank(
        FLOOD_AREA,
        mechanism=mechanism,
        return_period_years=return_period,
        limit=200,
    )
    envelopes = ranked.get("envelopes", [])
    values = {
        envelope["scope"]["id"]: envelope["value"]
        for envelope in envelopes
        if envelope["scope"]["level"] == "ward"
    }
    colour = mechanism_colour(mechanism)

    left, right = st.columns([3, 2], gap="large")
    with left:
        if values:
            st.pydeck_chart(
                build_map(values, selected=focus or scope_id, colour=colour),
                use_container_width=True,
                height=520,
            )
            st.caption(
                f"{len(values)} wards · {mechanism} · {return_period}-year · "
                "grey wards publish no value"
            )
        else:
            st.markdown("<div class='refusal'><div class='what'>No ward values for "
                        "that combination.</div></div>", unsafe_allow_html=True)
    with right:
        st.markdown(f"<h2 class='sec'>Ranked · {mechanism} {return_period}-year</h2>",
                    unsafe_allow_html=True)
        rows = []
        top = max(values.values()) if values else 1
        for envelope in envelopes[:15]:
            scope = envelope["scope"]
            width = 100 * envelope["value"] / top if top else 0
            rows.append(
                "<tr>"
                f"<td>{escape(scope['name'])}</td>"
                f"<td class='num'>{pct(envelope['value'])}</td>"
                "<td style='width:34%'>"
                f"<span class='track' style='display:block;height:6px;background:#E4E6E1'>"
                f"<span class='fill' style='display:block;height:6px;width:{width:.0f}%;"
                f"background:{colour}'></span></span></td>"
                "</tr>"
            )
        st.markdown(
            "<table class='grid'><tr><th>Ward</th><th class='num'>Exposed</th>"
            f"<th></th></tr>{''.join(rows)}</table>",
            unsafe_allow_html=True,
        )
        with st.expander("Provenance of the top row"):
            top_envelope = envelopes[0] if envelopes else None
            if top_envelope:
                st.json(top_envelope)


# --- ask -------------------------------------------------------------------


def _ask(api: ApiClient) -> None:
    st.markdown("<h2 class='sec'>Ask</h2>", unsafe_allow_html=True)
    question = st.text_area(
        "Question",
        value=st.session_state.get("question", ""),
        height=80,
        placeholder="What share of ward 75 is exposed to the 100-year riverine flood?",
        label_visibility="collapsed",
    )
    st.session_state.question = question
    cols = st.columns([1, 1, 1, 2])
    labels = ["Flood ranking", "People exposed", "Plan on sea level"]
    for index, (example, label) in enumerate(zip(EXAMPLES, labels, strict=True)):
        with cols[index]:
            if st.button(label, key=f"ex{index}", use_container_width=True):
                st.session_state.question = example
                st.rerun()
    with cols[3]:
        submitted = st.button("Ask", type="primary", use_container_width=True)

    if not submitted:
        st.markdown(
            "<div class='ev' style='color:#5F6660; margin-top:.6rem'>"
            "Answers restate published values and cite them. If the data cannot "
            "answer the question, the answer says what is missing.</div>",
            unsafe_allow_html=True,
        )
        return

    with st.spinner("Querying the mart and the document index"):
        result = api.ask(question)

    answer = result["answer"]
    if answer.get("abstained"):
        st.markdown(
            "<div class='refusal'><div class='what'>"
            + escape(answer["text"])
            + "</div><div class='missing'>"
            + escape("; ".join(answer.get("missing", [])))
            + "</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<p style='font-size:1.02rem; max-width:70ch'>{escape(answer['text'])}</p>",
            unsafe_allow_html=True,
        )
    if result.get("citations"):
        st.markdown("<h2 class='sec'>Citations</h2>", unsafe_allow_html=True)
        st.markdown(
            "".join(_citation(api, citation) for citation in result["citations"]),
            unsafe_allow_html=True,
        )
    st.caption(
        f"model {result.get('model') or 'guard'} · {result.get('seconds', 0):.1f} s · "
        f"{result.get('requests', 0)} request(s)"
        + (
            f" · ${result['cost_usd']:.6f}"
            if result.get("cost_usd") is not None
            else ""
        )
    )


def _citation(api: ApiClient, citation: dict[str, Any]) -> str:
    """A row key means nothing to a planner, so resolve it to what it names.

    The key stays visible in mono underneath: it is what a reader quotes back
    when they want the exact row, and it is what the appendix lists.
    """
    reference = citation["reference"]
    if citation.get("kind") == "measurement":
        try:
            row = api.get(f"/rows/{reference}")
            envelope = row["envelopes"][0]
            parts = [
                envelope["scope"]["name"],
                _indicator_label(envelope["indicator_id"]),
            ]
            hazard = " ".join(
                str(part)
                for part in (
                    envelope.get("mechanism"),
                    f"{envelope['return_period_years']}-year"
                    if envelope.get("return_period_years")
                    else None,
                )
                if part
            )
            if hazard:
                parts.append(hazard)
            parts.append(_value(envelope["value"], envelope["unit"]))
            label = " · ".join(parts)
        except (ApiError, IndexError, KeyError):
            label = "published row"
    else:
        label = f"document passage · {reference[:10]}"
    return (
        f"<div class='ev' style='margin:.3rem 0'>{escape(label)}"
        f"<span style='font-family:var(--data);font-size:.68rem;color:#5F6660'>"
        f"&nbsp;&nbsp;{escape(reference[:16])}</span></div>"
    )


INDICATOR_LABELS = {
    "flood_exposed_area_pct": "flood-exposed area",
    "flood_exposed_population": "people in flood extent",
    "hot_days_tmax_ge_35c": "hot days at or above 35 °C",
    "population_count_worldpop": "population",
}


def _indicator_label(indicator_id: str) -> str:
    return INDICATOR_LABELS.get(indicator_id, indicator_id.replace("_", " "))


def _value(value: float, unit: str) -> str:
    if unit == "percent":
        return f"{value:.2f}%"
    if unit in {"count", "persons"}:
        return f"{value:,.0f}"
    return f"{value:g} {unit}"


# --- report ----------------------------------------------------------------


def _report(api: ApiClient, scope_id: str) -> None:
    st.markdown("<h2 class='sec'>Report</h2>", unsafe_allow_html=True)
    st.markdown(
        "<p style='max-width:62ch'>One PDF for this scope: headline figures, the "
        "flood caveat on every page, and an evidence appendix naming dataset "
        "versions, licences, checksums and methods.</p>",
        unsafe_allow_html=True,
    )
    if st.button("Generate report", type="primary"):
        with st.spinner("Rendering"):
            job = api.request_report(scope_id)
        st.session_state.report_job = job
    job = st.session_state.get("report_job")
    if not job:
        return
    status = job.get("status", "queued")
    st.markdown(
        f"<div class='ev'>Job <span style='font-family:var(--data)'>{escape(job['job_id'][:12])}"
        f"</span> · {escape(status)}</div>",
        unsafe_allow_html=True,
    )
    if status == "done":
        st.link_button("Open PDF", api.pdf_url(job["job_id"]))
    elif status == "failed":
        st.markdown(
            f"<div class='stamp'><b>Rendering failed.</b> {escape(job.get('error', 'unknown'))}"
            "</div>",
            unsafe_allow_html=True,
        )
