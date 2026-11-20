# Data catalogue

The machine-readable catalogue is [`data/catalogue/datasets.json`](../data/catalogue/datasets.json).
It is the authoritative record of what was actually obtained, and a test
(`tests/test_catalogue.py`) fails if it becomes incoherent.

## Why it is machine-readable

A prose catalogue drifts. A validated one cannot: an `active` dataset must carry
a licence, a checksum, a retrieval date and an explicit list of known gaps. If
that is not true, CI fails.

## Fields

| Field | Meaning |
|---|---|
| `id` | Stable identifier used in envelopes and tool arguments |
| `role` | Why the dataset is in the system — context, hazard, exposure, vulnerability, validation |
| `basis` | `observation`, `reanalysis`, `projection`, `modelled_estimate`, `derived` |
| `licence` | Redistribution and derived-use terms |
| `version`, `checksum` | What exactly was used; a changed checksum is a changed input |
| `units`, `crs`, `native_resolution` | Required before any join is permitted |
| `spatial_coverage`, `temporal_coverage`, `time_basis` | What the data does and does not cover |
| `status` | `active`, `blocked`, `not_implemented`, `planned`, `context_only` |
| `artifact` | Path to the acquired file, relative to the data directory |
| `required` | `true` when a published indicator cannot be produced without it |
| `known_gaps` | Stated limitations, not a wish list |

`checksum` is the sha256 of `artifact`, so `make verify` can compare what is on
disk with what the catalogue claims. An evidence envelope may pin a different
scope for the same dataset — climate envelopes pin the combined raw payload
checksum, for example — and that is recorded per row rather than assumed.

## Acquisition

`make data` reads this catalogue and runs every dataset that has an adapter, in
dependency order. A `required` dataset that fails exits non-zero; an optional
one is recorded as `skipped`. Each run writes
`data/manifests/data-<run_id>.json` with per-source status, artifact and
checksum. `make data-offline` checks the cache with no network access.

A dataset whose adapter does not exist yet cannot be acquired, and a `required`
one fails the run rather than disappearing quietly. That is deliberate: a
requirement that is not implemented should be a visible failure, not a gap.

## Qualification gates

No dataset becomes `active` until access, licence, coverage, format, CRS,
units, identifiers, vintage and size have all been checked. A failed gate is
recorded as `blocked` with the reason — for example `mdb_wards`, which was
unreachable and remains blocked rather than quietly replaced.

## Status at Phase 3

| Status | Datasets |
|---|---|
| active | `geoboundaries_zaf_adm2`, `geoboundaries_zaf_adm4`, `era5_openmeteo`, `worldpop`, `census_2022_ward_population` |
| blocked | `mdb_wards`, `census_2022` |
| not_implemented | `cds_era5` |
| planned | `aqueduct_floods`, `nccis_projections`, `firms` |
| context_only | `greenbook` |

`mdb_wards` stays `blocked` even though ward geometry now exists: the entry
records the authoritative source, and `geoboundaries_zaf_adm4` records what is
actually in use. Keeping both makes the substitution visible rather than
letting the blocked entry quietly disappear.

`census_2022` is split in two deliberately. The full census is `blocked`:
socio-economic indicators are published only through interactive tools, and
there is no bulk ward table. `census_2022_ward_population` is `active` because
the population-only ward product is downloadable and validated — but it is not
joined to geometry (111 census wards against 110 ADM4 polygons) and no
published indicator depends on it. `worldpop` is active at 1 km, not the 100 m
product the specification names, because the 100 m national file cannot be
subset ([ADR-009](adr/009-exposure-resolution-and-vulnerability-gap.md)).
