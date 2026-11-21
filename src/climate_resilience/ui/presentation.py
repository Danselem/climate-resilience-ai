"""Pure presentation helpers.

Anything that turns numbers into words lives here so it can be tested without a
browser. The rules are the project's rules: a unit is never dropped, an absence
is never rendered as a zero, and riverine and coastal are never combined.
"""

from __future__ import annotations

from decimal import Decimal

from .theme import COASTAL, RIVERINE, SIGNAL


def pct(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}%"


def people(value: float) -> str:
    return f"{value:,.0f}"


def compact(value: float) -> str:
    """Short form for a bar label, never used where exactness matters."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return f"{value:,.0f}"


def mechanism_colour(mechanism: str | None) -> str:
    return {"riverine": RIVERINE, "coastal": COASTAL}.get(mechanism or "", SIGNAL)


def hero_sentence(
    scope_name: str,
    *,
    area_pct: float | None,
    mechanism: str | None,
    return_period: int | None,
    people_exposed: float | None,
) -> str:
    """The one sentence the sheet leads with.

    If a flood value exists it is stated with its mechanism and return period.
    If it does not, the sheet says what is missing rather than putting a
    number-shaped hole at the top of the page.
    """
    if area_pct is None:
        return f"No flood exposure value is published for {scope_name}."

    exposure = (
        f"<strong>{pct(area_pct)}</strong> of {scope_name}'s area lies inside the "
        f"modelled {return_period}-year {mechanism} flood extent"
    )
    if people_exposed:
        exposure += f", where <strong>{people(people_exposed)}</strong> people live"
    return exposure + "."


def bar_html(label: str, value: float, *, maximum: float, colour: str) -> str:
    width = 0.0 if maximum <= 0 else max(0.0, min(100.0, 100.0 * value / maximum))
    return (
        f'<div class="bar"><span>{label}</span>'
        f'<span class="track"><span class="fill" style="width:{width:.1f}%;'
        f'background:{colour}"></span></span>'
        f'<span class="val">{pct(value)}</span></div>'
    )


def sparkline(points: list[tuple[int, float]]) -> str:
    """A small line drawing of a series, in the sheet's ink.

    No chart library: the shape is the information, and a library would add
    axes, legends and hover states that this page does not need.
    """
    if len(points) < 2:
        return "<p class='ev-absent'>Not enough years to draw a series.</p>"
    width, height, pad = 640, 104, 8
    values = [value for _, value in points]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = (width - 2 * pad) / (len(points) - 1)
    coords = [
        (
            pad + index * step,
            height - 26 - (value - low) / span * (height - 40),
        )
        for index, (_, value) in enumerate(points)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    first_year, last_year = points[0][0], points[-1][0]
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        'role="img" aria-label="Annual hot days">'
        f'<polyline points="{path}" fill="none" stroke="{RIVERINE}" stroke-width="2"/>'
        f'<text x="{pad}" y="{height - 1}" font-size="10" fill="#5F6660">{first_year}</text>'
        f'<text x="{width - pad}" y="{height - 1}" font-size="10" fill="#5F6660" '
        f'text-anchor="end">{last_year}</text>'
        "</svg>"
    )


def quantile_bins(values: list[float], count: int = 5) -> list[float]:
    """Edges for a choropleth, by quantile so a skewed indicator still reads."""
    if not values:
        return []
    ordered = sorted(values)
    edges = []
    for index in range(1, count):
        position = Decimal(index) * Decimal(len(ordered) - 1) / Decimal(count)
        edges.append(ordered[int(position)])
    return edges


def shade(value: float, edges: list[float], colour: str) -> str:
    """Blend a mechanism colour toward paper as the value falls."""
    if not edges:
        return "#E4E6E1"
    step = sum(1 for edge in edges if value > edge)
    alpha = 0.18 + 0.82 * (step / max(len(edges), 1))
    return _blend(colour, "#F6F7F4", 1 - alpha)


def _blend(foreground: str, background: str, amount: float) -> str:
    fg = [int(foreground[index : index + 2], 16) for index in (1, 3, 5)]
    bg = [int(background[index : index + 2], 16) for index in (1, 3, 5)]
    mixed = [round(b + (f - b) * amount) for f, b in zip(fg, bg, strict=True)]
    return "#{:02X}{:02X}{:02X}".format(*mixed)
