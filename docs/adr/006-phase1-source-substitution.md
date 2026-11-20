# ADR-006 — Phase 1 substitutes Open-Meteo for CDS and geoBoundaries for MDB

**Status:** accepted (temporary; revisit triggers below)

## Context

Phase 1 requires one indicator computed end to end from real data with a
complete evidence trail. Two intended sources were unavailable in the build
environment:

- `demarcation.org.za` (MDB) timed out — no ward or municipal polygons.
- Copernicus CDS requires an account and licence acceptance — no credentials.

The alternatives were to stop, to fabricate data, or to use real substitute
sources and label them precisely.

## Decision

Use real substitutes, label the substitution everywhere it matters, and make
the gap visible in code:

- **Boundaries:** geoBoundaries ZAF ADM2 (CC BY 3.0 IGO, itself derived from MDB
  data) for the municipal polygon, and geoBoundaries ZAF ADM4 for wards
  (110 features for eThekwini, same redistribution lineage). Ward numbers are
  parsed from the feature name because the release carries no official codes;
  that provenance is stored on every ward row. The MDB adapter remains declared:
  `require_mdb_wards()` raises until the authoritative release is ingested.
- **Temperature:** Open-Meteo archive (CC BY 4.0, ERA5-derived daily aggregates)
  rather than the CDS product. The CDS adapter exists as a declared contract
  that raises `NotImplementedError`.
- Provenance is recorded in `data/catalogue/datasets.json`, in every envelope's
  `datasets` list, in `quality.warnings`, and in `docs/limitations.md`.

## Consequences

- Phase 1 was exercised on real climate data for the real eThekwini boundary,
  and its numbers are checkable against an independent recount.
- Two datasets are labelled as secondary distributions. Anyone reading a number
  can see that, which is the point. A third (`geoboundaries_zaf_adm4`) carries
  the same label for ward geometry.
- Swapping either source is a configuration and adapter change, not a rewrite,
  because both adapters emit the same canonical table.

## Revisit triggers

- CDS credentials available → implement `ingestion/cds_era5.py`, re-run, and
  compare cell values against the Open-Meteo extract (a free validation).
- MDB reachable → ingest wards, reconcile the ADM4 vintage, and unblock the
  `mdb_wards` catalogue entry before publishing any ward-level number.
