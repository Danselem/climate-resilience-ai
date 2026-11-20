# Limitations — Phases 1–2

Recorded at the end of Phase 2. Anything here is a known, deliberate gap, not
an oversight. A limitation that changes an output is also recorded in that
output's `quality.warnings`.

## Spatial

- **Wards are a redistribution, not the MDB release.** `demarcation.org.za` timed
  out from the build environment, so wards come from geoBoundaries ADM4
  (CC BY 3.0 IGO), itself derived from MDB data. The layer is internally sound —
  110 wards, 0 repairs, ward areas summing to the municipality area within
  0.0 km² — but it has not been reconciled against an independent ward list.
- **Ward codes are parsed, not authoritative.** The source carries
  `eThekwini 001` rather than an official ward code. `ward_number` is extracted
  from that name and flagged as such in the stored feature properties. Any join
  to Census 2022 must use the crosswalk, not the number.
- **Vintage mismatch risk.** Wards are 2020 vintage; Census 2022 ward geography
  may differ. The crosswalk to census geography does not yet exist, so no census
  join is permitted.
- **Municipal boundary vintage is also 2020** and is a different dataset
  (ADM2). Area validates against the published figure (2,556.6 km²).
- **Cell geometry is an approximation.** The provider snaps requests to its own
  grid and reports coordinates that are not exact 0.25° multiples. Each cell is
  modelled as a 0.25° box centred on the reported coordinate. This affects area
  weights at the margin, not the temperature values.

## Climate data

- **Secondary distribution.** Temperature is ERA5 *via* the Open-Meteo archive,
  not the Copernicus CDS product. Provenance is labelled in every envelope and
  the catalogue. The CDS adapter is declared in `ingestion/cds_era5.py` and
  raises `NotImplementedError`.
- **Five grid cells for the whole metro.** At 0.25° the metro spans five
  returned grid points. Ward-level heat differentiation is not possible with
  this source; ranking cells would be ranking data resolution, not climate.
  This is why results are published per cell with the resolution attached.
- **No reported missing data.** Every cell-year has 100% coverage. The provider
  is assumed to interpolate or complete the series, but that behaviour is
  undocumented, so `coverage_pct = 100` should be read as "the provider returned
  a value", not "an observation existed".

## Analytical

- **Ward geometry exists but no ward-level indicator is published yet.** The
  boundary layer and crosswalk are built, validated and persisted; aggregating
  indicators to wards is the next phase. Reporting a ward number today would
  imply a granularity the climate data does not support.
- **Municipality values are a derived index, not an observation.** They are an
  area-weighted mean of integer cell counts, which is why they are fractional
  (0.223 days) and why `basis = derived`. Uncertainty bounds are the min/max
  across contributing cells, not a confidence interval.
- **One indicator only.** `hot_days_tmax_ge_35c`. No trends, no projections,
  no drought, no fire, no flood.
- **No independent observational validation.** The benchmark compares the mart
  to an independent recount of the same source (`scripts/independent_check.py`).
  That proves the pipeline is correct, not that ERA5 matches Durban's weather
  stations.

## Not yet built

Ward-level indicators, exposure, vulnerability, projections, flood, fire, the
tool layer, the assistant, PDF reports, and the AWS deployment are specified in
`climate-resilience.md` and not implemented. Nothing in the repository should
be read as claiming otherwise.
