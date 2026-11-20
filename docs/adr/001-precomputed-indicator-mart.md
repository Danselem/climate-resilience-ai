# ADR-001 — Precompute indicators into a mart; never touch rasters at request time

**Status:** accepted

## Context

An answer must be fast and stable. Computing a gridded indicator against a
geometry at question time costs tens of seconds and produces a number that can
silently change when the source is re-downloaded. Both are fatal for a
decision-support tool.

## Decision

All published metrics are precomputed into `indicator_value`, keyed by
indicator × method version × scope × period × hazard parameters × dataset
version. The API and the assistant read only this table. Rebuilding is an
explicit, manifested batch job.

## Consequences

- Query latency is milliseconds; the dominant cost becomes LLM inference.
- Two questions asked a month apart return the same number unless a rebuild
  occurred, and a rebuild is attributable to a specific run and input hash.
- Data is stale between rebuilds. Mitigated by recording `run_id` and dataset
  version on every row, not by caching.
- The mart schema is a public contract: adding a hazard parameter means a
  migration, not a code change.
