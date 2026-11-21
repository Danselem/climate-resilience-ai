"""Deterministic pre-flight refusal.

Two kinds of question must not reach the model: a request for pluvial flood
exposure (I9), and a request for a measurement from a dataset that does not
exist. Both are decided from the text, cost nothing, and cannot hallucinate.

The distinction that keeps this honest is *measurement intent*. "What does the
Climate Action Plan say about pluvial flooding?" is a document question and is
allowed through; "how many people are exposed to pluvial flooding in ward 75"
is refused. A keyword match alone would refuse both.
"""

from __future__ import annotations

from dataclasses import dataclass

PLUVIAL_TERMS = (
    "pluvial",
    "surface water flood",
    "surface-water flood",
    "surface water flooding",
    "flash flood",
    "stormwater flood",
    "drainage flood",
)

PLUVIAL_REASON = (
    "Pluvial (surface-water) flooding is not modelled. The platform covers "
    "riverine and coastal flooding only; the April 2022 KwaZulu-Natal damage "
    "was largely pluvial, and no open metro-scale dataset exists for it (I9)."
)

# Terms that mean "give me a number" rather than "tell me what the text says".
MEASUREMENT_TERMS = (
    "how many",
    "how much",
    "how has",
    "how have",
    "has changed",
    "changed across",
    "changed since",
    "what percentage",
    "what share",
    "what fraction",
    "which wards",
    "what is the",
    "what are the",
    "how exposed",
    "exposed to",
    "risk score",
    "estimate",
    "modelled",
    "modeled",
    "projected",
    "per km",
    "per square",
    "in 2050",
    "in 2080",
    "by 2050",
    "by 2080",
)

DOCUMENT_TERMS = (
    "plan say",
    "plan state",
    "plan mention",
    "strategy say",
    "strategy state",
    "report say",
    "report state",
    "document",
    "policy",
    "according to",
    "what does the",
    "what do the",
)

# The pilot covers one municipality. A measurement question about another city
# has no answer here, and inventing one is the worst possible outcome.
OTHER_MUNICIPALITIES = (
    "cape town",
    "johannesburg",
    "pretoria",
    "tshwane",
    "ekurhuleni",
    "nelson mandela bay",
    "buffalo city",
    "msunduzi",
    "pietermaritzburg",
    "richards bay",
)

UNSUPPORTED = (
    (
        (
            "vulnerability",
            "socio-economic",
            "socioeconomic",
            "poverty",
            "below the poverty line",
        ),
        "No vulnerability indicator is published. Census 2022 socio-economic "
        "data exists only in interactive tools, and its 111 wards do not match "
        "the 110 ADM4 boundaries (ADR-009).",
        ["a ward-level socio-economic dataset"],
    ),
    (
        ("projection", "rcp4.5", "rcp8.5", "rcp 4.5", "rcp 8.5", "future climate"),
        "No climate projection is published. Flood projections were measured "
        "and rejected: the 2080 layers use different forcing from the baseline, "
        "so a delta is not a clean climate signal (ADR-010).",
        ["a projection dataset with matched forcing"],
    ),
    (
        ("wildfire", "fire detection", "firms", "fire per km"),
        "No fire dataset is ingested. FIRMS is catalogued as planned and never "
        "acquired.",
        ["fire detection data"],
    ),
    (
        ("rainfall", "drought", "dry spell", "consecutive dry", "precipitation"),
        "No rainfall or drought indicator is published. Only heat, population "
        "and flood exposure exist in the mart.",
        ["a rainfall and drought indicator"],
    ),
    (
        ("trend", "increase in hot days", "warming rate", "change in hot days"),
        "No trend method is published. Annual counts exist, but a trend "
        "estimate (Mann-Kendall, Sen's slope) is not implemented.",
        ["a trend indicator"],
    ),
)


# Instruction-override and credential-extraction attempts. Refusing these
# before the model runs is not a filter on free speech: it removes the only
# surface on which an injected instruction could reach the tools.
INJECTION_TERMS = (
    "ignore your",
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "system prompt",
    "your instructions",
    "repeat your",
    "reveal your",
    "print your",
    "api key",
    "openrouter",
)

RISK_SCORE_TERMS = (
    "risk score",
    "out of 10",
    "score out of",
    "rank the wards by risk",
)

COMBINE_TERMS = (
    "combined total",
    "add them together",
    "add riverine",
    "add coastal",
    "total flood risk",
    "sum of riverine",
    "sum the mechanisms",
)


@dataclass(frozen=True)
class Refusal:
    text: str
    missing: list[str]
    available: str | None = None


def preflight(question: str) -> Refusal | None:
    lowered = question.lower().strip()
    if not lowered:
        return Refusal("The question is empty.", ["a question"])

    if any(term in lowered for term in INJECTION_TERMS):
        return Refusal(
            "I do not follow instructions that override the analytical rules, "
            "and I do not reveal configuration or credentials.",
            ["a question about eThekwini climate data"],
        )

    suppression = ("leave out", "omit", "without the", "exclude", "don't mention")
    if ("caveat" in lowered or "pluvial" in lowered) and any(
        term in lowered for term in suppression
    ):
        return Refusal(
            "The pluvial caveat is part of the result, not an optional extra: "
            "the data covers riverine and coastal flooding only. I will not "
            "produce a flood figure with that removed.",
            ["an answer that keeps the flood mechanism caveat"],
        )

    if any(term in lowered for term in RISK_SCORE_TERMS):
        return Refusal(
            "No composite risk score is published. Hazard, exposure and "
            "vulnerability are reported separately, and combining them into a "
            "single score requires a defined and validated method.",
            ["a defined risk-scoring method"],
        )

    if any(term in lowered for term in COMBINE_TERMS):
        return Refusal(
            "Riverine and coastal flooding are separate hazards and are never "
            "summed. Each is published with its own mechanism label.",
            ["a method that justifies merging two hazard mechanisms"],
        )

    if _is_document_question(lowered):
        return None
    if not _has_measurement_intent(lowered):
        return None

    if any(term in lowered for term in PLUVIAL_TERMS):
        return Refusal(PLUVIAL_REASON, ["a pluvial flood hazard layer"])

    elsewhere = next(
        (place for place in OTHER_MUNICIPALITIES if place in lowered), None
    )
    if elsewhere and "ethekwini" not in lowered and "durban" not in lowered:
        return Refusal(
            f"Only eThekwini is published in this pilot; {elsewhere.title()} is "
            "outside its boundary. No figure is available for it.",
            [f"data for {elsewhere.title()}"],
        )

    for terms, reason, missing in UNSUPPORTED:
        if any(term in lowered for term in terms):
            return Refusal(reason, missing)

    return None


def _is_document_question(lowered: str) -> bool:
    return any(term in lowered for term in DOCUMENT_TERMS)


def _has_measurement_intent(lowered: str) -> bool:
    return any(term in lowered for term in MEASUREMENT_TERMS)
