# climate-resilience-ai

Climate Resilience Intelligence Platform — eThekwini pilot.

An analytical system, not a chatbot: every number is computed deterministically,
carries its provenance, and can be reproduced from a recorded manifest. A
language model may later explain those numbers; it may never calculate them.

**Status: agent built, not yet measured.** Heat, population exposure and flood
exposure end to end on real data, a validated ward boundary layer, a document
index holding the Durban Climate Action Plan, and a Pydantic AI agent that
queries both. The agent is tested offline; its latency, cost and retrieval
accuracy need an OpenRouter key and have not been measured. Vulnerability is
blocked on a bulk Census 2022 source. See
[`docs/limitations.md`](docs/limitations.md) before reading any result.

- Specification: [`climate-resilience.md`](climate-resilience.md)
- Agent and quality rules: [`AGENTS.md`](AGENTS.md)

## What works today

`hot_days_tmax_ge_35c` — days per calendar year with daily maximum temperature
at or above 35 °C — for 1980–2025, at ERA5 grid-cell level and as an
area-weighted municipal aggregate, with full provenance and a reproducibility
check. Only complete calendar years are published
([ADR-008](docs/adr/008-analysis-window-and-revisions.md)).

```
municipality       1980   0.000    2025   2.701
                  (area-weighted, derived)
```

This is a real heat signal, but it is **not** ward-level: the municipality spans
five 0.25° grid cells. Read `docs/limitations.md` first.

### Population exposure (Phase 3)

WorldPop 2020 (UN-adjusted, 1 km) clipped to eThekwini and allocated to the 110
ADM4 wards by each cell's area share.

```bash
uv run climate-resilience worldpop
uv run climate-resilience exposure
```

```
cells         : 3,654
population    : 3,766,001
resolution    : 1 km
exposure rows : 111 (110 wards + 1 municipality)
```

Exposure is not risk. These rows answer "where do people live" and carry
`hazard_type = none`; combining them with a hazard is a separate, explicit
calculation. The 100 m product is not used because the national file is 609 MB
and the server does not support range requests
([ADR-009](docs/adr/009-exposure-resolution-and-vulnerability-gap.md)).

### Flood exposure (Phase 4)

WRI Aqueduct Floods v2 baseline hazard maps — riverine and coastal, 10/50/100
year return periods — clipped to eThekwini and exposed against ward area and
WorldPop population.

```bash
uv run climate-resilience flood
uv run climate-resilience flood-exposure
```

```
cell-layers   : 21,258   (6 layers x 3,543 cells)
wet cells     : 316 riverine (10-yr), 317 (50/100-yr), 0 coastal
resolution    : 1 km raster from a 5' (~10 km) hydrological model
flood rows    : 1,320 (108 wards x 3 return periods x 2 mechanisms x 2 indicators,
                        + municipality, 6 scope-layers withheld)
```

| Riverine, 100-yr | Value |
|---|---|
| Municipal area exposed | 8.89% (227.3 km²) |
| Population in exposed cells | 405,832 (10.8%) |
| Most exposed ward | 83.6% |
| Median ward | 0.03% |

Three things must be read alongside those numbers:

- **Pluvial flooding is not modelled.** The April 2022 KZN mechanism is out of
  scope, and the caveat is attached to every flood row.
- **Coastal flooding is zero for eThekwini at every published return period**,
  and also at 2080 RCP8.5. The same raster floods Maputo Bay, so this is a model
  result, not a failed download.
- **The depth field is near-binary** — two values cover 99% of wet cells —
  because the hydrology is 10 km. This is modelled extent with coarse depth
  classes, not a continuous depth map ([ADR-010](docs/adr/010-flood-hazard-baseline-and-coastal-null.md)).

The ward pattern was checked against current literature. The most exposed wards
sit on the Umgeni/Springfield reach, the Umlazi–Isipingo–Umhlatuzana system and
the northern reaches near Tongaat — the same rivers JICA's 2025 Durban survey
and the Presidential Climate Commission's 2022 flood analysis name, and the
corridors where Springer (2025) places the highest-risk informal settlements.
That is a placement check, not a validation of magnitude.

### Assistant

One agent, two tool families: exact values from the mart, prose from the
documents. It never calculates — every number is a mart row, restated with its
envelope.

```bash
uv run climate-resilience ask "Which wards have the largest share of area exposed to a 100-year riverine flood?"
uv run climate-resilience ask "How many people are exposed to pluvial flooding in ward 75?"
```

The second returns without spending a token:

```
Pluvial (surface-water) flooding is not modelled. The platform covers riverine
and coastal flooding only; the April 2022 KwaZulu-Natal damage was largely
pluvial, and no open metro-scale dataset exists for it (I9).

missing:
  - a pluvial flood hazard layer

requests=0 tokens=0/0 guard=True
```

Three guarantees are structural, not prompt requests
([ADR-012](docs/adr/012-agent-budget-and-grounding.md)):

| Guarantee | Enforced by |
|---|---|
| ≤ 2 model calls, ≤ 3 tool calls | `UsageLimits`, raised by the runtime |
| Every number cited | `Answer` validator rejects an uncited answer |
| Flood answers carry the pluvial caveat | post-check appends it if the model omits it |

Tools: `get_indicator`, `rank_scopes`, `resolve_scope`, `coverage`, `explain`,
`search_documents`. Results are trimmed to ten rows so one question cannot pull
the whole mart into the prompt.

### Documents (RAG)

Prose goes in a vector index, measurements stay in the mart. The index holds
plans, strategies and dataset documentation; it never holds a climate value.

```bash
docker compose up -d db          # Postgres with PostGIS + pgvector
uv run climate-resilience documents
uv run climate-resilience search "sea level rise and coastal protection"
```

```
  durban-cap-2019                156 chunks  63ca783fe0cb
indexed       : 1 document(s)

durban-cap-2019 p.62 [municipality] Loss of ecosystem & biodiversity
  score 0.0323  dense=1 lexical=3
```

Three constraints are structural:

- **GreenBook is excluded.** CC BY-NC-SA 3.0 ZA is NonCommercial and
  ShareAlike, which a commercial derived index cannot honour. Recorded in
  `data/catalogue/documents.json`, never ingested
  ([ADR-011](docs/adr/011-rag-supporting-layer.md)).
- **A chunk is ward-scoped only if it names a ward.** The CAP names none, so
  all 156 chunks are municipal and a ward question returns municipal context
  labelled as such.
- **Retrieval is hybrid**: dense cosine plus Postgres full-text, fused by
  reciprocal rank. Dense finds paraphrase, lexical finds "RCP8.5" and ward
  numbers.

### Census ward population (Phase 3, not joined)

Census 2022 ward totals are ingested with their official codes: 111 eThekwini
wards, 4,239,901 persons. They are **not** joined to the 110 ADM4 polygons —
the ward counts differ — and the downloadable product contains population only,
with no service, tenure or employment variables. Vulnerability is withheld
rather than guessed.

### Ward boundary layer (Phase 2)

110 eThekwini wards ingested from geoBoundaries ADM4, validated and persisted
with an explicit ward → municipality crosswalk.

```bash
uv run climate-resilience wards
```

```
wards         : 110
ward area     : 2,556.6 km²
municipality  : 2,556.6 km²
difference    : +0.0 km²
repaired      : 0
spot checks: durban_cbd -> eThekwini 028, umhlanga -> 035, pinetown -> 018,
             chatsworth -> 073, kwamashu -> 042, pietermaritzburg -> None
```

Gates before anything is persisted: geometry validity (with repair counted),
containment inside the municipality, area reconciliation against the
municipal polygon, pairwise overlap detection, expected ward count, and point
spot checks including one point that must fall outside. Any error aborts the
run instead of writing a partial layer.

**Ward geometry does not mean ward-level heat.** Five 0.25° cells cannot
distinguish 110 wards; aggregating heat now would publish 110 copies of 5
values. Population exposure is built separately from WorldPop (Phase 3), which
does resolve ward differences; heat remains a grid-level product.

## Quick start

```bash
uv sync --all-groups

make data      # acquire every source, then build the mart (one command)
make verify    # catalogue + artifact checksums + independent recount
```

`make data` downloads into `data/raw`, builds `data/processed`, and writes the
mart. Stages reuse cached raw inputs, so a second run does no network I/O.

Individual stages remain available when you are debugging one of them:

```bash
uv run climate-resilience boundaries   # municipal polygon
uv run climate-resilience wards        # 110 ward polygons, validated + crosswalk
uv run climate-resilience climate      # ERA5-derived daily Tmax
uv run climate-resilience worldpop     # WorldPop 1 km clipped to eThekwini
uv run climate-resilience census       # Census 2022 ward population (not joined)
uv run climate-resilience flood        # Aqueduct baseline layers, clipped
uv run climate-resilience documents    # chunk + index catalogue documents
uv run climate-resilience mart         # heat rows + manifest + snapshot
uv run climate-resilience exposure     # population exposure rows
uv run climate-resilience flood-exposure  # flood rows
uv run climate-resilience show --scope-level municipality --limit 10
```

No network? `make data-offline` verifies the cached artifacts against their
catalogue checksums and performs no fetch.

Run `uv run climate-resilience --help` for all commands.

## One command, and what it promises

`make data` runs `boundaries → wards → climate → worldpop → flood → census →
mart` in dependency order. Each source is isolated: a blocked optional source is recorded
as `skipped`, while a failure in a source marked `required` in the catalogue
exits non-zero and skips the build.

Every run writes `data/manifests/data-<run_id>.json`:

```
  ok   geoboundaries_zaf_adm2   eThekwini: 2,556.6 km², vintage 2020
  ok   geoboundaries_zaf_adm4   110 wards, 110 crosswalk rows, 0 repaired
  ok   era5_openmeteo           84,010 rows across 5 cells, 1980-01-01..2025-12-31
  ok   worldpop                 3,654 cells, 3,766,001 persons, WorldPop 2020 1 km
  ok   aqueduct_floods          21,258 cell-layers, 6 layers, 950 wet cell-layers
  ok   census_2022_ward_population 111 wards, 4,239,901 persons; not joined
  ok   mart build               1,707 mart rows
```

After each stage the declared artifact is hashed and compared with the
catalogue, so "the step ran" and "the expected file is on disk" are separate
claims. The mart reads its climate and population inputs through recorded
pointers (`data/processed/<dataset>/latest.json`), never by sorting directory
names.

## Quality gates

```bash
uv run ruff check .
uv run pytest
make verify          # catalogue checksums + independent recount
make data-offline    # no-network cache check
```

CI runs lint, tests and catalogue validation. Live downloads are run manually
because they depend on external services; their manifests are the evidence.
The acquisition orchestration itself is tested with fake runners, so a broken
stage order or failure policy fails CI without a 150 MB download.

## How it is built

| Layer | Purpose |
|---|---|
| `acquire.py` | One-command acquisition: order, isolation, required/optional |
| `ingestion/` | One adapter per source, each declaring licence and vintage |
| `spatial.py` | CRS policy: store EPSG:4326, compute in EPSG:32736 |
| `spatial_validation.py` | Boundary gates: validity, containment, overlap, area |
| `crosswalk.py` | Explicit ward → municipality mapping with vintage |
| `spot_checks.py` | Known-point placement checks, including one that must miss |
| `indicators/` | Registered, versioned, deterministic definitions |
| `exposure.py` | WorldPop → ward and municipality population, separate from hazard |
| `flood.py` | Aqueduct → ward and municipality flood exposure, per mechanism |
| `indicators/flood.py` | Area-fraction and population-in-zone maths, pluvial refused |
| `tools/mart_tools.py` | Five read-only tools over the mart; evidence or typed refusal |
| `rag/` | Document catalogue, Docling chunking, pgvector store, hybrid retrieval |
| `assistant/agent.py` | Pydantic AI agent, budget, tool registration, caveat post-check |
| `assistant/guard.py` | Pre-flight refusal for pluvial and unmeasured questions |
| `mart/` | Precomputed rows carrying evidence envelopes |
| `envelope.py` | The contract that makes traceability enforceable |
| `manifest.py` | Input/output hashing and run records |

Seven decisions shape everything else, and each has an ADR:

1. **Precompute into a mart** ([ADR-001](docs/adr/001-precomputed-indicator-mart.md)) —
   no raster work at request time.
2. **Every number is an evidence envelope**
   ([ADR-002](docs/adr/002-evidence-envelope.md)) — citation and abstention fall
   out of the data model.
3. **Failed data gates are recorded, not worked around**
   ([ADR-006](docs/adr/006-phase1-source-substitution.md)).
4. **One command acquires, and sources fail independently**
   ([ADR-007](docs/adr/007-one-command-acquisition.md)) — a blocked source is
   reported, not silently dropped or allowed to abort the run.
5. **The analysis window ends at the last complete calendar year**
   ([ADR-008](docs/adr/008-analysis-window-and-revisions.md)) — a partial year
   is withheld, never labelled as a full one.
6. **Exposure is published at 1 km; vulnerability is withheld**
   ([ADR-009](docs/adr/009-exposure-resolution-and-vulnerability-gap.md)) — the
   100 m surface cannot be subset, and census ward indicators are not a bulk
   product. A gap is reported, not filled with a guess.
7. **Flood is baseline-only, at any inundation depth, with coastal published as
   a verified zero** ([ADR-010](docs/adr/010-flood-hazard-baseline-and-coastal-null.md))
   — no cell reaches 0.5 m, so the default threshold would publish a column of
   zeros; and the 2080 layers confound climate change with a change of forcing
   dataset.

## Reproducibility

Two builds from the same inputs produce the same `content_hash`:

```bash
uv run climate-resilience mart | grep content_hash
uv run climate-resilience mart | grep content_hash   # identical
```

The hash excludes `run_id` and `created_at` — run identity, not content. Every
build writes `data/manifests/build_mart-<run_id>.json` with input and output
checksums, package versions and the git commit.

## Data

Five datasets are active: geoBoundaries ZAF ADM2 (municipalities), geoBoundaries
ZAF ADM4 (wards), ERA5 via Open-Meteo, WorldPop 2020 1 km, and Aqueduct Floods
v2 baseline. The first three are **labelled substitutions** for the intended
sources, because the MDB site was unreachable and no CDS credentials exist. The
`mdb_wards` entry stays `blocked` rather than being deleted, so the substitution
is visible in the catalogue. Details, gates and gaps:
[`docs/data-catalogue.md`](docs/data-catalogue.md).

Raw and derived data are git-ignored. The catalogue and manifests are the
committed record.

## Not built yet

Ward-level heat (blocked by 5-cell climate resolution, not by code),
vulnerability, projections, fire, the tool layer, the assistant, PDF reports and
the AWS deployment. Specified in `climate-resilience.md`; nothing here should be
read as claiming otherwise.

Flood projections are deliberately not built: the 2080 layers are forced by GCMs
while the baseline uses WATCH, so the difference is not a clean climate signal
([ADR-010](docs/adr/010-flood-hazard-baseline-and-coastal-null.md)).
