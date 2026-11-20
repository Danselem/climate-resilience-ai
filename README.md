# climate-resilience-ai

Climate Resilience Intelligence Platform — eThekwini pilot.

An analytical system, not a chatbot: every number is computed deterministically,
carries its provenance, and can be reproduced from a recorded manifest. A
language model may later explain those numbers; it may never calculate them.

**Status: Phase 2 complete.** One indicator end to end on real data, plus a
validated ward boundary layer and crosswalk. See
[`docs/limitations.md`](docs/limitations.md) before reading any result.

- Specification: [`climate-resilience.md`](climate-resilience.md)
- Agent and quality rules: [`AGENTS.md`](AGENTS.md)

## What works today

`hot_days_tmax_ge_35c` — days per calendar year with daily maximum temperature
at or above 35 °C — for 1980–2024, at ERA5 grid-cell level and as an
area-weighted municipal aggregate, with full provenance and a reproducibility
check.

```
municipality       1980   0.000    2024   2.347
                  (area-weighted, derived)
```

This is a real heat signal, but it is **not** ward-level: the municipality spans
five 0.25° grid cells. Read `docs/limitations.md` first.

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

**Ward geometry does not mean ward-level indicators.** Five 0.25° cells cannot
distinguish 110 wards; aggregating now would publish 110 copies of 5 values.
That is the next phase's problem, and it is a data-resolution problem, not a
code problem.

## Quick start

```bash
uv sync --all-groups

uv run climate-resilience boundaries   # municipal polygon -> data/raw, data/processed
uv run climate-resilience wards        # 110 ward polygons, validated + crosswalk
uv run climate-resilience climate      # ERA5-derived daily Tmax for intersecting cells
uv run climate-resilience mart         # build indicator rows + manifest + snapshot
uv run climate-resilience show --scope-level municipality --limit 10

uv run python scripts/independent_check.py   # independent recount of every cell-year
```

Or `make boundaries wards climate mart verify`.

Run `uv run climate-resilience --help` for all commands.

## Quality gates

```bash
uv run ruff check .
uv run pytest
uv run climate-resilience catalogue
```

CI runs lint, tests and catalogue validation. Live downloads are run manually
because they depend on external services; their manifests are the evidence.

## How it is built

| Layer | Purpose |
|---|---|
| `ingestion/` | One adapter per source, each declaring licence and vintage |
| `spatial.py` | CRS policy: store EPSG:4326, compute in EPSG:32736 |
| `spatial_validation.py` | Boundary gates: validity, containment, overlap, area |
| `crosswalk.py` | Explicit ward → municipality mapping with vintage |
| `spot_checks.py` | Known-point placement checks, including one that must miss |
| `indicators/` | Registered, versioned, deterministic definitions |
| `mart/` | Precomputed rows carrying evidence envelopes |
| `envelope.py` | The contract that makes traceability enforceable |
| `manifest.py` | Input/output hashing and run records |

Three decisions shape everything else, and each has an ADR:

1. **Precompute into a mart** ([ADR-001](docs/adr/001-precomputed-indicator-mart.md)) —
   no raster work at request time.
2. **Every number is an evidence envelope**
   ([ADR-002](docs/adr/002-evidence-envelope.md)) — citation and abstention fall
   out of the data model.
3. **Failed data gates are recorded, not worked around**
   ([ADR-006](docs/adr/006-phase1-source-substitution.md)).

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

Three datasets are active: geoBoundaries ZAF ADM2 (municipalities), geoBoundaries
ZAF ADM4 (wards) and ERA5 via Open-Meteo, all CC BY 3.0 IGO / CC BY 4.0. All are
**labelled substitutions** for the intended sources, because the MDB site was
unreachable and no CDS credentials exist. The `mdb_wards` entry stays `blocked`
rather than being deleted, so the substitution is visible in the catalogue.
Details, gates and gaps: [`docs/data-catalogue.md`](docs/data-catalogue.md).

Raw and derived data are git-ignored. The catalogue and manifests are the
committed record.

## Not built yet

Ward-level indicators (blocked by 5-cell climate resolution, not by code),
exposure, vulnerability, projections, flood, fire, tools, assistant, PDF
reports, AWS deployment. Specified in `climate-resilience.md`; nothing here
should be read as claiming otherwise.
