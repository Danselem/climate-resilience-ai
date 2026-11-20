# ADR-008 — The analysis window ends at the last complete calendar year

**Status:** accepted

## Context

Phase 1 pinned `history_end = 2024-12-31` while scaffolding. By November 2026
that default was 23 months out of date, and nothing in the code said why it
existed. It looked like a limit of the source. It was not: the Open-Meteo
archive served every day through the request date, and the fetch simply stopped
asking after 2024.

Two separate defects sat behind the stale date.

- **Coverage was being used as a proxy for completeness.** The publication gate
  accepted a year with at least 90% of its days present. A series that stopped
  on 25 November had 329 of 365 days — 90.1% — and would have passed, then been
  labelled `period_start = 1 January, period_end = 31 December`. The period end
  was hard-coded, so nothing contradicted the label.
- **A "current" window is not a stable window.** The source is a secondary
  distribution of ERA5. Its most recent two to three months are preliminary
  ERA5T and can be revised without notice. A window ending "today" can change
  its numbers without any change to code, inputs or methodology.

## Decision

- **`history_end` is unset by default** and resolves to the last complete
  calendar year at fetch time (`resolve_history_end`). Fetching in January
  therefore extends the window by one year without editing configuration.
- **The resolved value is pinned in the record.** It becomes part of the
  dataset version (`archive-1980-01-01_2025-12-31`), the artifact path, the
  catalogue entry and the run manifest. A dynamic default still produces a
  reproducible run; the next January produces a new version, not a mutated one.
- **A year is published only if it is complete** — observations span 1 January
  to 31 December — **and** meets `min_coverage`. Completeness is derived from
  the data, not assumed from the configuration.
- **`CRP_HISTORY_END` remains an escape hatch** for pinning a specific window,
  including a partial one, when a deliberate test requires it. Any year that is
  not complete is withheld rather than mislabelled.
- **The window does not include the current year.** Year-to-date would be a
  different indicator with its own period and label, not a flag on this one.

1980 is a chosen baseline, not a data limit; ERA5 reaches back to 1940. Forty-six
complete years are enough to show a signal and short enough to fetch cheaply.

## Consequences

- The published range is 1980–2025: 84,010 daily cell readings, 46 complete
  years, 276 mart rows (230 cell-year + 46 municipality-year). Extending to 2025
  added rows; it did not change any 1980–2024 value, which was checked directly
  before the build was accepted.
- Re-publishing the same window reproduces the same `content_hash`. Extending
  the window changes it, because the row set changed — that is the intended
  meaning of the hash.
- Leaving the provisional ERA5T tail out costs freshness. This is deliberate:
  the project prefers a number that will not move to a number that is three
  months newer.
- A re-fetch inside the revision window of the final year could still change its
  values. The catalogue retrieval date and the artifact checksum make that
  visible; they do not prevent it.
- Any future "latest conditions" product must be a separate indicator with
  explicit preliminary labelling and its own provenance, not a widened default.

## Revisit triggers

- A consumer needs sub-annual or year-to-date information: add an indicator
  whose period is the observation window and whose label says so.
- The provider exposes the ERA5T-to-ERA5 transition date, or a finalised-ERA5
  endpoint: the window could then extend to the latest *final* month instead of
  the last complete year.
- A source with a different latency or revision policy replaces this one: the
  rule becomes "last settled period for *that* source", recorded per dataset.
