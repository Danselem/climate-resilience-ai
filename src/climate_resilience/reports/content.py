"""Report content, assembled from mart rows only.

A report is a set of published rows rendered for a human. Nothing is calculated
here: every number comes from an envelope, so the appendix can name the dataset,
version, licence and method behind it. The flood caveat is part of the document
frame, not a paragraph a template could forget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape

from sqlalchemy import Engine

from ..envelope import EvidenceEnvelope
from ..tools import mart_tools
from ..tools.models import ScopeRef

FLOOD_CAVEAT = (
    "Flood analysis covers riverine and coastal flooding only. Pluvial "
    "(surface-water) flooding is not modelled."
)

HEAT_INDICATOR = "hot_days_tmax_ge_35c"
POPULATION_INDICATOR = "population_count_worldpop"
FLOOD_AREA = "flood_exposed_area_pct"
FLOOD_POPULATION = "flood_exposed_population"
RETURN_PERIODS = (10, 50, 100)


@dataclass
class ReportData:
    scope: ScopeRef
    generated_at: datetime
    headline: list[tuple[str, str, str]] = field(default_factory=list)
    flood_rows: list[tuple[str, int, str, str]] = field(default_factory=list)
    heat_rows: list[tuple[int, str]] = field(default_factory=list)
    rows: list[tuple[str, EvidenceEnvelope]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def collect(engine: Engine, scope_query: str) -> ReportData:
    """Gather everything the report shows, or raise if the scope is unknown."""
    resolved = mart_tools.resolve_scope(engine, query=scope_query)
    if not resolved.ok or not resolved.scopes:
        raise LookupError(f"no published scope matches {scope_query!r}")
    scope = resolved.scopes[0]
    data = ReportData(scope=scope, generated_at=datetime.now(UTC))

    population = mart_tools.get_indicator(
        engine, indicator_id=POPULATION_INDICATOR, scope_id=scope.id
    )
    heat = mart_tools.get_indicator(engine, indicator_id=HEAT_INDICATOR, scope_id=scope.id)
    data.rows.extend(zip(heat.row_keys, heat.envelopes, strict=True))
    data.rows.extend(zip(population.row_keys, population.envelopes, strict=True))

    if heat.envelopes:
        latest = max(heat.envelopes, key=lambda env: env.period.start)
        data.headline.append(
            ("Hot days (Tmax ≥ 35 °C)", f"{latest.value:g} days", f"{latest.period.start.year}")
        )
    else:
        # Silence would read as zero. Ward-level heat is not published because
        # the climate grid is coarser than a ward.
        data.headline.append(
            (
                "Hot days (Tmax ≥ 35 °C)",
                "not published at ward level",
                "5-cell climate grid; published for the municipality",
            )
        )
        data.limitations.append(
            "Ward-level heat is not published. The ERA5 grid is 0.25° (five cells "
            "across the metro), so a ward-level hot-day count would be an artefact "
            "of which cell a ward falls in. The municipal series is published."
        )
    if population.envelopes:
        value = population.envelopes[0].value
        data.headline.append(("Population (WorldPop)", f"{value:,.0f} people", "1 km grid"))

    for mechanism in ("riverine", "coastal"):
        for return_period in RETURN_PERIODS:
            area = mart_tools.get_indicator(
                engine,
                indicator_id=FLOOD_AREA,
                scope_id=scope.id,
                mechanism=mechanism,
                return_period_years=return_period,
            )
            people = mart_tools.get_indicator(
                engine,
                indicator_id=FLOOD_POPULATION,
                scope_id=scope.id,
                mechanism=mechanism,
                return_period_years=return_period,
            )
            data.rows.extend(zip(area.row_keys, area.envelopes, strict=True))
            data.rows.extend(zip(people.row_keys, people.envelopes, strict=True))
            if not area.envelopes:
                continue
            area_env = area.envelopes[0]
            people_env = people.envelopes[0] if people.envelopes else None
            data.flood_rows.append(
                (
                    mechanism,
                    return_period,
                    f"{area_env.value:.2f}%",
                    f"{people_env.value:,.0f}" if people_env else "not published",
                )
            )
            if (
                mechanism == "coastal"
                and area_env.value == 0
                and not any(
                    "Coastal exposure is published as zero" in text
                    for text in data.limitations
                )
            ):
                data.limitations.append(
                    "Coastal exposure is published as zero with a warning: the "
                    "layer does not resolve within the ward boundary. A zero here "
                    "means 'not detected at this resolution', not 'no risk'."
                )

    # The ten most recent complete years, newest first.
    for _row_key, envelope in sorted(
        zip(heat.row_keys, heat.envelopes, strict=False),
        key=lambda pair: pair[1].period.start,
        reverse=True,
    )[:10]:
        data.heat_rows.append((envelope.period.start.year, f"{envelope.value:g}"))

    for envelope in [env for _, env in data.rows]:
        for warning in envelope.quality.warnings:
            if warning not in data.limitations:
                data.limitations.append(warning)

    # Three identical rows at 10, 50 and 100 years look like a bug unless the
    # document says why they are identical.
    for mechanism in ("riverine", "coastal"):
        areas = {
            area for name, _, area, _ in data.flood_rows if name == mechanism
        }
        if len(areas) == 1 and next(iter(areas), "0.00%") != "0.00%":
            data.limitations.append(
                f"{mechanism.title()} exposure is identical at 10, 50 and 100 years "
                "for this scope: the 5-arcminute hazard grid resolves the same area "
                "at each return period. Read it as modelled extent, not as "
                "sensitivity to return period."
            )

    data.rows = [(key, env) for key, env in data.rows]
    return data


def render_html(data: ReportData, *, run_id: str) -> str:
    """A self-contained document: no external assets, so it renders offline."""
    scope = data.scope
    scope_label = f"Ward {scope.ward_number}" if scope.ward_number else scope.name

    headline = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td>"
        f"<td class='muted'>{escape(note)}</td></tr>"
        for label, value, note in data.headline
    )
    flood = "".join(
        f"<tr><td>{escape(mechanism.title())}</td><td>{period}-year</td>"
        f"<td class='num'>{escape(area)}</td><td class='num'>{escape(people)}</td></tr>"
        for mechanism, period, area, people in data.flood_rows
    )
    heat = "".join(
        f"<tr><td>{year}</td><td class='num'>{value}</td></tr>" for year, value in data.heat_rows
    )
    heat_table = (
        "<table><tr><th>Year</th><th class='num'>Days ≥ 35 °C</th></tr>"
        f"{heat}</table>"
        if data.heat_rows
        else "<p class='muted'>Not published at this scope. See Limitations.</p>"
    )
    limitations = "".join(f"<li>{escape(text)}</li>" for text in data.limitations)
    appendix = _appendix(data)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(scope_label)} — climate evidence</title>
<style>
  @page {{
    size: A4; margin: 22mm 16mm 18mm 16mm;
    @top-center {{
      content: "{escape(FLOOD_CAVEAT)}";
      font: 7.5pt "Helvetica", sans-serif; color: #7a2e00;
      border-bottom: 0.5pt solid #d9b8a6; padding-bottom: 2mm; width: 100%;
    }}
    @bottom-right {{ content: "page " counter(page) " of " counter(pages);
                     font: 7pt "Helvetica", sans-serif; color: #777; }}
  }}
  body {{ font: 10pt "Helvetica", sans-serif; color: #1d1d1f; }}
  h1 {{ font-size: 20pt; margin: 0 0 2mm 0; }}
  h2 {{ font-size: 12pt; margin: 8mm 0 2mm; border-bottom: 0.5pt solid #ccc;
        padding-bottom: 1mm; }}
  .sub {{ color: #666; margin-bottom: 6mm; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 4mm; }}
  th, td {{ text-align: left; padding: 1.6mm 2mm; border-bottom: 0.4pt solid #e4e4e4; }}
  th {{ width: 45%; font-weight: 600; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ color: #777; font-size: 8.5pt; }}
  .note {{ background: #fdf3ee; border-left: 2pt solid #c05621; padding: 3mm 4mm;
           margin: 4mm 0; font-size: 9pt; }}
  .appendix {{ font-size: 8pt; }}
  .appendix td, .appendix th {{ padding: 1mm 1.5mm; }}
  code {{ font-size: 7.5pt; }}
</style></head>
<body>
  <h1>{escape(scope_label)}</h1>
  <div class="sub">{escape(scope.name)} · {scope.level} · {scope.area_km2:,.1f} km² ·
    generated {data.generated_at.strftime("%d %B %Y")} ·
    run <code>{escape(run_id[:12])}</code></div>

  <h2>Headline</h2>
  <table>{headline}</table>

  <h2>Flood exposure</h2>
  <table>
    <tr><th>Mechanism</th><th>Return period</th><th class="num">Area exposed</th>
        <th class="num">People exposed</th></tr>
    {flood}
  </table>
  <div class="note">{escape(FLOOD_CAVEAT)} Exposure is not risk: it counts what a
    hazard layer reaches, not what would be lost.</div>

  <h2>Hot days, last ten complete years</h2>
  {heat_table}

  <h2>Limitations</h2>
  <ul>{limitations}</ul>

  <h2>Evidence appendix</h2>
  {appendix}
</body></html>"""


def _appendix(data: ReportData) -> str:
    """Dataset, version, licence, checksum and method behind every figure."""
    datasets: dict[str, list[str]] = {}
    methods: dict[str, list[str]] = {}
    rows: list[str] = []
    for _, envelope in data.rows:
        for dataset in envelope.datasets:
            entry = datasets.setdefault(
                dataset.id,
                [
                    dataset.id,
                    dataset.version,
                    dataset.licence,
                    dataset.checksum[:16],
                    dataset.source_url,
                ],
            )
            entry[1] = dataset.version
        methods.setdefault(
            envelope.method_id,
            [envelope.method_id, envelope.method_version, envelope.hazard_type],
        )
        rows.append(
            "<tr>"
            f"<td><code>{escape(envelope.indicator_id)}</code></td>"
            f"<td>{escape(envelope.scope.name)}</td>"
            f"<td>{envelope.period.start.isoformat()} → {envelope.period.end.isoformat()}</td>"
            f"<td>{escape(envelope.mechanism or '—')}</td>"
            f"<td>{envelope.return_period_years or '—'}</td>"
            f"<td class='num'>{envelope.value:g}</td>"
            f"<td>{escape(envelope.unit)}</td>"
            f"<td><code>{escape(envelope.method_id)}</code> v{escape(envelope.method_version)}</td>"
            f"<td class='num'>{envelope.quality.coverage_pct:g}%</td>"
            "</tr>"
        )

    dataset_rows = "".join(
        f"<tr><td><code>{escape(d)}</code></td><td>{escape(v)}</td>"
        f"<td>{escape(licence)}</td><td><code>{escape(checksum)}</code></td>"
        f"<td>{escape(url)}</td></tr>"
        for d, v, licence, checksum, url in datasets.values()
    )
    method_rows = "".join(
        f"<tr><td><code>{escape(mid)}</code></td><td>{escape(version)}</td>"
        f"<td>{escape(hazard)}</td></tr>"
        for mid, version, hazard in methods.values()
    )

    return f"""
  <div class="appendix">
    <table>
      <tr><th>Indicator</th><th>Scope</th><th>Period</th><th>Mechanism</th>
          <th>Return period</th><th class="num">Value</th><th>Unit</th>
          <th>Method</th><th class="num">Coverage</th></tr>
      {''.join(rows)}
    </table>
    <table>
      <tr><th>Dataset</th><th>Version</th><th>Licence</th><th>Checksum</th><th>Source</th></tr>
      {dataset_rows}
    </table>
    <table>
      <tr><th>Method</th><th>Version</th><th>Hazard</th></tr>
      {method_rows}
    </table>
  </div>"""
