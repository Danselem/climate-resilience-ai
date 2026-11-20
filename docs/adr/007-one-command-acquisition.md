# ADR-007 — One command acquires and builds; sources fail independently

**Status:** accepted

## Context

The specification requires the walking skeleton to reproduce "from one command"
and the pipeline to ingest its pilot datasets reproducibly. In practice the
project had five separate commands and an ordering that existed only in the
README. Phase 3 adds three more sources (WorldPop, Aqueduct, Census), each with
its own licence, subsetting rule and failure mode. A sequence that a human must
remember does not survive that growth.

Two facts make the naive answer wrong:

- **Sources fail unevenly.** The MDB site times out; CDS needs credentials that
  may not exist; a download can be throttled. Aborting the whole run on any
  failure makes the command unusable. Skipping silently is the dishonesty this
  project exists to avoid.
- **Stages already cache.** Each adapter reuses its raw payloads and hashes
  them. The missing piece was orchestration and a status record, not a download
  engine.

## Decision

`climate-resilience data` acquires every catalogued source in dependency order,
builds the mart, and always writes `data/manifests/data-<run_id>.json` with one
entry per source: status, detail, artifact path, sha256, duration.

- **Order comes from the code, membership from the catalogue**
  (`STAGE_BY_DATASET`, `STAGE_ORDER` in `acquire.py`). A stage runs only if its
  dataset is catalogued.
- **`required` is a catalogue field.** A required source that fails exits
  non-zero and skips the build; an optional one is recorded as `skipped` with
  its reason. A required dataset with no adapter fails rather than vanishing.
- **Checksums are verified, not assumed.** After a stage finishes, its declared
  artifact is hashed and compared with the catalogue. A stage that "succeeded"
  but produced an unexpected file is a failure.
- **Offline mode** (`--offline`) performs no network access: it verifies cached
  artifacts against the catalogue and skips the build. This is what makes the
  orchestration testable in CI and usable without connectivity.
- **`make data`** wraps it; `make data-offline`, `make verify` and `make all`
  cover the cache, the checks and the whole thing.
- **The mart resolves its climate input through a pointer**
  (`data/processed/era5_openmeteo/latest.json`), not by sorting directory names.
  The pointer records the version and the artifact hash, so a rewritten parquet
  is detected instead of silently consumed.

Make targets stay `.PHONY` and the stages stay idempotent. File-based Make
dependencies were rejected because artifact paths embed dataset versions that
change per release; staleness here is pinned by checksum, not modification time.
Modelling that in Make would require generated rules per version, which is more
machinery than the problem justifies.

## Consequences

- A blocked optional source degrades the run instead of breaking it, and the
  report says which sources are missing. The exit code still tells a script
  whether the published indicator is intact.
- Adding a source is a catalogue entry, an adapter and one line in
  `STAGE_BY_DATASET` — not Makefile surgery.
- The fetch report is its own schema rather than a `RunManifest`, because
  per-source status has no place in the stage manifest contract. Both record
  `run_id` and `git_commit`, so a build can be tied to the acquisition that fed
  it.
- `make data` re-runs stages whose raw inputs are already cached. That costs a
  few seconds of parsing and no bandwidth. If measured cost ever justifies
  skipping, that is a caching change inside an adapter, not a Make rule.
- CI cannot download. It exercises the orchestration with fake runners and
  fixtures, and `make data-offline` guards the checksum path.

## Revisit triggers

- More than roughly eight sources, or a need to refresh only one source: add
  explicit dependency edges and per-source selection to the catalogue instead of
  extending the static order.
- A source with a genuine incremental update (e.g. WorldPop annual releases):
  that adapter needs its own version resolution, and the pointer pattern used
  for climate is the model to follow.
