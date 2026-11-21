# climate-resilience-ai

Climate Resilience Intelligence Platform — eThekwini pilot.

An analytical system, not a chatbot: every number is computed deterministically,
carries its provenance, and can be reproduced from a recorded manifest. A
language model may later explain those numbers; it may never calculate them.

**Status: measured.** Heat, population exposure and flood exposure end to end on
real data, a validated ward boundary layer, a document index holding the Durban
Climate Action Plan, and a Pydantic AI agent that queries both. The agent is
scored against a 48-item gold set and retrieval against 99 labelled passages:
48/48 answers, p95 2.9 s, $0.00017 per question, but **Recall@5 of 0.57** — a
little under half the passages that answer a document question are still missing
from the top five.
Vulnerability is blocked on a bulk Census 2022 source. See
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
| ≤ 4 model calls, ≤ 5 tool calls | `UsageLimits`; measured worst case, not a target |
| Every number cited | citations are derived from the evidence, never transcribed |
| No answer without evidence | an uncited answer is converted to a refusal in code |
| Flood answers carry the pluvial caveat | post-check appends it if the model omits it |
| An answer cannot contradict its own evidence | "no flood risk" beside a positive exposure value is refused |

Tools: `get_indicator`, `rank_scopes`, `coverage`, `explain`,
`search_documents`. Results are trimmed to five rows so one question cannot pull
the whole mart into the prompt. `resolve_scope` is deliberately not a tool: the
model used it to re-resolve names it had already been given, five calls at a
time, and scope resolution now happens inside the analytical tools.

Models are a fallback chain, because free endpoints rate-limit without notice:

```
LLM_MODELS=amazon/nova-micro-v1,particle-ai/particle-1:free
```

**Measured on `amazon/nova-micro-v1` in a warm process, 20 Nov 2026:**

| Question | Requests | Latency | Tokens in/out | Cost |
|---|---|---|---|---|
| 100-year riverine exposure by ward | 2 | **3.83 s** | 5,346 / 126 | $0.00021 |
| Population in flood-exposed areas | 2 | **2.06 s** | 5,370 / 83 | $0.00020 |
| Hot days in eThekwini, 2025 | 2 | **1.80 s** | 5,223 / 93 | $0.00020 |
| What the CAP says about sea level rise | 2 | **3.20 s** | — | $0.00019 |
| Water and sanitation in the CAP | 2 | **1.59 s** | 3,858 / 65 | $0.00014 |
| 2050 dry-spell projection (refused) | 0 | 0.0 s | 0 / 0 | $0 |

Median **2.9 s**, mean **$0.00019** per question — inside the 6 s p95 and
40× inside the $0.004 budget. Cold-start document questions add ~8 s for the
embedding model, which a long-running process pays once.

Getting there required four changes, all measured rather than assumed:
deduplicating per-row warnings (37% of the prompt), capping rows at five,
capping output, and deriving citations from the evidence instead of asking the
model to transcribe row keys — which had been causing a retry on almost every
answer.

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

### API

The same typed tools, over HTTP. `uv run climate-resilience serve` (or `make api`)
serves an OpenAPI document at `/docs`.

```bash
curl "localhost:8000/indicators/hot_days_tmax_ge_35c?scope_id=ethekwini&period_year=2025"
curl "localhost:8000/rank?indicator_id=flood_exposed_area_pct&mechanism=riverine&return_period_years=100&limit=5"
curl "localhost:8000/scopes?q=Durban"
curl -X POST localhost:8000/ask -H 'content-type: application/json' \
     -d '{"question":"How many people are exposed to the 100-year riverine flood?"}'
```

| Route | Returns |
|---|---|
| `GET /health` | mart row count, document index presence |
| `GET /coverage` | indicators, periods, mechanisms, return periods that exist |
| `GET /scopes?q=` | a published scope id from "ward 75", "Durban", `ethekwini-075` |
| `GET /indicators/{id}` | envelopes for one indicator |
| `GET /rank` | wards or municipality ranked by one indicator |
| `GET /rows/{row_key}` | full provenance for one published row |
| `GET /documents/search` | passages from municipal plans |
| `POST /ask` | assistant answer, citations, cost and latency |

Two contract decisions matter more than the routes:

- **A missing value is `200` with `status: insufficient`**, not a 404 or a zero.
  A client cannot mistake "we do not publish this" for "the value is 0".
- **A malformed parameter is `422` before any tool runs** — `return_period_years`
  is restricted to 10, 50 or 100, and the message says so.

Flood values without a mechanism return both rows, each labelled. There is no
combined total to ask for.

**Mart latency (N2, p95 ≤ 1 s), measured with `make bench`:**

```
get_indicator  p50 0.92 ms   p95 1.98 ms
rank_scopes    p50 2.07 ms   p95 2.84 ms
explain        p50 0.32 ms   p95 0.54 ms
```

Set `CRP_API_KEY` to require `X-API-Key` on every route except `/health`. Unset
means local use.

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

## Evaluation

Two numbers, measured separately, because they fail for different reasons.

```bash
uv run climate-resilience eval-assistant          # answers + retrieval
uv run climate-resilience eval-assistant --no-retrieval
```

### Answers

48 questions in four categories, decided mechanically — nothing is judged by
reading the prose.

| Category | Passes when |
|---|---|
| analytical | the expected mart row is among the citations, located by SQL from its published parameters |
| document | a chunk of the expected document was retrieved and cited |
| abstain | the answer refused and named the missing input |
| adversarial | refused, or answered with evidence and no forbidden strings |

```
items         : 48
passed        : 48 (100%)
  abstain      12/12
  adversarial  8/8
  analytical   20/20
  document     8/8
latency p50/95: 1.64s / 2.99s
cost          : mean $0.00017
```

Both targets hold with margin: p95 3.0 s against 6 s, $0.00017 against $0.0040.

Getting from 42/48 to 48/48 was not tuning. Three defects were behind every
failure, and each was reproduced before it was fixed:

- **Temperature was unset.** The same 48 items scored 75–94% across runs. Pinned
  at 0, they produce the same result twice. The variance had been hiding which
  failures were real.
- **A deterministic tool loop.** nova-micro emitted the *identical* `rank_scopes`
  call seven times, each returning five successful rows, and never concluded —
  with temperature 0 the prompt never changed, so the loop could not break.
  Both `rank_scopes` and `search_documents` now say the result is final and name
  themselves: "do not call rank_scopes again with the same arguments". A softer
  wording was tested and ignored.
- **A measurement-intent gap.** "How has annual rainfall changed since 1980" did
  not look like a measurement question, so it reached the model, which answered
  it with hot-day counts. Change-along-a-series phrasing now triggers the
  existing refusal for unpublished rainfall.

### Retrieval

23 questions, 99 labelled passages, scored with `hybrid_search` alone — no
model, no tool selection. Labels were written from the document text before any
retrieval was run, so they describe the corpus rather than the retriever.

```
retrieval     : 23 labelled questions
  recall@5    : 0.57
  recall@10   : 0.734
  mrr         : 0.887
  ndcg@5      : 0.62
  weakest     : cap-sea-level (0.131), cap-city-profile (0.151), cap-biodiversity (0.339)
```

When retrieval finds a relevant passage it is almost always first (MRR 0.89),
but **43% of the passages that answer a question are still absent from the top
five**. Three defects were behind the first measurement, and fixing them took
the numbers from 0.50/0.78/0.54 to 0.57/0.89/0.62:

- **The chunks did not fit the model.** Chunking was set to 512 tokens and
  `all-MiniLM-L6-v2` reads 256, so 36% of chunks were embedded with their second
  half silently discarded. Switching to `bge-base-en-v1.5` (512-token window)
  made the existing chunks valid — and because chunk ids are content hashes, the
  labels survived.
- **The lexical query asked for a conjunction**, so "what does the plan say
  about sea level rise" required a chunk containing every word. OR-ed content
  words, and headings now indexed: lexical Recall@5 0.047 → 0.383.
- **Equal fusion weight was expensive**, because the two arms are not equally
  good. Sweeping it showed 1.0/0.1 beats 1.0/1.0 by 7 points of Recall@5 and 11
  of nDCG.

The labels are single-annotator and conservative, and the fusion weight was
chosen on the same questions it is reported against, so these are optimistic.
What remains is corpus-shaped: repeated section headings, near-duplicate "Now
and the future" sections, and multi-row action tables that chunk badly.

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
vulnerability, projections, fire, PDF reports, the FastAPI endpoints, the
Streamlit interface and the AWS deployment. Specified in
`climate-resilience.md`; nothing here should be read as claiming otherwise.

Flood projections are deliberately not built: the 2080 layers are forced by GCMs
while the baseline uses WATCH, so the difference is not a clean climate signal
([ADR-010](docs/adr/010-flood-hazard-baseline-and-coastal-null.md)).
