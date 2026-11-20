# Limitations — Phase 4

Recorded at the end of Phase 4 flood hazard. Anything here is a known,
deliberate gap, not an oversight. A limitation that changes an output is also recorded in that
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

## Evaluation

- **48 items, not the 150 the framework asks for.** The 150 needs manual
  labelling of retrieval ground truth, which has not been done. 48 is enough to
  detect regressions and not enough to claim general accuracy.
- **Accuracy varies run to run (75–94%).** The same model, same items. Most
  failures are request-limit aborts when it loops, not wrong analysis. Averaging
  them would hide the variance, so the range is reported.
- **Analytical references are independent of the tools, not of the data.** The
  expected row is found with SQL from the published parameters. That catches a
  tool returning the wrong row; it cannot catch the mart itself being wrong,
  which is `scripts/independent_check.py`'s job.
- **Retrieval quality is not measured.** Recall@k, MRR and nDCG need labelled
  relevant chunks. The document items only check that the right document was
  cited, which is a weaker claim.
- **Adversarial coverage is now 8/8, but the guard is not general.** The
  injection that previously succeeded is caught by a contradiction check: an
  answer asserting absence while citing a positive exposure value is rejected.
  That covers claims which contradict the retrieved evidence. It cannot catch an
  injected claim that is merely *unrelated* to the evidence, and it cannot catch
  a model persuaded to stay silent about a figure it did retrieve.
- **Six of forty-eight items fail on the request ceiling.** The model loops on
  some questions and is stopped. Raising the ceiling to five requests did not
  improve accuracy and pushed p95 from 3.9 s to 5.5 s, so it was reverted. These
  are recorded as failures rather than tuned away.

## Assistant

- **Latency is inside target only on a faster model.** `amazon/nova-micro-v1`
  answers in 1.6-3.8 s; the free fallback takes 10-18 s. Cold-start document
  questions add ~8 s to load the embedding model. The 6 s p95 applies to a warm
  process, which is how it deploys, and that is the configuration measured.
- **Citations over-report.** They are derived from every measurement and chunk
  the run touched, not from what the prose actually used. Groundedness is
  therefore guaranteed and citation *precision* is not; a one-number answer can
  carry ten references. Precision and completeness must be scored separately in
  the evaluation, and precision will be the weaker one.
- **Cost is measured, not estimated.** $0.00019 per question on nova-micro
  against a $0.004 target. The free fallback prices at zero, which is true and
  not representative of a paid deployment.
- **Tool-selection accuracy is not measured.** Two questions were checked by
  hand; the gold set does not exist yet.
- **The request ceiling is three, not two.** Most questions finish in two; a
  model that self-corrects needs a third, and failing outright costs more than
  the extra call. `gpt-oss-20b` refused to call a tool at all; `llama-3.1-8b`
  needed three rounds and still failed.
- **Input tokens are not the latency driver.** Halving them (8,939 → 4,400)
  left latency unchanged. Output tokens and provider throughput dominate, which
  is why the answer is capped and the model is fast rather than large.
- **The guard is keyword-based.** It refuses pluvial and unmeasured-dataset
  questions before any model call. A phrasing it misses still reaches tools that
  cannot answer it, so the failure mode is a slower refusal rather than a wrong
  answer — but it can also refuse an answerable question phrased unusually.
- **One model, no tiering.** The two-request design is a single agent run; a
  small intent model and a larger synthesis model cannot be mixed within it.
- **No response cache.** Repeated questions cost the same as first ones.
- **A validation failure costs the run.** If the model returns an uncited
  answer twice, the second request is consumed and the result is an abstention.
  That is the intended trade, and it is visible in the `error` field.
- **The caveat post-check is textual.** It guarantees the words "pluvial" appear
  in a flood answer; it cannot guarantee the rest of the sentence is right.
- **Free-model availability is volatile.** `gemma-4-26b:free` and
  `ling-3.2-flash:free` both returned 429 within minutes of working; one
  catalogue id (`nemotron-3-lightning:free`) returned "not a valid model ID".
  The fallback chain exists because of this, and the served model is recorded
  per run.

## Documents (RAG)

- **One document is indexed.** The Durban Climate Action Plan 2019. Retrieval
  quality cannot be claimed from a corpus this size, and the evaluation harness
  has not run.
- **GreenBook is excluded on licence grounds.** CC BY-NC-SA 3.0 ZA is
  NonCommercial and ShareAlike; a commercial derived index cannot honour it
  without written permission from CSIR.
- **The CAP names no wards.** All 156 extracted chunks are municipal, so a
  ward-level question about the plan returns city-wide text, labelled as such.
  That is a property of the document, not a retrieval failure, and it must not
  be reported as if the plan spoke to a ward.
- **Ingestion is slow and batch-only.** Six minutes for a 6.1 MB PDF, dominated
  by Docling layout analysis and OCR. Acceptable for ten documents, never at
  query time.
- **No reranker, and no evidence that one is needed.** Fusion is reciprocal
  rank with no learned weight; that is a defensible default, not a measured
  optimum.
- **The document index is not the analytical engine.** No published number is
  derived from retrieved text, and the boundary is enforced by having two
  stores rather than one.

## Flood

- **Pluvial (surface-water) flooding is not modelled.** This is the mechanism
  responsible for much of the April 2022 KwaZulu-Natal damage. Every flood row
  carries the caveat; a pluvial question must be refused, not answered with a
  riverine number (I9).
- **The 1 km raster is not a 1 km simulation.** The hydrology behind it is
  PCR-GLOBWB at 5' (~10 km). Two depth values cover 99% of wet cells in each
  riverine layer (0.466 m and 0.317 m at 100-year), because one water level is
  partitioned over a finer terrain model. Treat the product as a modelled
  extent with coarse depth classes, not a continuous depth field.
- **No cell in eThekwini exceeds 0.5 m at any return period.** The published
  threshold is therefore "any modelled inundation" rather than the 0.5 m
  default; the deviation from §10.7 is recorded in
  [ADR-010](adr/010-flood-hazard-baseline-and-coastal-null.md).
- **Coastal flooding is zero in the model, and zero is a stronger claim than
  "low".** Aqueduct v2 shows no coastal inundation for eThekwini at 10, 50 or
  100 years, nor at 2080 RCP8.5 with median sea-level rise. The same raster
  inundates Maputo Bay, so the null is not a failed download, and JICA's 2025
  Durban flood survey independently rates coastal storm surge risk as currently
  low. But the coast does flood: the 2007 surge caused damage, local sea level
  is rising 2.7 mm/year, and 0.3–1 m is projected by 2100. Absence of modelled
  inundation at 1 km is not absence of coastal risk.
- **Extent saturates while depth triples.** Wet cells go 316 → 317 → 317 while
  maximum depth goes 0.163 → 0.365 → 0.466 m between the 10- and 100-year
  events. Area-based exposure barely separates return periods; population
  exposure is flat at about 405,800. That is the source's behaviour at this
  resolution.
- **Ward exposure is highly concentrated.** Of 108 published wards, the median
  riverine area fraction at 100 years is 0.03% and 9 wards exceed 50%; the
  maximum is 83.6%. A single number for "the average ward" would describe almost
  none of them. The concentration is consistent with independent accounts: the
  April 2022 floods affected the Mlazi, Mgeni, Isipingo, Mbokodweni and
  Umhlatuzana, and the most exposed wards sit on those corridors. That is a
  placement check, not a validation of magnitude.
- **Population exposure is an upper bound.** The hazard model reports one depth
  per cell, so everyone in a wet cell is counted as exposed even where water
  would occupy part of it.
- **Two harbour wards have no riverine input.** Wards 026 and 028 sit where the
  riverine raster is nodata (the harbour); their riverine rows are withheld
  rather than published as zero, and listed in the snapshot's `withheld` field.
- **No flood defences, weirs or sluices are modelled**, and flash floods are
  poorly captured — both stated in WRI's technical note.
- **The GloFAS riverine cross-check is not implemented.** It needs CDS
  credentials, which this environment does not have. The independent check is a
  rasteriser recount of the same source: it verifies the pipeline, not the model.
- **Projections are not published.** The 2080 RCP8.5 layers are forced by GCMs
  while the baseline uses WATCH, so a difference is not a clean climate signal;
  measured for eThekwini, the three-GCM spread brackets the baseline. The
  coastal release also ships sea-level-rise percentiles 5 and 50 only, with no
  high-end case.

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
- **Four indicators.** `hot_days_tmax_ge_35c`, `population_count_worldpop`,
  `flood_exposed_area_pct` and `flood_exposed_population`. No trends,
  projections, drought or fire.
- **Hazard, exposure and vulnerability stay separate.** Flood exposure pairs a
  hazard with a population denominator, which is why it is published. It is not
  a risk score: no vulnerability input exists, no damages are modelled, and no
  ranking is produced.
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
- **Aqueduct is downloaded whole, deliberately.** Range requests work at the
  host, but GDAL's `/vsicurl` request pattern is throttled with intermittent
  403s, so a remote window read is not dependable. Six files (~410 MB) are
  fetched and clipped locally, which also gives a real checksum per file.
- **Stats SA pages are a bot challenge; files are not.** The catalogue cites the
  direct ward-product file. The HTML landing page cannot be fetched
  programmatically, so link rot would be detected by the artifact checksum, not
  by a page parser.
- **A required source with no adapter fails the run.** `worldpop` and
  `aqueduct_floods` are required because published indicators depend on them.
  `census_2022_ward_population` is active but optional: it is acquired and
  validated, yet no published indicator depends on it. `census_2022` remains
  blocked.

## Not yet built

Vulnerability indicators, projections, fire, the tool layer, the assistant, PDF
reports, and the AWS deployment are specified in `climate-resilience.md` and not
implemented. Nothing in the repository should be read as claiming otherwise.
