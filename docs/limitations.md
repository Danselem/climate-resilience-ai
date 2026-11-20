# Limitations — Phase 3

Recorded at the end of Phase 3 exposure. Anything here is a known, deliberate
gap, not an oversight. A limitation that changes an output is also recorded in that
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
- **The window ends at the last complete calendar year.** The published range is
  1980–2025: 46 complete years. The last two to three months of this feed are
  preliminary ERA5T and can be revised, so a window ending "today" could change
  its numbers without any change to code or inputs. A year is published only if
  its observations span 1 January to 31 December *and* meet the coverage gate;
  coverage alone would have labelled a series ending in November as a full year
  ([ADR-008](adr/008-analysis-window-and-revisions.md)).

## Exposure

- **The exposure surface is 1 km, not 100 m.** The national 100 m WorldPop
  GeoTIFF is 609 MB and `data.worldpop.org` does not honour range requests, so
  it cannot be subset at download. The 1 km aggregated UN-adjusted product is
  7.3 MB and is what the MVP uses ([ADR-009](adr/009-exposure-resolution-and-vulnerability-gap.md)).
  At eThekwini's latitude a cell is about 0.8 km east–west by 0.9 km north–south;
  "1 km" is the equatorial nominal size. A settlement smaller than a cell cannot
  be resolved.
- **WorldPop 2020 is a modelled estimate, not a count.** It is UN-adjusted and
  two years before Census 2022. The clipped total is 3,766,001 persons against
  4,239,901 in the census — an 11% difference that is a vintage and method gap,
  not an error to hide. Every exposure row carries `basis = modelled_estimate`.
- **Ward allocation splits boundary cells by area.** A 1 km cell that straddles
  a ward boundary contributes to both wards in proportion to the overlap; it is
  not assigned to the ward containing its centre. Ward totals therefore sum to
  the municipality total within rounding.
- **Exposure is not risk.** Exposure rows carry `hazard_type = none`. They
  describe where people live. Combining them with heat, riverine or coastal
  flood is a separate calculation and none is published yet.

## Vulnerability

- **No vulnerability indicator is published.** The Census 2022 bulk ward product
  contains population by age, sex and population group only. Water, sanitation,
  tenure and employment indicators are available only through the interactive
  SuperWeb/SuperCross tools, which are not a reproducible bulk source.
- **The ward tables cannot be joined.** Census 2022 has 111 eThekwini wards
  (`59500001`–`59500111`); the validated ADM4 layer has 110 polygons. The census
  table is stored with official codes and deliberately not joined to geometry.
  A 111-to-110 join would be an assumption, not a crosswalk.
- **No combined index, ranking or risk score is produced.** With hazard,
  exposure and vulnerability kept separate, and vulnerability absent, any
  combined number would be invented. The assistant must abstain on vulnerability
  questions and say why.

## Analytical

- **Heat is grid-level; exposure is ward-level.** The heat indicator is
  published for five ERA5 cells and an area-weighted municipality, not for 110
  wards: the climate data cannot support that granularity. Population exposure
  uses a 1 km surface and can be allocated to wards, so the two products have
  different spatial resolutions and must not be presented as one map.
- **Municipality heat values are a derived index, not an observation.** They are
  an area-weighted mean of integer cell counts, which is why they are fractional
  (0.223 days) and why `basis = derived`. Uncertainty bounds are the min/max
  across contributing cells, not a confidence interval.
- **Two indicators only.** `hot_days_tmax_ge_35c` and
  `population_count_worldpop`. No trends, projections, drought, fire or flood.
- **No independent observational validation.** The benchmark compares the mart
  to an independent recount of the same source (`scripts/independent_check.py`).
  That proves the pipeline is correct, not that ERA5 matches Durban's weather
  stations or that WorldPop matches the census.

## Acquisition

- **`make data` re-runs stages whose inputs are already cached.** The cost is
  seconds of parsing, not bandwidth. There is no per-stage skip rule, so a
  source cannot go stale unnoticed: its artifact is re-hashed against the
  catalogue every run.
- **`make data-offline` proves the cache, not the network.** It verifies
  checksums and skips the build. A green offline run says the files match the
  catalogue; it says nothing about whether the upstream URL would still serve
  them.
- **Boundary downloads are national, not subset.** The ADM4 release arrives as a
  ~150 MB GeoJSON for South Africa and is filtered to the 110 eThekwini
  features locally. There is no server-side subset for this source.
- **WorldPop is downloaded whole.** The 7.3 MB 1 km national GeoTIFF is fetched
  and clipped locally. The 100 m equivalent is 609 MB with no resume; that is
  why it is not the MVP surface.
- **Stats SA pages are a bot challenge; files are not.** The catalogue cites the
  direct ward-product file. The HTML landing page cannot be fetched
  programmatically, so link rot would be detected by the artifact checksum, not
  by a page parser.
- **A required source with no adapter fails the run.** `worldpop` is required
  because exposure rows are published. `census_2022_ward_population` is active
  but optional: it is acquired and validated, yet no published indicator depends
  on it. `census_2022` remains blocked.

## Not yet built

Vulnerability indicators, projections, flood, fire, the tool layer, the
assistant, PDF reports, and the AWS deployment are specified in
`climate-resilience.md` and not implemented. Nothing in the repository should
be read as claiming otherwise.
