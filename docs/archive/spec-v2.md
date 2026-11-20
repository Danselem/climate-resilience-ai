# Climate Resilience Intelligence Platform

**Version 2 — design specification**
**Status:** draft for review · supersedes `docs/archive/brief-v1.md`
**Pilot:** eThekwini Municipality, South Africa
**Stack:** Python 3.12 · FastAPI · PostGIS · Streamlit · OpenRouter · AWS

---

## 0. What changed in v2

v1 was a brief: it described features, sources and deliverables. v2 keeps that intent and adds the engineering decisions needed to build it — requirements with measurable targets, a capacity estimate, the interfaces that make traceability enforceable, and a delivery order driven by risk rather than by layer.

| Change | Reason |
|---|---|
| Numeric non-functional targets added | v1's success criteria were not falsifiable |
| Capacity estimate added | v1's AWS component list was not justified by load; the pilot is < 5 GB and ~0.01 QPS |
| Precomputed indicator mart made mandatory | Raster computation at question time is slow and makes answers drift |
| Evidence envelope defined | "Every metric traceable" was a value, not an interface |
| SQS, Dask, read replicas removed from MVP | No measured bottleneck justifies them; triggers defined in §8.3 |
| Delivery reordered into vertical slices | v1 deferred the highest-risk question ("does the data support the indicator?") to week 6+ |
| Flood removed from MVP example questions | v1 §12 deferred flood but §4 and §7 used flood as the flagship question |
| Composite ranking made explicit | v1 forbade "risk scores" while requesting a combined ranking; resolved in §10.6 |
| Independent reference answers mandated | Reference values computed by the code under test prove nothing |
| Operations, security and cost sections added | v1 named tools without defining how they are operated |

Everything else — the problem, the data sources, the anti-hallucination stance, the hazard/exposure/vulnerability separation — is retained from v1.

---

## 1. Purpose and scope

Build a working proof of concept showing how public climate and socioeconomic data can be turned into **reproducible, evidence-backed planning insight** for a South African municipality.

The system is not a climate chatbot. It is an analytical system whose outputs are computed deterministically, recorded with their provenance, and explained by a language model that may only restate what the analytics returned.

**In scope (MVP):** one municipality (eThekwini), one primary hazard, one end-to-end vertical slice from source download to displayed result, a natural-language interface over that slice, a measured evaluation harness, and a cloud deployment of the same code.

**Out of scope (see §4.3):** multi-municipality, flood modelling, real-time data, user accounts, mobile, offline field use.

---

## 2. Problem statement

Municipal adaptation teams can access climate projections, hazard maps, census data and environmental datasets, but these live on different platforms, in different formats, coordinate systems and time bases. Combining them for a local assessment requires GIS and climate-data expertise that most municipalities do not have, and the resulting analyses are rarely reproducible — a figure in a planning document often cannot be traced back to a dataset version, a method, or a calculation.

The gap is therefore not data availability. It is **integration, interpretation and evidence**.

| Challenge | What the system addresses |
|---|---|
| Fragmented data | One analytical environment with a canonical spatial and temporal model |
| Difficult interpretation | Plain-language explanation of computed indicators |
| Limited accessibility | Questions answered without SQL or GIS scripting |
| Weak evidence trails | Every number carries a complete provenance record |
| Planning implications | Exposure and vulnerability identified per ward, not just climate statistics |

---

## 3. Users and the questions the system must answer

**Primary users:** municipal climate adaptation planners, GIS analysts, and disaster-management staff. Estimated 5–50 users in the pilot; no assumption of technical GIS skill.

The pilot must answer questions of this shape, and must be able to say *"I don't have the data for that"* for everything else:

1. Which wards have experienced the greatest increase in hot days (Tmax ≥ 35 °C)?
2. How has annual rainfall changed across the metro since 1980?
3. Which wards are projected to see longer dry spells by 2050 under RCP8.5?
4. Which wards combine high heat exposure with high socioeconomic vulnerability?
5. How do observed recent conditions compare with the modelled 2021–2050 projection?
6. Which wards recorded the most fire detections per square kilometre per year?

Note: v1 used flood as its flagship example. Flood is deferred (§4.3) because no suitable flood-hazard dataset is secured; promising flood analysis in the demo would be dishonest.

---

## 4. Requirements

### 4.1 Functional

| ID | Requirement |
|---|---|
| F1 | Ingest the pilot datasets reproducibly, storing raw inputs immutably with checksums |
| F2 | Publish a canonical spatial layer: municipality and ward boundaries, versioned, valid, with a documented CRS policy |
| F3 | Compute registered climate indicators from ERA5 for every ward over a defined historical period |
| F4 | Compute exposure by intersecting hazard indicators with ward population |
| F5 | Compute ward-level vulnerability indicators from Census 2022, kept as a separate axis from hazard |
| F6 | Serve all published metrics from a precomputed indicator mart via a typed API |
| F7 | Answer natural-language questions by selecting bounded analytical tools and restating their outputs |
| F8 | Cite dataset, period, scope and method for every numeric claim, in the UI and in reports |
| F9 | Abstain explicitly when the required data, period or scope is unavailable |
| F10 | Generate an evidence-backed summary report for a chosen ward or the municipality, asynchronously |

### 4.2 Non-functional

These are acceptance targets for the pilot, not aspirations. Each is measured in §12.

| ID | Requirement | Target |
|---|---|---|
| N1 | End-to-end answer latency (single-metric question) | p95 ≤ 10 s |
| N2 | Mart query latency, excluding LLM | p95 ≤ 3 s |
| N3 | Report generation | ≤ 90 s, asynchronous |
| N4 | Numeric claims carrying an evidence reference | 100% |
| N5 | Tolerance vs independent reference: counts | exact |
| N6 | Tolerance vs independent reference: continuous indicators | ≤ 0.5 °C, ≤ 5% relative |
| N7 | Correct abstention on unanswerable questions | 100%, zero confident wrong answers |
| N8 | Tool-selection accuracy on the benchmark | ≥ 90% |
| N9 | Reproducibility: same inputs + same commit | byte-identical mart output |
| N10 | Availability during pilot business hours | 99.5% (single-AZ accepted; see §14.3) |
| N11 | Backup RPO / RTO | 24 h / 4 h |
| N12 | LLM cost per question | ≤ $0.01 average |
| N13 | Pilot infrastructure cost | ≤ $150 / month |
| N14 | Environment parity | identical container image locally and in AWS |
| N15 | Code quality | `uv run ruff check .` clean; full type hints; ≥ 80% coverage on analytics and spatial modules |
| N16 | Observability | every request logged with request id, tools called, latency, tokens, cost |

### 4.3 Non-goals

Stated to prevent scope drift, and to make the deferral explicit rather than accidental.

- **Flood hazard.** No secured flood-hazard, drainage or high-resolution elevation dataset. Revisit only when one is acquired and documented.
- **Multi-municipality.** eThekwini only, until the pipeline is validated.
- **Real-time or forecast data.** Historical reanalysis and published projections only.
- **"Risk score".** See §10.6 — no composite risk number without an explicit, published, sensitivity-tested method.
- **User accounts and personal data.** No authentication-backed profiles; aggregate public data only.
- **Model-comparison UI.** Model selection is configuration, not an end-user feature.
- **Orchestration frameworks, vector databases, workflow schedulers, Kubernetes.** No measured requirement.

---

## 5. Scale and capacity estimate

Order-of-magnitude reasoning that determines the architecture. Figures are assumptions to confirm in Phase 1; the conclusions are robust to being wrong by 10×.

| Quantity | Estimate | Basis |
|---|---|---|
| Concurrent users | 5–50 | One municipality |
| Question rate | ≤ 1,000 / day ≈ 0.01 QPS average, ~0.1 peak | 50 users × 20 questions |
| ERA5 metro extract | 0.25° grid ≈ 3×3 to 4×4 cells; 40 years hourly ≈ 3–6 M values per variable ≈ 15–25 MB float32 | Subset at download, not global |
| Census 2022 ward table | ~110 rows × ~50 columns | Confirm ward count and vintage (§15) |
| FIRMS metro detections | Thousands of rows over 20 years | CSV |
| GreenBook package | Tens to low hundreds of MB | To verify |
| **Total pilot footprint** | **< 5 GB** | |
| Dominant latency | LLM inference: 1–5 s per call | Not query throughput |

**Conclusions:**

1. **There is no throughput or storage problem.** One PostgreSQL instance, one stateless API service, and object storage are sufficient. Sharding, replicas, caching layers, distributed compute and queues are not warranted.
2. **The bottlenecks are LLM latency and raster computation.** Both are addressed by precomputing indicators (§8.4) and by keeping tool calls bounded.
3. **Data volume is small enough that correctness, lineage and validation are the real engineering work** — not scale.

Indicative latency budget for a single-metric question (N1):

| Stage | Budget |
|---|---|
| Intent parsing and tool selection | 500–1,500 ms |
| Mart query | 20–100 ms |
| Answer synthesis | 1,000–4,000 ms |
| Render | < 200 ms |
| **p95 total** | **~6 s, SLO 10 s** |

---

## 6. Domain invariants

These are enforced in code and tested. They are the analytical contract of the platform, and the reason answers can be trusted.

| ID | Invariant |
|---|---|
| I1 | Hazard, exposure and vulnerability are stored and reported separately. No column named `risk`. |
| I2 | Every record declares its evidence type: `observation`, `reanalysis`, `projection`, or `derived`. |
| I3 | Every projection record carries scenario, model, baseline period and projection period. Mixing unlabelled observations and projections is a validation error. |
| I4 | Units, CRS, spatial resolution and time basis are validated before any join. Mismatch fails loudly rather than being silently coerced. |
| I5 | Raw source files are immutable. Derived outputs live in separate versioned locations. |
| I6 | Every published metric is reproducible from a recorded inputs hash and code commit. |
| I7 | Missing data is reported, never interpolated silently; if coverage falls below the method's threshold, the metric is withheld. |

---

## 7. Data

### 7.1 Sources and roles

| Source | Data collected | Role | Access |
|---|---|---|---|
| [GreenBook](https://www.greenbook.co.za/greenbook-support.html) | Municipal risk profiles, maps, data packages, vulnerability and exposure context | Primary municipal context | Manual package download — verify |
| [NCCIS](https://nccis.environment.gov.za/climate-services/download-data) | CSIR and SAWS projections; changes relative to 1971–2000 for 2021–2050 under RCP4.5 / RCP8.5 | Future projections | Portal download — verify |
| [Copernicus CDS](https://cds.climate.copernicus.eu/en/how-to-api) | ERA5 hourly temperature and precipitation | Historical baseline | CDS API; account and licence acceptance |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/download/) | MODIS / VIIRS active fire detections | Wildfire observation | CSV/JSON/shapefile; registration for archive |
| [Stats SA](https://www.statssa.gov.za/) | Census 2022 population, households, demographic indicators | Exposure and vulnerability | Verify ward-level availability |
| [Municipal Demarcation Board](https://www.demarcation.org.za) | Municipal and ward boundaries | Geographic reference | Verify release vintage |

### 7.2 Pilot bundle

| Phase | Datasets |
|---|---|
| **First slice** | MDB ward boundaries + ERA5 historical temperature |
| Second slice | Census 2022 ward indicators |
| Projections | NCCIS 2021–2050 under RCP4.5 and RCP8.5 |
| Optional | FIRMS fire detections |
| Context only | GreenBook (read for framing and cross-checking, not as a computation input until its file structure is understood) |

GreenBook is valuable but its packages are documents and dashboards rather than a tidy API. Treat it as context and cross-check first; do not make the analytics depend on parsing it.

### 7.3 Data qualification gates

No dataset enters the pipeline until every gate passes. A gate failure is a documented finding, not a reason to improvise.

| Gate | Test |
|---|---|
| Access | Can it be retrieved by script or by a documented manual step? |
| Licence | Is redistribution and derived use permitted? Recorded in the catalogue |
| Coverage | Does it actually cover eThekwini for the required period? |
| Format | Is it parseable with a maintained library? |
| CRS and units | Declared and internally consistent? |
| Identifiers | Do geographic identifiers match between sources at the required level? |
| Vintage | Does the boundary/ward vintage align with the census vintage? |
| Size | Is the subset small enough to handle without distributed compute? |

### 7.4 Catalogue requirements

One machine-readable entry per dataset, stored alongside the code and validated by a test. Required fields: source name, URL, retrieval date, licence, version or release, checksum, units, CRS, spatial coverage, temporal coverage, native resolution, time basis, known gaps, and processing steps applied.

---

## 8. Architecture

### 8.1 Layers

```text
sources → ingestion (fetch, verify, catalogue)
        → canonical layer (spatial + temporal normalisation, PostGIS)
        → indicator mart (precomputed metrics + evidence envelopes)
        → tools / API (typed functions, bounded inputs)
        → assistant (OpenRouter: select tool, restate result, cite)
        → interfaces (Streamlit: map, explorer, chat, report)
```

Strict rule: **the interface layer never computes a metric.** It reads the mart. The assistant never reads a raster, a CSV, or a database table directly — only tool outputs.

### 8.2 Runtime components

Identical code, identical image, environment-driven configuration.

| Concern | Local | AWS |
|---|---|---|
| Compute | Docker Compose: api, ui | ECS Fargate: api, ui services |
| Database | PostGIS container | RDS PostgreSQL + PostGIS |
| Object storage | `data/` directory | S3 (raw, processed, reports) |
| Secrets | `.env` (git-ignored) | Secrets Manager |
| Logs and metrics | stdout | CloudWatch |
| Scheduling | Cron / `make` targets | EventBridge → ECS task |
| Infrastructure | `docker-compose.yml` | Terraform |

### 8.3 Deliberately absent, and when to add it

Each block below trades operating complexity for a capability the MVP has not yet demonstrated a need for. Adding one early multiplies failure modes without buying anything.

| Block | Trigger to add |
|---|---|
| SQS / worker fleet | Ingestion exceeds ~10 min, needs retries, or reports exceed 90 s |
| Redis cache | Mart queries already optimised and p95 still breaches N2 |
| Read replica | Sustained DB CPU > 70% or measured read contention |
| Dask / distributed compute | A single extract exceeds available RAM |
| Sharding | Not applicable at this scale; would require a design review |
| Vector database | Document retrieval becomes an actual user requirement |
| Kubernetes | Multi-tenant platform with independent scaling needs |
| Model-comparison UI | Evaluation needs broader model coverage than config supports |

### 8.4 Data flow

1. **Fetch** — download to `data/raw/<source>/<version>/`, hash, write a fetch manifest. Never re-download silently; a version is pinned once.
2. **Normalise** — parse, subset to the metro bounding box, standardise CRS and units, derive the canonical temporal axis. Output to `data/processed/<source>/<version>/`.
3. **Validate** — gate checks (§7.3), geometry validity, range checks, coverage. Failure blocks promotion.
4. **Load canonical** — PostGIS tables for boundaries, census indicators, and point/polygon observations.
5. **Build mart** — compute every registered indicator for every scope × period × scenario. Each row carries its evidence envelope. This is a batch job with a manifest, not an API path.
6. **Publish** — mart becomes the only read surface for tools.
7. **Serve** — API and assistant queries the mart.

Steps 1–6 are a CLI pipeline (`uv run python -m crpipeline ...`), not a web feature. That is deliberate: batch pipelines are testable, re-runnable and auditable; HTTP-triggered ingestion is none of those things.

### 8.5 Why a mart rather than live computation

- Query latency becomes milliseconds instead of tens of seconds.
- Results are stable between builds; the same question returns the same number.
- Rebuilding is an explicit, logged act — so a changed answer is always attributable to a changed input.
- Uncertainty and coverage are computed once, with the value, not reconstructed later.

---

## 9. Critical interfaces

### 9.1 Evidence envelope

Every tool return, every mart row, and every rendered number uses the same structure. This is the spine of the system: traceability, citation and abstention all fall out of it.

```python
class EvidenceEnvelope(BaseModel):
    value: float
    unit: str
    indicator_id: str            # e.g. "hot_days_tmax_ge_35c"
    method_id: str
    method_version: str

    scope: Scope                 # level, id, name, geometry_ref
    period: Period               # start, end, basis: observation|reanalysis|projection|derived

    scenario: str | None         # null for observations
    model: str | None            # null for observations
    baseline_period: Period | None

    datasets: list[DatasetRef]   # id, version, checksum, source_url, licence
    uncertainty: Uncertainty | None   # type, lower, upper
    quality: Quality             # n_samples, coverage_pct, missing_pct, warnings
    run: RunRef                  # git_commit, run_id, created_at, inputs_hash
```

Rules: the assistant may restate `value`, `unit`, `period`, `scope` and `uncertainty` — nothing else. If a field is null, the answer must say so rather than fill the gap.

### 9.2 Tool contract

| Property | Requirement |
|---|---|
| Signature | Typed Pydantic input and output; no free-form SQL or dicts |
| Bounds | Scope restricted to known ward IDs; indicator IDs from a closed registry; periods limited to available coverage |
| Determinism | Same inputs → same output |
| Failure | Returns a typed `InsufficientData` result with a reason, never an exception the model must interpret |
| Budget | ≤ 5 tool calls per question; per-call timeout of 10 s |
| Side effects | Read-only |

Tools are the *same functions* the API exposes. There is no second implementation for the assistant — that is how drift and inconsistency enter a system.

### 9.3 Mart schema (indicative)

```sql
indicator_value (
  indicator_id      text        not null,
  method_version    text        not null,
  scope_level       text        not null,   -- 'ward' | 'municipality'
  scope_id          text        not null,
  period_start      date        not null,
  period_end        date        not null,
  basis             text        not null,   -- observation|reanalysis|projection|derived
  scenario          text,                   -- null for non-projection
  model             text,
  baseline_start    date,
  baseline_end      date,
  value             double precision,
  unit              text        not null,
  uncertainty_lower double precision,
  uncertainty_upper double precision,
  n_samples         integer,
  coverage_pct      numeric,
  missing_pct       numeric,
  dataset_version   text        not null,
  run_id            text        not null,
  primary key (indicator_id, method_version, scope_level, scope_id,
               period_start, period_end, basis, scenario, model, dataset_version)
);
```

One row per published number, fully attributable. No aggregation happens at read time.

### 9.4 Run manifest

Written by every pipeline stage and every mart build:

```json
{
  "run_id": "2026-11-19T10:12:00Z-7f3a",
  "stage": "build_mart",
  "git_commit": "abc1234",
  "inputs": [{"path": "...", "sha256": "..."}],
  "parameters": {"period": ["1980-01-01", "2024-12-31"]},
  "outputs": [{"path": "...", "sha256": "..."}],
  "package_versions": {"xarray": "...", "xclim": "..."},
  "started_at": "...",
  "finished_at": "..."
}
```

CI holds a golden manifest: a rebuild from pinned inputs must produce identical output hashes (N9).

---

## 10. Analytical method standards

### 10.1 Coordinate systems

- Store in **EPSG:4326** for portability and GeoJSON compatibility.
- Compute distances and areas in **EPSG:32736 (UTM zone 36S)** covering the metro.
- Use an **equal-area projection** for area-weighted statistics and densities; confirm the correct South African Albers EPSG rather than guessing.
- Record the CRS on every dataset and in every catalogue entry; re-projection is explicit and logged.

### 10.2 Units and time

- SI units internally; convert for display only, and state the display unit alongside the value.
- Store timestamps in UTC; apply SAST (UTC+2) when a definition depends on calendar days. Day-boundary convention is part of the method, not an implementation detail.
- Record the temporal aggregation basis (hourly → daily → annual/seasonal) per indicator.

### 10.3 Spatial relationships

- Ward boundaries carry a **delimitation vintage**. Boundaries change between cycles; a ward code from one release is not the same polygon in another.
- Maintain a versioned boundary table and an explicit **crosswalk** to the census geography. A join without a crosswalk is a defect.
- Overlay policy for gridded data: area-weighted mean per polygon, with the number of contributing cells recorded. Cells straddling a boundary are not silently included or excluded — the rule is documented per indicator.

### 10.4 Indicator registry

Each indicator is a registered entry with a definition, citation, inputs, period, threshold, aggregation, and uncertainty note. Do not invent definitions ad hoc.

| Indicator | Definition | Notes |
|---|---|---|
| `hot_days_tmax_ge_35c` | Days per year with daily Tmax ≥ 35 °C | Threshold configurable; document choice |
| `txx` | Annual maximum of daily Tmax | |
| `mean_tmax` | Annual and seasonal mean daily Tmax | Pair with Mann–Kendall + Sen's slope for trend |
| `cdd` | Consecutive dry days | Requires a precipitation threshold; use xclim's definition |
| `rx1day` | Annual maximum 1-day precipitation | |
| `spi12` | 12-month standardised precipitation index | State the fitting period |
| `fire_detections_per_km2` | Detections per km² per year | Requires FIRMS confidence filtering |

Where xclim implements a definition, use it and cite the version. Where it does not, implement the definition explicitly and test it against a worked example.

### 10.5 Uncertainty and missing data

Every metric reports: sampling basis (grid cells per polygon), coverage percentage, missing-data percentage, and a quantified uncertainty where the method supports one. If coverage falls below the threshold defined for that indicator, the metric is withheld rather than published with a caveat. Withheld is a valid, honest result.

### 10.6 Composite ranking

v1 forbade "risk scores" but asked for "highest combined exposure to vulnerability". Resolved as follows:

- **Default:** present hazard, exposure and vulnerability as **separate, independently ranked axes**. The user sees where a ward ranks on each, not a single number.
- **If a single ordering is required:** define an `Adaptation Priority Index` with published weights, an explicit normalisation basis, a stated direction for each input, and a sensitivity test showing how the ranking changes at ±20% weights. Label it an index. Never call it risk, and never let the model compute it.

---

## 11. Assistant design

**Boundary of responsibility:** OpenRouter handles language — intent parsing, tool selection, and prose. Python and PostGIS handle every number.

| Concern | Decision |
|---|---|
| Provider | OpenRouter via its OpenAI-compatible API, behind a thin adapter so the provider can be swapped |
| Model selection | Configuration (`LLM_MODEL`), not user-facing |
| Orchestration | Single-pass tool selection with bounded calls; no autonomous multi-step loops in the MVP |
| Grounding | The model receives envelope JSON verbatim and may only restate it |
| Abstention | Explicit `InsufficientData` result plus a required "what is missing" explanation |
| Citations | Every numeric claim rendered with a link to its envelope, dataset and method |
| Logging | Model, prompt/completion tokens, latency, estimated cost, tools called, request id. Never the API key, never raw user text in telemetry |
| Prompt injection | Retrieved text is data, never instruction; tool outputs are structured, not free prose; document excerpts are not fed to the model in the MVP (datasets remain local and aggregate) |
| Cost control | Per-question token cap, per-tool-result size cap, monthly budget alert (N12, N13) |

Failure modes the design must handle explicitly: unknown ward, indicator not in the registry, period outside coverage, low coverage, ambiguous scope (ward vs metro), and a question requiring flood data. Each maps to a specific typed response, not to improvisation.

---

## 12. Evaluation

Evaluation is a harness in CI, not a review meeting.

### 12.1 Benchmark

20–30 questions covering: historical analysis, projections, exposure, vulnerability, spatial comparison, multi-dataset, and **unanswerable** cases. Each entry records: question, expected tool, expected dataset and version, geographic scope, reference answer, tolerance class, and whether abstention is the correct outcome.

**Reference answers must be produced independently of the code under test** — derived by hand, by a different library, or from a published value. Comparing a function to itself is not a test. Where independent derivation is infeasible, mark the item `unverified` and say so in the results; do not count it as a pass.

### 12.2 Metrics and thresholds

| Area | Metric | Threshold |
|---|---|---|
| Data ingestion | Datasets passing all gates | 100% of the pilot bundle |
| Data quality | Invalid geometries, CRS mismatches, missing-value rate | 0 invalid; missing rate reported per dataset |
| Analytical correctness | Agreement with independent reference | N5 / N6 |
| Spatial accuracy | Ward overlay spot checks at known locations | 100% within expected ward |
| Retrieval accuracy | Correct tool, scope, period | ≥ 90% (N8) |
| Groundedness | Numeric claims with an evidence reference | 100% (N4) |
| Abstention | Correct refusal on unanswerable items | 100%, zero confident errors (N7) |
| Reproducibility | Rebuild hash equality | identical (N9) |
| Performance | p50 / p95 latency, mart query time | N1–N3 |
| Cost | Per question, per benchmark run, monthly infrastructure | N12, N13 |

### 12.3 Reporting

Results are published as a table plus a failure analysis: which questions failed, why, and what the limitation implies. A failing metric is reported as failing. Evaluations are re-run on every change to analytics, tools, or prompts, and the run manifest is archived with the results.

---

## 13. Delivery plan

Vertical slices. Each phase ends with a demonstrable, tested artifact and explicit exit criteria. The highest-risk question — *does eThekwini's data support the indicator we promised?* — is answered in Phase 1, not Phase 6.

| Phase | Work | Exit criteria | Est. |
|---|---|---|---|
| **0. Decisions and skeleton** | Requirements (this doc), data catalogue template, method registry template, ADR-001..004, `pyproject.toml`, Ruff, pytest, CI, Compose + PostGIS, `.env.example` | `uv run pytest` and `ruff check` green in CI; PostGIS reachable; ADRs merged | 2 d |
| **1. Walking skeleton** | MDB wards + ERA5 extract → canonical layer → one indicator (`hot_days_tmax_ge_35c`) → mart row → CLI output | Number reproduces from one command; envelope complete; checksums and manifest written; data qualification gates recorded | 5 d |
| **2. Spatial foundation** | Versioned boundaries, validity repair, crosswalk to census wards, CRS/units validation gates, overlay spot tests | 100% valid geometries; area sanity check within tolerance; spot checks pass | 3 d |
| **3. Exposure and vulnerability** | Census 2022 ward indicators; population exposure; separate axes | Mart queryable; every row attributable; no combined "risk" column | 4 d |
| **4. Projections** | NCCIS 2021–2050 RCP4.5/8.5 for the same indicator; baseline/projection labelling enforced | Projection rows carry scenario, model, baseline; invariant I3 tested | 4 d |
| **5. Tools and API** | Typed tools over the mart, FastAPI endpoints, OpenAPI, contract and bounds tests | Contract tests pass; p95 mart query measured against N2 | 4 d |
| **6. Assistant** | OpenRouter adapter, 4–6 tools, abstention paths, citation rendering, cost and latency logging | Abstention works on the unanswerable set; no unsupported numerics in spot checks | 5 d |
| **7. Interface** | Streamlit: map, indicator explorer, chat with citations, report view | A user answers all six §3 questions unaided | 4 d |
| **8. Evaluation** | Benchmark, independent references, CI harness, failure analysis | N4–N9 measured and reported, including failures | 4 d |
| **9. AWS deployment** | Terraform, ECR, ECS, RDS, S3, Secrets, CloudWatch, migrations, backups | Deployed smoke test passes; parity confirmed; RPO/RTO documented; cost measured | 4 d |
| **10. Second hazard (optional)** | FIRMS or drought indicators, repeating the Phase 1 pattern | Same guarantees as Phase 1 | 3 d |

**Total: ~6–7 weeks solo.** Estimates are indicative and should be revised after Phase 1.

**Definition of done for any phase:** tests pass, the artifact is demonstrable, the catalogue/registry is updated, and the limitation is written down.

---

## 14. Operations

### 14.1 Observability

Structured JSON logs with request id, tool names, latency, tokens and cost. Metrics: request rate, p50/p95 latency, tool error rate, abstention rate, LLM cost per hour, ingestion duration, mart row counts. Alerts: latency above N1 for 15 min, error rate above 2%, cost above monthly budget, failed ingestion or mart build.

### 14.2 Security

- No secrets in the repository, images, or logs; `.env.example` lists variable names only; Secrets Manager in AWS.
- API key required for all non-local endpoints; per-key rate limit (token bucket, 429 with `Retry-After`).
- Read-only database role for the API; migrations run separately with elevated credentials.
- Aggregate public data only. No PII. Census small-cell suppression respected — enforce a minimum population threshold for any ward-level published statistic.
- Ingested text is untrusted: never treat file contents as instructions.
- Dependencies pinned and scanned; images pinned by digest.

### 14.3 Availability and recovery

Pilot target 99.5% during business hours. Single-AZ is accepted as a documented tradeoff: it saves cost at the price of a multi-hour outage risk. RPO 24 h (nightly snapshot), RTO 4 h (restore and redeploy from Terraform), both tested once before the demo.

### 14.4 Deployment

Identical image local and cloud (N14). Migrations as a pre-deploy ECS task. Rolling deployment with health-check gates; blue/green is unnecessary at this scale but the health gate is not. Rollback is redeploying the previous image digest. Terraform state in S3 with locking.

### 14.5 Cost

Indicative monthly pilot cost: RDS PostgreSQL/PostGIS (~$30–60), ECS Fargate (~$15–40), S3 and data transfer (single-digit dollars), CloudWatch (single-digit), LLM usage (under $5 at benchmark volumes). Total well inside N13. Confirm with the AWS pricing calculator before provisioning, and record actuals after one month.

---

## 15. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| GreenBook packages are not programmatically accessible | Loses the richest municipal context | Treat as context, not a computation dependency; verify in Phase 0–1 |
| Census 2022 not available at ward level in machine-readable form | Blocks vulnerability analysis; forces small-area or main-place fallback | Verify early; downscale honestly or report at a coarser level |
| Ward vintage mismatch (2021 vs 2026 boundaries) | Silently wrong joins | Explicit vintage + crosswalk; test that ward counts and codes reconcile |
| NCCIS projection files are large or awkwardly formatted | Extraction effort, storage | Subset at ingest; confirm download mechanics in Phase 3 planning |
| Grid cell resolution (ERA5 ~31 km) misrepresented as ward-level accuracy | Overstated precision in answers | Report sampling basis and cell count; phrase results as metro-scale constrained by ward geometry |
| ERA5 licence or rate limits obstruct automated re-download | Non-reproducible pipeline | Pin a retrieved copy with checksum; document the retrieval date |
| User trust collapses on a single wrong number | Project failure | Mart + envelope + abstention + benchmark; zero tolerance on N4 and N7 |

**Explicitly unverified at the time of writing:** whether each source can be downloaded by script, its licence terms, ward-level availability of census tables, the exact eThekwini ward count, and the MDB release vintage that pairs with Census 2022. Each is a Phase 1 acceptance test. None should be assumed in the design.

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
│   ├── adr/                         # 001..004, decisions and consequences
│   ├── data-catalogue.md
│   ├── methods.md                   # indicator registry
│   ├── limitations.md
│   └── archive/brief-v1.md
├── data/
│   ├── raw/         # immutable, git-ignored
│   ├── processed/   # git-ignored
│   ├── reference/   # small test fixtures, committed
│   └── catalogue/   # machine-readable dataset entries, committed
├── src/climate_resilience/
│   ├── ingestion/    # fetch, verify, catalogue
│   ├── canonical/    # CRS, geometry, temporal normalisation
│   ├── indicators/   # registered deterministic methods
│   ├── mart/         # build and query
│   ├── tools/        # typed analytical tools (single source of truth)
│   ├── api/          # FastAPI
│   ├── agent/        # OpenRouter adapter, prompts
│   ├── reporting/
│   └── evaluation/
├── tests/
│   ├── test_ingestion.py
│   ├── test_spatial.py
│   ├── test_indicators.py
│   ├── test_mart.py
│   ├── test_tools.py
│   ├── test_agent.py
│   └── test_reproducibility.py
├── eval/
│   ├── questions.json
│   ├── reference_answers.json
│   └── results/
└── infrastructure/aws/              # Terraform
```

---

## 17. Deliverables

1. **Working application** — natural-language interface plus analytical explorer, answering the six §3 questions.
2. **Local deployment** — `uv` + Docker Compose, one command.
3. **AWS deployment** — Terraform, containerised, documented, with health checks and measured cost.
4. **Data pipeline** — reproducible, checksummed, versioned, with catalogue entries and qualification results.
5. **Analytical tools** — indicator registry with methods, tests and reference values.
6. **Evaluation results** — benchmark, independent references, measured metrics, failure analysis.
7. **Documentation** — sources, licences, architecture, ADRs, methods, limitations.
8. **Demonstration** — walkthrough of real questions, computed outputs with citations, and an honest abstention.

---

## 18. Next actions

1. Review and approve this specification, especially the non-goals (§4.3) and the deferral of flood.
2. Run Phase 0: write ADR-001..004, scaffold the repository, get CI green.
3. Execute Phase 1 with one goal: prove that eThekwini's real data supports one indicator, end to end, with a complete evidence trail.

Everything else waits until that is true.
