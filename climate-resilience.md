# Climate Resilience Intelligence Platform

**Version 3 — design specification**
**Status:** draft for review · supersedes `docs/archive/spec-v2.md` and `docs/archive/brief-v1.md`
**Pilot:** eThekwini Municipality, South Africa
**Stack:** Python 3.12 · FastAPI · PostGIS · Streamlit · OpenRouter · AWS

---

## 0. Change log

### v3 (this version)

| Change | Reason |
|---|---|
| **Flood reinstated** as a first-class hazard (riverine + coastal) | It is a required capability, not an optional extra |
| Flood hazard layer specified: WRI Aqueduct Floods v2, cross-checked with GloFAS | v1 and v2 named no flood dataset, which is why flood looked infeasible |
| Pluvial / surface-water flood declared an explicit non-goal | No open metro-scale pluvial dataset exists; 2022 KZN damage was substantially pluvial, so overstating coverage would be the project's biggest credibility risk |
| **WorldPop 100 m gridded population added** as the exposure surface | Ward-total × area-share is a crude estimate; gridded population makes every exposure answer defensible |
| Envelope extended for probabilistic hazards | A 100-year flood depth cannot share a schema with an annual mean temperature |
| **Ratio indicator class** added, with explicit denominators | Flood exposure is a fraction of a denominator; the denominator choice changes the answer |
| Latency tightened: p95 ≤ 6 s; mart ≤ 1 s | Cost and latency are explicit scoring criteria |
| Cost tightened: ≤ $0.004/question, hard cap $0.02 | Same reason; mechanisms specified in §11.3 and §14.5 |
| **PDF reports required**, asynchronous via SQS | Decides the report path and gives SQS a genuine job |
| Full v1 AWS component list retained | Required for the cloud deliverable; §8.3 assigns each component a real role |
| April 2022 validation rescoped to riverine extent | Validating a riverine layer against pluvial damage would produce a false failure |
| Independent reference answers mandated | Reference values computed by the code under test prove nothing |
| Delivery reordered as vertical slices; ~8 weeks | Highest-risk question (does the data support the indicator?) is answered in week 1 |

### v2

Converted the brief into a design specification: numeric non-functional targets, a capacity estimate, the evidence envelope as a system interface, a precomputed indicator mart, and phase exit criteria. Retained the problem statement, data sources and anti-hallucination stance from v1.

---

## 1. Purpose and scope

Build a working proof of concept showing how public climate and socioeconomic data can become **reproducible, evidence-backed planning insight** for a South African municipality.

This is not a climate chatbot. It is an analytical system whose numbers are computed deterministically, recorded with provenance, and explained by a language model that may only restate what the analytics returned.

**In scope:** one municipality (eThekwini); three hazards (heat, flood — riverine and coastal only, fire); one end-to-end vertical slice first, then breadth; a natural-language interface with citations; PDF reports; a measured evaluation harness; a cloud deployment of the same image.

**Out of scope:** see §4.3.

---

## 2. Problem statement

Municipal adaptation teams can access climate projections, hazard maps, census data and environmental datasets, but they live on different platforms, in different formats, coordinate systems and time bases. Combining them for a local assessment requires GIS and climate-data expertise most municipalities lack, and the resulting analyses are rarely reproducible — a figure in a planning document often cannot be traced to a dataset version, a method, or a calculation.

The gap is not data availability. It is **integration, interpretation and evidence**.

| Challenge | What the system addresses |
|---|---|
| Fragmented data | One analytical environment with a canonical spatial and temporal model |
| Difficult interpretation | Plain-language explanation of computed indicators |
| Limited accessibility | Questions answered without SQL or GIS scripting |
| Weak evidence trails | Every number carries a complete provenance record |
| Planning implications | Exposure and vulnerability identified per ward, not just climate statistics |

---

## 3. Users and the questions the system must answer

**Primary users:** municipal adaptation planners, GIS analysts, disaster-management staff. 5–50 users in the pilot; no assumption of GIS skill.

The pilot must answer questions of this shape, and must say *"I don't have the data for that"* otherwise:

1. Which wards have experienced the greatest increase in hot days (Tmax ≥ 35 °C)?
2. How has annual rainfall changed across the metro since 1980, and how many consecutive dry days occur now compared with the 1980s?
3. Which wards are projected to see longer dry spells by 2050 under RCP8.5?
4. **Which wards have the largest share of area exposed to a 1-in-100-year riverine or coastal flood?**
5. **How many people live in flood-exposed areas under a 1-in-100-year event, and which wards have the highest count?**
6. Which wards combine high heat exposure with high socioeconomic vulnerability?
7. Which wards recorded the most fire detections per km² per year?

### Flood scope caveat (binding on the UI and every report)

The flood analysis covers **riverine and coastal** flooding only. It does **not** model pluvial (surface-water) flooding — the intense-rainfall-overwhelmed-drainage mechanism responsible for much of the April 2022 KwaZulu-Natal damage. This caveat appears on every flood result, in the PDF report header, and in `docs/limitations.md`. It is never described as a general "flood risk" assessment.

---

## 4. Requirements

### 4.1 Functional

| ID | Requirement |
|---|---|
| F1 | Ingest the pilot datasets reproducibly; store raw inputs immutably with checksums |
| F2 | Publish a canonical spatial layer: municipality and ward boundaries, versioned, valid, with a documented CRS policy |
| F3 | Compute registered climate indicators from ERA5 per ward over a defined historical period |
| F4 | Compute riverine and coastal flood exposure per ward for 10-, 50- and 100-year return periods, with depth thresholds |
| F5 | Compute dasymetric population exposure using WorldPop, per ward |
| F6 | Compute ward vulnerability indicators from Census 2022, kept as a separate axis from hazard |
| F7 | Serve all published metrics from a precomputed indicator mart via a typed API |
| F8 | Answer natural-language questions by selecting bounded tools and restating their outputs |
| F9 | Cite dataset, period, scope, method and uncertainty for every numeric claim |
| F10 | Abstain explicitly when required data, period or scope is unavailable |
| F11 | Generate a PDF report for a ward or the municipality, asynchronously, containing maps, metrics and an evidence appendix |
| F12 | Reproduce any published number or report from a recorded run manifest |

### 4.2 Non-functional

Acceptance targets, measured in §12. Not aspirations.

| ID | Requirement | Target |
|---|---|---|
| N1 | End-to-end answer latency, single-metric question | **p95 ≤ 6 s** |
| N2 | Mart query latency, excluding LLM | **p95 ≤ 1 s** |
| N3 | PDF report, asynchronous | **≤ 60 s**, p95 |
| N4 | Numeric claims carrying an evidence reference | 100% |
| N5 | Tolerance vs independent reference: counts and ratios | exact / ≤ 0.5 percentage points |
| N6 | Tolerance vs independent reference: continuous indicators | ≤ 0.5 °C, ≤ 5% relative |
| N7 | Correct abstention on unanswerable questions | 100%, zero confident wrong answers |
| N8 | Tool-selection accuracy on the benchmark | ≥ 90% |
| N9 | Reproducibility: same inputs + same commit | byte-identical mart output |
| N10 | Availability during pilot business hours | 99.5% (single-AZ accepted, §14.3) |
| N11 | Backup RPO / RTO | 24 h / 4 h |
| N12 | LLM cost per question | **≤ $0.004 average; hard cap $0.02** |
| N13 | Pilot infrastructure cost | ≤ $150 / month |
| N14 | Environment parity | identical container image local and AWS |
| N15 | Code quality | Ruff clean; full type hints; ≥ 80% coverage on `indicators`, `canonical`, `mart` |
| N16 | Observability | every request logged with request id, tools, latency, tokens, cost, cache hit |

### 4.3 Non-goals

- **Pluvial / surface-water flood modelling.** No open metro-scale dataset; the limitation is stated, not hidden. Revisit only if eThekwini floodline studies become available and are licensed for derived use.
- **Flood depth at address level.** Hazard layers are ~1 km; results are ward-scale statistics, never property-level predictions.
- **Multi-municipality.** eThekwini only until the pipeline is validated.
- **Real-time or forecast data.** Historical reanalysis and published projections only.
- **"Risk score".** See §10.6.
- **User accounts and personal data.** Aggregate public data only; API keys are not user profiles.
- **Model-comparison UI.** Model selection is configuration.
- **Sentinel-1 SAR processing, hydrodynamic modelling, drainage-network analysis.**
- **Orchestration frameworks, vector databases, workflow schedulers, Kubernetes.**

---

## 5. Scale and capacity estimate

Order-of-magnitude reasoning. Figures are assumptions to confirm in Phase 1; conclusions hold if they are wrong by 10×.

| Quantity | Estimate | Basis |
|---|---|---|
| Concurrent users | 5–50 | One municipality |
| Question rate | ≤ 1,000/day ≈ 0.01 QPS avg, ~0.1 peak | 50 users × 20 questions |
| ERA5 metro extract | 0.25° grid ≈ 3×3 to 4×4 cells; 40 yr hourly ≈ 3–6 M values/variable ≈ 15–25 MB float32 | Subset at download |
| Aqueduct flood grid | ~1 km → ~2,500–3,500 cells over the metro; 3 return periods × 2 mechanisms × 2 scenarios ≈ 25–40 MB | Subset at download |
| WorldPop | 100 m → ~300k–500k cells; 2–3 annual vintages ≈ 10–30 MB | Subset at download |
| Census 2022 ward table | ~110 rows × ~50 columns | Confirm ward count and vintage (§15) |
| FIRMS detections | Thousands of rows over 20 years | CSV |
| GreenBook package | Tens to low hundreds of MB | To verify |
| PDF reports | ~2–5 MB each; ≤ 1,000 stored ≈ 5 GB | 90-day retention |
| **Total pilot footprint** | **< 10 GB** | |

**Conclusions:**

1. **No throughput or storage problem.** One PostgreSQL instance, one API service, one worker service, object storage. No sharding, no replicas, no distributed compute.
2. **Bottlenecks are LLM latency, raster/vector overlay compute, and PDF rendering.** The first is designed around (§11), the second is precomputed (§8.5), the third is asynchronous (§8.6).
3. **Correctness, lineage and validation are the engineering work** — not scale.

Latency budget (N1):

| Stage | Budget |
|---|---|
| Intent parsing and tool selection | 400–800 ms |
| Mart query | 50–200 ms |
| Answer synthesis | 800–2,500 ms |
| Render | < 200 ms |
| **p95 total** | **4–5 s, SLO 6 s** |

---

## 6. Domain invariants

Enforced in code, tested. These are the analytical contract.

| ID | Invariant |
|---|---|
| I1 | Hazard, exposure and vulnerability are stored and reported separately. No column named `risk`. |
| I2 | Every record declares its basis: `observation`, `reanalysis`, `projection`, `modelled_estimate`, or `derived`. |
| I3 | Every projection record carries scenario, model, baseline period and projection period. Unlabelled mixing of observations and projections is a validation error. |
| I4 | Every flood record carries mechanism (`riverine`/`coastal`), return period and depth threshold. A flood value without them is invalid. |
| I5 | Units, CRS, spatial resolution and time basis are validated before any join. Mismatch fails loudly. |
| I6 | Raw source files are immutable; derived outputs live in separate versioned locations. |
| I7 | Every published metric is reproducible from a recorded inputs hash and code commit. |
| I8 | Missing data is reported, never interpolated silently; below the method's coverage threshold the metric is withheld. |
| I9 | Pluvial flood results cannot be produced, because no such dataset is registered. Attempting to is a tool-level error. |

---

## 7. Data

### 7.1 Sources and roles

| Source | Data | Role | Basis | Access / licence |
|---|---|---|---|---|
| [MDB](https://www.demarcation.org.za) | Municipal and ward boundaries | Geographic reference | — | Release vintage must be recorded |
| [Copernicus CDS](https://cds.climate.copernicus.eu/en/how-to-api) — ERA5 | Hourly temperature, precipitation | Historical baseline | reanalysis | CDS API; account + licence acceptance |
| [Stats SA](https://www.statssa.gov.za/) | Census 2022 population, households, demographics | Vulnerability axis | observation (aggregated) | Verify ward-level availability |
| [WorldPop](https://www.worldpop.org/) | 100 m gridded population | Exposure surface | modelled_estimate | CC BY 4.0 |
| [WRI Aqueduct Floods v2](https://www.wri.org/aqueduct) | Riverine and coastal flood depth, 2–500 yr return periods, future scenarios | Flood hazard | modelled_estimate | Open, CC BY 4.0 |
| Copernicus GloFAS (CDS) | River discharge | Flood cross-check (riverine) | reanalysis | CDS API |
| [NCCIS](https://nccis.environment.gov.za/climate-services/download-data) | CSIR/SAWS projections, 2021–2050, RCP4.5/8.5 vs 1971–2000 | Future projections | projection | Portal download — verify |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/download/) | MODIS/VIIRS active fire detections | Wildfire observation | observation | Registration for archive |
| [GreenBook](https://www.greenbook.co.za/greenbook-support.html) | Municipal risk profiles, maps, data packages | Context and cross-check | mixed | Manual download — verify |
| Copernicus EMS | Mapped flood extent, specific events | Validation of the flood layer | observation | Open; confirm activation ID |

### 7.2 Pilot bundle

| Phase | Datasets |
|---|---|
| Walking skeleton | MDB ward boundaries + ERA5 temperature |
| Exposure | Census 2022 + WorldPop |
| Flood | Aqueduct Floods v2 (+ GloFAS cross-check) |
| Projections | NCCIS 2021–2050 |
| Fire | FIRMS |
| Validation | Copernicus EMS event extent |
| Context | GreenBook — read for framing and cross-checking, not a computation input until its file structure is understood |

GreenBook is valuable but its packages are documents and dashboards, not a tidy API. It stays a context source; no analytic depends on parsing it.

### 7.3 Data qualification gates

No dataset enters the pipeline until every gate passes. A gate failure is a documented finding, not a licence to improvise.

| Gate | Test |
|---|---|
| Access | Retrievable by script, or by a documented manual step |
| Licence | Redistribution and derived use permitted; recorded in the catalogue |
| Coverage | Actually covers eThekwini for the required period |
| Format | Parseable with a maintained library |
| CRS and units | Declared and internally consistent |
| Identifiers | Geographic identifiers match across sources at the required level |
| Vintage | Boundary vintage aligns with census vintage; WorldPop release aligns with Census 2022 |
| Resolution | Native resolution recorded and carried into every result's `quality` block |
| Size | Subset small enough to avoid distributed compute |

### 7.4 Catalogue requirements

One machine-readable entry per dataset, validated by a test. Required fields: source, URL, retrieval date, licence, version/release, checksum, units, CRS, native resolution, spatial coverage, temporal coverage, time basis, known gaps, processing steps.

---

## 8. Architecture

### 8.1 Layers

```text
sources → ingestion (fetch, verify, catalogue)
        → canonical layer (spatial + temporal normalisation, PostGIS)
        → indicator mart (precomputed metrics + evidence envelopes)
        → tools / API (typed functions, bounded inputs)
        → assistant (OpenRouter: select tool, restate, cite)
        → interfaces (Streamlit; PDF report service)
```

Strict rule: **the interface layer never computes a metric.** It reads the mart. The assistant never touches a raster, CSV or table — only tool outputs.

### 8.2 Runtime components

Identical code and image; environment-driven configuration.

| Concern | Local | AWS | Job in the MVP |
|---|---|---|---|
| Compute (API) | Compose: `api`, `ui` | ECS Fargate service | Serves tools, answers, report requests |
| Compute (worker) | Compose: `worker` | ECS Fargate service, queue-depth autoscaled | PDF rendering, mart rebuilds — **same image, different entrypoint** |
| Database | PostGIS container | RDS PostgreSQL + PostGIS | Canonical layer + mart + job state |
| Object storage | `data/` | S3 | Raw, processed, reports, manifests |
| Queue | LocalQueue shim (DB table) | **SQS** + DLQ | Report jobs and rebuild jobs |
| Secrets | `.env` (git-ignored) | Secrets Manager | OpenRouter key, DB credentials |
| Logs and metrics | stdout | CloudWatch | Structured logs, metrics, alarms |
| Scheduling | `make` targets | EventBridge → ECS task | Nightly mart freshness check, backups |
| Infrastructure | `docker-compose.yml` | Terraform | Parity |

The local queue shim exists so the local and cloud paths run the *same* code: `enqueue()` and `consume()` are one interface with two implementations.

### 8.3 Right-sizing: what each component does, and when to grow it

Every v1 component is retained. Each has a stated job; growth triggers are documented so the architecture is defensible rather than decorative.

| Component | MVP role | Grow when |
|---|---|---|
| SQS | Report + rebuild jobs, retries, DLQ | Job volume exceeds ~1/min sustained |
| ECS Fargate | API + worker | Worker p95 queue wait > 10 s |
| RDS PostGIS | Everything | Sustained CPU > 70% or read contention |
| S3 | Raw, processed, reports | Lifecycle tiering needed beyond 90 days |
| CloudWatch | Logs, metrics, alarms | Multi-environment dashboards |
| Secrets Manager | Credentials | Key rotation policy required |
| (not present) Redis | — | Mart queries optimised and N2 still breached |
| (not present) Dask | — | A single extract exceeds available RAM |
| (not present) read replica | — | Sustained read contention after optimisation |

### 8.4 Data flow

1. **Fetch** → `data/raw/<source>/<version>/`, hash, write fetch manifest. Versions pinned once; no silent re-download.
2. **Normalise** → parse, clip to the metro, standardise CRS/units, derive the canonical temporal axis → `data/processed/<source>/<version>/`.
3. **Validate** → §7.3 gates, geometry validity, range checks, coverage. Failure blocks promotion.
4. **Load canonical** → PostGIS: boundaries, census indicators, WorldPop grid, flood depth grid, point/polygon observations.
5. **Build mart** → compute every registered indicator for every scope × period × scenario × hazard parameter set. Each row carries its envelope.
6. **Publish** → the mart is the only read surface for tools.

Steps 1–6 are a CLI pipeline (`uv run python -m climate_resilience.pipeline ...`), not a web feature. Batch pipelines are testable, re-runnable and auditable; HTTP-triggered ingestion is none of those.

### 8.5 Why a mart, not live computation

- Query latency becomes milliseconds; overlay of a 1 km flood grid onto ~110 wards at request time does not.
- Results are stable between builds — the same question returns the same number.
- Rebuilding is an explicit, logged act, so a changed answer is always attributable to a changed input.
- Uncertainty, coverage and native resolution are computed once, with the value.

### 8.6 Report path

```text
POST /reports  → row in report_job (idempotency key) → SQS
worker         → maps (static PNG) + metrics table + evidence appendix
               → WeasyPrint → PDF → S3 → signed URL
GET /reports/{id} → status + link
```

Requirements: same image as the API; retries with backoff then DLQ; concurrency cap per API key (rendering is the one expensive operation and an uncapped endpoint is a denial-of-service vector); 90-day S3 retention; PDF metadata carries `run_id` and `mart_run_id`; a sidecar JSON envelope snapshot is stored beside the PDF so a report can be re-derived and diffed. The evidence appendix — dataset versions, checksums, methods, coverage — is what makes the report defensible.

WeasyPrint over headless Chromium: ~50 MB of image rather than ~300 MB, and HTML/CSS templating is sufficient. Maps are rendered server-side at job time as PNGs; there is no interactive map in a PDF.

---

## 9. Critical interfaces

### 9.1 Evidence envelope

Every tool return, every mart row and every rendered number uses one structure. Traceability, citation and abstention all fall out of it.

```python
class EvidenceEnvelope(BaseModel):
    value: float
    unit: str                      # "count", "degC", "percent", "persons"

    indicator_id: str              # "hot_days_tmax_ge_35c", "flood_exposed_area_pct"
    method_id: str
    method_version: str

    hazard_type: Literal["heat", "flood", "fire", "drought", "none"]
    return_period_years: int | None    # flood only: 10 | 50 | 100
    depth_threshold_m: float | None    # flood only, e.g. 0.5
    mechanism: Literal["riverine", "coastal"] | None  # flood only

    scope: Scope                   # level, id, name, geometry_ref
    period: Period                 # start, end, basis

    scenario: str | None           # null for non-projections
    model: str | None
    baseline_period: Period | None

    datasets: list[DatasetRef]     # id, version, checksum, source_url, licence
    uncertainty: Uncertainty | None
    quality: Quality               # n_samples, coverage_pct, missing_pct,
                                   # native_resolution, warnings
    run: RunRef                    # git_commit, run_id, created_at, inputs_hash
```

Rules: the assistant may restate `value`, `unit`, `period`, `scope`, `uncertainty` and `quality`. Nothing else. Null means the answer says so — it never fills the gap.

### 9.2 Tool contract

| Property | Requirement |
|---|---|
| Signature | Typed Pydantic input/output; no free-form SQL or dicts |
| Bounds | Ward IDs from the canonical table; indicator IDs from a closed registry; periods within coverage; return periods from `{10,50,100}` |
| Determinism | Same inputs → same output |
| Failure | Typed `InsufficientData(reason)` — never an exception the model must interpret |
| Budget | ≤ 3 tool calls per question; 10 s per call |
| Side effects | Read-only |

Tools are the *same functions* the API exposes. No second implementation for the assistant.

### 9.3 Mart schema (indicative)

```sql
indicator_value (
  indicator_id      text not null,
  method_version    text not null,
  scope_level       text not null,              -- 'ward' | 'municipality'
  scope_id          text not null,
  period_start      date not null,
  period_end        date not null,

  hazard_type       text not null,              -- heat|flood|fire|drought|none
  return_period_years integer,                  -- flood only
  depth_threshold_m double precision,           -- flood only
  mechanism         text,                       -- riverine|coastal

  basis             text not null,              -- observation|reanalysis|
                                                -- projection|modelled_estimate|derived
  scenario          text,
  model             text,
  baseline_start    date,
  baseline_end      date,

  value             double precision,
  unit              text not null,
  uncertainty_lower double precision,
  uncertainty_upper double precision,

  n_samples         integer,
  coverage_pct      numeric,
  missing_pct       numeric,
  native_resolution text,

  dataset_version   text not null,
  run_id            text not null,
  primary key (indicator_id, method_version, scope_level, scope_id,
               period_start, period_end, hazard_type, return_period_years,
               depth_threshold_m, mechanism, basis, scenario, model,
               dataset_version)
);
```

One row per published number, fully attributable. No aggregation at read time.

### 9.4 Report job

```sql
report_job (
  report_id       uuid primary key,
  idempotency_key text unique not null,
  scope_level     text not null,
  scope_id        text not null,
  template_id     text not null,
  template_version text not null,
  mart_run_id     text not null,
  status          text not null check (status in
                    ('queued','running','succeeded','failed','dead')),
  attempts        integer not null default 0,
  s3_key          text,
  error           text,
  requested_by    text not null,       -- hashed API key, never the key
  requested_at    timestamptz not null default now(),
  started_at      timestamptz,
  finished_at     timestamptz
);
```

### 9.5 Run manifest

Written by every pipeline stage and mart build:

```json
{
  "run_id": "2026-11-19T10:12:00Z-7f3a",
  "stage": "build_mart",
  "git_commit": "abc1234",
  "inputs": [{"path": "...", "sha256": "..."}],
  "parameters": {"period": ["1980-01-01", "2025-12-31"],
                 "flood_return_periods": [10, 50, 100],
                 "flood_depth_threshold_m": 0.5},
  "outputs": [{"path": "...", "sha256": "..."}],
  "package_versions": {"xarray": "...", "xclim": "...", "geopandas": "..."},
  "started_at": "...",
  "finished_at": "..."
}
```

CI holds a golden manifest: a rebuild from pinned inputs must produce identical output hashes (N9).

---

## 10. Analytical method standards

### 10.1 Coordinate systems

- Store **EPSG:4326**; compute distances and areas in **EPSG:32736 (UTM 36S)**.
- Use an **equal-area projection** for area-weighted statistics and densities; confirm the correct South African Albers EPSG rather than guessing.
- Record CRS on every dataset and catalogue entry; reprojection is explicit and logged.

### 10.2 Units and time

- SI internally; convert for display only, and state the display unit beside the value.
- Store timestamps in UTC; apply SAST (UTC+2) where a definition depends on calendar days. The day-boundary convention is part of the method.
- Record the temporal aggregation basis (hourly → daily → annual/seasonal) per indicator.

### 10.3 Spatial relationships

- Ward boundaries carry a **delimitation vintage**. Ward codes are not stable polygons across cycles.
- Maintain a versioned boundary table plus an explicit **crosswalk** to census geography. A join without a crosswalk is a defect.
- Gridded → polygon policy: **area-weighted mean** for continuous fields, **area fraction above threshold** for flood and fire, with contributing-cell counts recorded. The rule is documented per indicator, not chosen at runtime.
- Handle partial cells at the coastline and metro edge explicitly: report the fraction of the polygon with valid source data.

### 10.4 Indicator registry

Registered definitions; no ad-hoc calculations.

| Indicator | Definition | Basis | Notes |
|---|---|---|---|
| `hot_days_tmax_ge_35c` | Days/year with Tmax ≥ 35 °C | reanalysis | Threshold configurable, documented |
| `txx` | Annual max of daily Tmax | reanalysis | |
| `mean_tmax` | Annual/seasonal mean daily Tmax | reanalysis | Pair with Mann–Kendall + Sen's slope |
| `cdd` | Consecutive dry days | reanalysis | Use xclim's definition with a stated precipitation threshold |
| `rx1day` | Annual max 1-day precipitation | reanalysis | |
| `spi12` | 12-month SPI | reanalysis | State the fitting period |
| `flood_exposed_area_pct` | Ward area fraction with depth ≥ threshold | modelled_estimate | Per return period, mechanism, scenario |
| `flood_exposed_population` | WorldPop persons in grid cells with depth ≥ threshold | modelled_estimate | Dasymetric; per return period |
| `pop_exposed_pct` | Exposed persons ÷ ward population | derived | Denominator stated |
| `fire_detections_per_km2` | Detections/km²/year | observation | Confidence filter documented |

Where xclim implements a definition, use it and cite the version. Where it does not, implement explicitly and test against a worked example.

### 10.5 Uncertainty and missing data

Every metric reports sampling basis (grid cells per polygon), coverage percentage, missing percentage, and native resolution. If coverage falls below the indicator's threshold, the metric is withheld. Withheld is a valid, honest result.

### 10.6 Composite ranking

v1 forbade "risk scores" while requesting "highest combined exposure to vulnerability". Resolved:

- **Default:** hazard, exposure and vulnerability are presented as **separate, independently ranked axes**.
- **If a single ordering is required:** define an `Adaptation Priority Index` with published weights, explicit normalisation, stated direction per input, and a sensitivity test at ±20% weights. Label it an index. Never call it risk; never let the model compute it.

### 10.7 Flood-specific standards

| Item | Standard |
|---|---|
| Hazard source | Aqueduct Floods v2 riverine and coastal; GloFAS discharge as an independent riverine cross-check |
| Return periods | 10, 50, 100 years — reported separately, never averaged |
| Depth threshold | Default 0.5 m (any-inundation variant also computed); recorded in the envelope |
| Mechanism | Riverine and coastal reported separately; never summed |
| Scenario | Baseline and future (confirm SSP/RCP mapping in the Aqueduct release); projection labelling per I3 |
| Exposure denominator | Ward area for `flood_exposed_area_pct`; WorldPop persons for population. Ward-total population is retained only as a documented sensitivity comparison |
| Resolution honesty | ~1 km hazard grid means ward-scale statistics, not street-level prediction. `native_resolution` is displayed with every flood figure |
| Pluvial | Not modelled. Enforced by I9 |
| Validation | Extent comparison against Copernicus EMS mapping for a known riverine event; results recorded in the evaluation, not asserted |

The dasymetric-versus-ward-total choice materially changes exposed-population numbers. Both are computed during Phase 3; the difference is reported as a sensitivity range, and the dasymetric figure is the published one.

---

## 11. Assistant design

**Boundary of responsibility:** OpenRouter handles language — intent parsing, tool selection, prose. Python and PostGIS handle every number.

### 11.1 Behaviour

| Concern | Decision |
|---|---|
| Provider | OpenRouter via its OpenAI-compatible API, behind a thin adapter so the provider can be swapped |
| Model selection | Configuration (`LLM_MODEL_INTENT`, `LLM_MODEL_SYNTHESIS`), not user-facing |
| Orchestration | Single-pass tool selection; **two LLM calls maximum**; no autonomous loops |
| Grounding | Envelope JSON passed verbatim; the model may only restate it |
| Abstention | Typed `InsufficientData` result plus a required statement of what is missing |
| Citations | Every numeric claim rendered with a link to its envelope, dataset and method |
| Flood framing | Any flood answer must carry the riverine/coastal-only caveat; the prompt cannot omit it |
| Cost control | Per-question token cap, per-tool-result size cap, monthly budget alarm (N12, N13) |

### 11.2 Failure modes with typed responses

Unknown ward · indicator not in registry · period outside coverage · coverage below threshold · ambiguous scope (ward vs metro) · flood question implying pluvial · question needing an unregistered dataset. Each maps to a specific typed response, not to improvisation.

### 11.3 Latency and cost mechanisms

Applied in this order of measured impact:

| Lever | Effect |
|---|---|
| Mart-only reads | Removes the 10–40 s raster-overlay tail — the single largest win |
| Two LLM calls, not a loop | Halves latency and cost |
| Result cache keyed by canonicalised question + `mart_run_id` | Repeat questions approach zero cost; safe because answers are deterministic |
| Model tiering: small model for intent/tool selection, capable model for synthesis | ~60% cost reduction at equal quality |
| Prompt caching on the fixed system prompt + tool schema | Converts ~2.8k input tokens per call to cached reads |
| Output cap (300 tokens) and streaming | Bounds cost; lowers perceived latency |
| Parallel tool calls where independent | Removes serial round trips |

---

## 12. Evaluation

A harness in CI, not a review meeting.

### 12.1 Benchmark

25–30 questions: historical analysis, projections, exposure, vulnerability, **flood exposure (area and population)**, spatial comparison, multi-dataset, and **unanswerable** cases — including at least two that ask for pluvial flood risk, which must be refused with the correct explanation.

Each entry records: question, expected tool, expected dataset and version, geographic scope, reference answer, tolerance class, and whether abstention is correct.

**Reference answers must be produced independently of the code under test** — by hand, by a different library, or from a published value. Where independent derivation is infeasible, mark the item `unverified` and report it as such; do not count it as a pass.

### 12.2 Metrics and thresholds

| Area | Metric | Threshold |
|---|---|---|
| Data ingestion | Datasets passing all gates | 100% of the pilot bundle |
| Data quality | Invalid geometries, CRS mismatches, missing rates | 0 invalid; rates reported |
| Analytical correctness | Agreement with independent reference | N5 / N6 |
| Spatial accuracy | Ward overlay spot checks at known locations | 100% within expected ward |
| Flood validation | Overlap with EMS-mapped riverine extent for a known event | Reported, with false-positive and false-negative area |
| Sensitivity | Dasymetric vs ward-total exposed population | Difference reported as a range, not hidden |
| Retrieval accuracy | Correct tool, scope, period, return period | ≥ 90% (N8) |
| Groundedness | Numeric claims with an evidence reference | 100% (N4) |
| Abstention | Correct refusal on unanswerable items | 100%, zero confident errors (N7) |
| Flood caveat | Flood answers carrying the mechanism caveat | 100% |
| Reproducibility | Rebuild hash equality | identical (N9) |
| Latency | p50 / p95 answer and mart query | N1, N2 |
| Reports | PDF generation time; content matches envelope | N3; 100% |
| Cost | Per question, per benchmark run, monthly infra | N12, N13 |

### 12.3 Reporting

Results published as a table plus a failure analysis: which items failed, why, and what the limitation implies. A failing metric is reported as failing. Re-run on every change to analytics, tools or prompts; archive the run manifest with the results.

---

## 13. Delivery plan

Vertical slices. Each phase ends with a demonstrable, tested artifact and explicit exit criteria. The highest-risk question — *does eThekwini's data support the indicator we promised?* — is answered in Phase 1, not Phase 8.

| Phase | Work | Exit criteria | Est. |
|---|---|---|---|
| **0. Decisions and skeleton** | This spec, catalogue template, method registry template, ADR-001..005, `pyproject.toml`, Ruff, pytest, CI, Compose + PostGIS, `.env.example` | `uv run pytest` and `ruff check` green in CI; PostGIS reachable; ADRs merged | 2 d |
| **1. Walking skeleton** | MDB wards + ERA5 → canonical layer → `hot_days_tmax_ge_35c` → mart row → CLI output → envelope → manifest | Number reproduces from one command; envelope complete; checksums written; gates recorded | 5 d |
| **2. Spatial foundation** | Versioned boundaries, validity repair, vintage crosswalk to census wards, CRS/units gates, WorldPop ingest, overlay spot tests | 100% valid geometries; area sanity check within tolerance; spot checks pass | 4 d |
| **3. Exposure and vulnerability** | Census 2022 indicators; dasymetric exposure via WorldPop; ward-total sensitivity comparison | Mart queryable; every row attributable; no `risk` column; sensitivity range reported | 5 d |
| **4. Heat and drought** | Full heat/drought registry: Txx, mean Tmax trends (Mann–Kendall + Sen's slope), CDD, Rx1day | Reference tests pass incl. trend slope | 4 d |
| **5. Flood hazard** | Aqueduct Floods v2 ingest; 10/50/100-yr; riverine/coastal; thresholds; ratio indicators; GloFAS cross-check | Envelope carries mechanism/return period/threshold; I4 and I9 tested; resolution displayed | 5 d |
| **6. Projections** | NCCIS 2021–2050 RCP4.5/8.5 for the same indicators; labelling enforced | I3 tested; scenario/baseline present on every projection row | 4 d |
| **7. Fire** | FIRMS detections, confidence filter, density per km² | Reference test; density denominators documented | 2 d |
| **8. Tools and API** | Typed tools over the mart, FastAPI, OpenAPI, bounds and contract tests | Contract tests pass; mart p95 measured against N2 | 4 d |
| **9. Assistant** | OpenRouter adapter, tiered models, ≤ 3 tools, ≤ 2 calls, cache, abstention, citations, flood caveat | Abstention works incl. pluvial questions; no unsupported numerics in spot checks; cost measured against N12 | 5 d |
| **10. PDF reports** | `report_job`, SQS + DLQ, worker entrypoint, WeasyPrint templates, static maps, evidence appendix, signed URLs, concurrency cap | A report completes < 60 s; content matches envelopes; DLQ path exercised | 4 d |
| **11. Interface** | Streamlit: map, indicator explorer, chat with citations, report request and status | A user answers all seven §3 questions unaided | 4 d |
| **12. Evaluation** | Benchmark incl. pluvial refusals and EMS validation; independent references; CI harness; failure analysis | N1–N9 measured and reported, including failures | 4 d |
| **13. AWS deployment** | Terraform, ECR, ECS (api + worker), RDS, S3, SQS + DLQ, Secrets, CloudWatch alarms, migrations, backups | Smoke test passes in AWS; parity confirmed; RPO/RTO documented; cost measured | 4 d |

**Total ≈ 56–60 working days (~8 weeks) solo.** Revise after Phase 1.

**Definition of done per phase:** tests pass, artifact demonstrable, catalogue/registry updated, limitation written down.

---

## 14. Operations

### 14.1 Observability

Structured JSON logs: request id, tools, latency, tokens, cost, cache hit, mart_run_id. Metrics: request rate, p50/p95 latency, tool error rate, abstention rate, cache hit rate, LLM cost/hour, queue depth, report duration, ingestion and mart build duration, mart row counts.

Alarms: latency above N1 for 15 min · error rate above 2% · cost above monthly budget · queue depth above threshold for 10 min · DLQ non-empty · failed ingestion or mart build.

### 14.2 Security

- No secrets in the repository, images or logs; `.env.example` lists names only; Secrets Manager in AWS.
- API key required on all non-local endpoints; token-bucket rate limit per key (429 with `Retry-After`).
- Report endpoint has a separate, lower concurrency cap per key.
- Read-only DB role for the API; migrations use elevated credentials.
- Aggregate public data only; no PII. Census small-cell suppression respected — enforce a minimum population threshold for any published ward statistic.
- Ingested text is untrusted: file contents are never treated as instructions; document excerpts are not sent to the model in the MVP.
- Dependencies pinned and scanned; images pinned by digest.

### 14.3 Availability and recovery

Pilot target 99.5% during business hours. Single-AZ is an accepted, documented tradeoff: lower cost, at the price of a multi-hour outage risk. RPO 24 h (nightly snapshot), RTO 4 h (restore + redeploy via Terraform), both rehearsed once before the demo.

### 14.4 Deployment

Identical image local and cloud (N14). Migrations as a pre-deploy ECS task. Rolling deployment with health-check gates; rollback is redeploying the previous image digest. Terraform state in S3 with locking.

### 14.5 Cost model

Per question, two calls (intent ~1.8k in / 150 out; synthesis ~3.4k in / 400 out):

```
cost = (in_tokens  × price_in  + out_tokens × price_out) / 1_000_000
     = (5,200 × 0.50 + 550 × 1.50) / 1_000_000
     ≈ $0.0034
```

| Scenario | Cost |
|---|---|
| Unchanged prompt, no caching | ~$0.0034 |
| With prompt caching (~2.8k tokens cached at ~10%) | ~$0.0022 |
| Cache hit on a repeated question | ~$0.0000 |
| Worst case with one retry | ~$0.0069 (inside the $0.02 cap) |
| 30-question benchmark run | ~$0.10 |
| Three-model sweep × 3 runs | ~$1 |

Infrastructure, indicative monthly: RDS PostGIS $30–60 · ECS Fargate api+worker $20–40 · ALB if used ~$18 · S3 and transfer single digits · CloudWatch ~$5. Total ≈ $80–130, inside N13. Confirm with the AWS pricing calculator before provisioning; record actuals after one month. Prices and model rates are configuration, verified at Phase 9.

---

## 15. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| **Pluvial flooding not covered** (the 2022 mechanism) | Users may read riverine results as general flood risk | Binding caveat on every flood surface (I9, §3); pluvial questions refused; limitation documented |
| Flood hazard resolution (~1 km) read as street-level | Overstated precision | `native_resolution` displayed with every flood figure; ward-scale wording enforced |
| WorldPop vs ward-total exposure differ materially | Headline numbers shift between methods | Both computed in Phase 3; range published; dasymetric is the published figure |
| Census 2022 not available at ward level | Vulnerability axis coarser than exposure surface | Verify early; reconcile explicitly or report at a coarser level with the mismatch stated |
| Ward vintage mismatch (2021 vs 2026) | Silently wrong joins | Explicit vintage + crosswalk; reconcile ward counts and codes |
| WorldPop release built on a different census vintage than Census 2022 | Inconsistent denominators | Pin the matching release; record it in the catalogue |
| GreenBook not programmatically accessible | Lose richest municipal context | Context only; no analytic depends on it |
| NCCIS files large or awkward | Extraction effort | Subset at ingest; confirm mechanics in Phase 6 planning |
| ERA5 ~31 km grid presented as ward accuracy | Overstated precision | Report cell counts and sampling basis; describe results as metro-constrained |
| ERA5 licence/rate limits block re-download | Non-reproducible pipeline | Pin a retrieved copy with checksum and retrieval date |
| A single wrong number destroys user trust | Project failure | Mart + envelope + abstention + benchmark; zero tolerance on N4 and N7 |

**Unverified at the time of writing:** scripted download feasibility per source, licence terms, ward-level census availability, exact eThekwini ward count, the MDB release vintage pairing with Census 2022, the Aqueduct return-period/scenario parameter set for this release, and the EMS activation ID for a riverine validation event. Each is a Phase 1–5 acceptance test. None is assumed in the design.

---

## 16. Repository structure

```text
climate-resilience-ai/
├── README.md
├── AGENTS.md
├── climate-resilience.md            # this specification
├── pyproject.toml
├── uv.lock
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── adr/                         # 001..005
│   ├── data-catalogue.md
│   ├── methods.md                   # indicator registry
│   ├── limitations.md
│   └── archive/{brief-v1.md, spec-v2.md}
├── data/
│   ├── raw/         # immutable, git-ignored
│   ├── processed/   # git-ignored
│   ├── reference/   # small committed fixtures
│   └── catalogue/   # machine-readable dataset entries, committed
├── src/climate_resilience/
│   ├── ingestion/
│   ├── canonical/
│   ├── indicators/      # heat, drought, flood, fire
│   ├── exposure/        # worldpop dasymetric, ward-total comparison
│   ├── mart/
│   ├── tools/           # single source of truth for analytics
│   ├── api/
│   ├── agent/
│   ├── reporting/       # PDF templates, map rendering
│   ├── worker/          # queue consumer entrypoint
│   └── evaluation/
├── tests/
│   ├── test_ingestion.py
│   ├── test_spatial.py
│   ├── test_indicators.py
│   ├── test_flood.py
│   ├── test_exposure.py
│   ├── test_mart.py
│   ├── test_tools.py
│   ├── test_agent.py
│   ├── test_reporting.py
│   └── test_reproducibility.py
├── eval/
│   ├── questions.json
│   ├── reference_answers.json
│   └── results/
└── infrastructure/aws/              # Terraform
```

---

## 17. Deliverables

1. **Working application** — natural-language interface and analytical explorer answering the seven §3 questions, with citations.
2. **Local deployment** — `uv` + Docker Compose, one command.
3. **AWS deployment** — Terraform, containerised api and worker, documented, with alarms and measured cost.
4. **Data pipeline** — reproducible, checksummed, versioned, catalogued, with qualification results.
5. **Analytical tools** — indicator registry across heat, drought, flood and fire, with tests and reference values.
6. **PDF reports** — asynchronous, evidence-appended, reproducible from the stored run.
7. **Evaluation results** — benchmark, independent references, measured metrics, failure analysis.
8. **Documentation** — sources, licences, architecture, ADRs, methods, limitations.
9. **Demonstration** — real questions, cited outputs, a generated report, and an honest refusal.

---

## 18. Next actions

1. Review and approve this specification — especially the flood scope caveat (§3), the pluvial non-goal (§4.3), and the exposure method choice (§10.7).
2. Run Phase 0: ADR-001..005, repository scaffold, CI green.
3. Execute Phase 1 with one goal: prove eThekwini's real data supports one indicator end to end, with a complete evidence trail.

Everything else waits until that is true.
