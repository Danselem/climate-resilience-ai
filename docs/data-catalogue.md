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
| `known_gaps` | Stated limitations, not a wish list |

## Qualification gates

No dataset becomes `active` until access, licence, coverage, format, CRS,
units, identifiers, vintage and size have all been checked. A failed gate is
recorded as `blocked` with the reason — for example `mdb_wards`, which was
unreachable and remains blocked rather than quietly replaced.

## Status at Phase 2

| Status | Datasets |
|---|---|
| active | `geoboundaries_zaf_adm2`, `geoboundaries_zaf_adm4`, `era5_openmeteo` |
| blocked | `mdb_wards` |
| not_implemented | `cds_era5` |
| planned | `census_2022`, `worldpop`, `aqueduct_floods`, `nccis_projections`, `firms` |
| context_only | `greenbook` |

`mdb_wards` stays `blocked` even though ward geometry now exists: the entry
records the authoritative source, and `geoboundaries_zaf_adm4` records what is
actually in use. Keeping both makes the substitution visible rather than
letting the blocked entry quietly disappear.
