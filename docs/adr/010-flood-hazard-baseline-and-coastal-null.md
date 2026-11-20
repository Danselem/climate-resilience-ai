# ADR-010 — Flood hazard: baseline only, any-inundation threshold, and a coastal null

**Status:** accepted

## Context

F4 requires riverine and coastal flood exposure per ward for 10-, 50- and
100-year return periods, with depth thresholds. The source is WRI Aqueduct
Floods v2 hazard maps: global 1 km GeoTIFFs of inundation depth, one file per
mechanism, return period, scenario and forcing.

Four assumptions in the specification did not survive inspection.

**1. The 0.5 m default threshold is empty here.** Measured over the municipal
polygon, no cell exceeds 0.5 m at any return period. The depth distribution is
bimodal: shallow or dry.

| Threshold | Wet cells (100-yr, riverine) |
|---|---|
| > 0.0 m | 317 |
| > 0.1 m | 317 |
| > 0.25 m | 316 |
| > 0.5 m | **0** |
| > 1.0 m | 0 |

Publishing at 0.5 m would emit 330 rows of `0.00 %`, which a reader cannot
distinguish from a broken pipeline.

**2. Coastal flooding is genuinely zero for eThekwini.** Zero wet cells at
10-, 50- and 100-year, and zero at 2080 RCP8.5 with median sea-level rise. The
file is not empty: the same raster inundates 153 cells elsewhere in the region,
concentrated in Maputo Bay at depths to 2.04 m. Aqueduct's bathtub surge model
floods a low-lying bay city and not this steep coastline.

**3. The 2080 projection is not a signal.** Measured at 100-year:

| Scenario | Wet cells | Max depth | Population in wet cells |
|---|---|---|---|
| Baseline (WATCH) | 337 | 0.466 m | 397,843 |
| 2080 RCP8.5 NorESM1-M | 336 | 0.327 m | 397,821 |
| 2080 RCP8.5 GFDL-ESM2M | 340 | 0.785 m | 399,540 |
| 2080 RCP8.5 MIROC-ESM-CHEM | 337 | 0.422 m | 397,843 |

Two of three GCMs show *less* depth than baseline; one shows more. Extent moves
by three cells out of 337. The baseline is forced by EUWATCH while the future
layers are forced by GCMs, so a baseline-to-2080 difference confounds climate
change with a change of forcing dataset.

**4. The depth field is a mask in disguise.** Within each riverine layer, two
values cover 99% of wet cells (0.466 m and 0.317 m at 100-year). The hydrology
is PCR-GLOBWB at 5′ (~10 km); the 1 km raster only partitions one water level
over the terrain. A threshold on this field is not measuring depth.

Two further facts: the release ships coastal sea-level-rise percentiles 5 and
50 only — there is no `perc_95` file despite WRI's data dictionary listing it —
and two harbour wards (026, 028) fall where the riverine raster is nodata, so
their riverine exposure has no input at all.

## Literature check

A model that produces a null needs an external view, so the outputs were
compared against current published work on eThekwini. The comparison is
corridor-level, not a validation of magnitude.

- **JICA, Data Collection Survey for Flood Damage Reduction in Durban (2025)**
  records that the April 2022 floods affected all rivers in the municipality —
  Mlazi, Mgeni, Isipingo, Mbokodweni and Umhlatuzana — and states that
  "coastal storm surge risk is currently considered low", while recommending a
  coastal risk assessment. Low is not zero, but it is consistent with the model
  producing no coastal inundation at 1 km.
- **Presidential Climate Commission brief (2023)** reports 18 river courses
  overflowing, naming the Amanzimtoti, Umbilo and Umgeni, with the worst
  impacts in riverside communities and informal settlements.
- **Perfect Storm (Outlier, 2023)** is explicit that April 2022 "was a case of
  inland river flooding, rather than a coastal storm surge", and records local
  sea-level rise of 2.7 mm/year with 0.3–1 m projected by 2100.
- **Springer, *Mapping pluralistic future flood risk scenarios for informal
  settlements in eThekwini* (2025)** identifies Umlazi, KwaMashu and KwaMakhuta
  among settlements at extremely high flood risk across all scenarios.

The published pattern matches those corridors. The most exposed wards cluster
on the Umgeni/Springfield reach around 31.00°E, −29.72 to −29.79 (wards 039,
034, 046, 048, 054, 025); on the Umlazi, Isipingo and Umhlatuzana system around
30.94–30.99°E, −29.88 to −29.98 (wards 075, 090, 068, 033, 032); and on the
northern reaches near Tongaat at 31.15°E, −29.54 (ward 062). Those are the
rivers the literature names.

What this does and does not establish: the ward pattern is qualitatively
consistent with independent accounts, which is evidence against a systematic
placement error. It is not evidence that the magnitudes are right — the
hydrology is 10 km, the depth field is two-valued, and no damage or defence
data enters the model.

## Decision

- **Baseline only.** Riverine `historical`/WATCH and coastal
  `historical`/`nosub`, at 10, 50 and 100 years. The 2080 measurement is
  recorded here as the evidence for deferring projections to their own phase,
  where model and baseline provenance become first-class.
- **Publish at any modelled inundation** (`depth_threshold_m = 0.0`). This
  deviates from §10.7, which asks for the 0.5 m default and an any-inundation
  variant. Publishing both would satisfy the letter of the specification and
  misinform the reader: the 0.5 m variant is structurally empty. The deviation
  is recorded rather than quietly applied.
- **Coastal zero rows are published, carrying a warning that names the Maputo
  counter-evidence and JICA's "currently low" assessment.** A zero that is
  queryable, corroborated and labelled is better than an absent row that reads
  as an omission.
- **Scopes with no hazard input are withheld, not published as zero.** Wards
  026 and 028 have no riverine coverage; their riverine rows are absent from the
  mart and listed in the snapshot's `withheld` field. Publishing `0.0` would
  claim "not exposed" when the truth is "not modelled here" (I8, F10).
- **Resolution is reported as two numbers**: the 1 km raster and the 5′ (~10 km)
  hydrological model. `native_resolution` carries both, because the second is
  the one that bounds the claim.
- **Population exposure is an upper bound at this resolution.** The hazard model
  reports one depth per cell, so everyone in a wet cell is counted as exposed.
  Every population row says so.
- **The catalogue records all six raw files.** `checksum`/`artifact` describe
  the canonical parquet; `artifacts` lists each source GeoTIFF with its SHA-256.

## Consequences

- 1,320 flood rows: 660 area fractions and 660 population counts, covering 108
  wards × 3 return periods × 2 mechanisms, plus the municipality. Six
  scope-layers are withheld for missing riverine data.
- The published municipal riverine exposure is 8.86% of area (226.5 km²) at
  10 years and 8.89% (227.3 km²) at 50 and 100 years, on 316–317 cells.
  Population in those cells is 405,811 at 10 years and 405,832 at 50 and 100.
- Extent saturates while depth triples. Area-based exposure barely separates the
  return periods; that is a property of the source at this resolution, not a bug,
  and it is stated in the README rather than smoothed over.
- Ward figures vary widely: the most exposed ward is 83.6% inundated and the
  median ward is 0.03%. At a 5′ model resolution those are statements about a
  coarse modelled extent, not about streets, and the concentration is consistent
  with the literature's focus on named river corridors rather than diffuse
  city-wide flooding.
- No risk score, ranking or combined index is produced. Riverine and coastal are
  separate axes and are never summed.
- The GloFAS riverine cross-check named in §10.7 remains unimplemented: it needs
  CDS credentials, which this environment does not have. The independent check
  is a rasteriser recount of the same source, which verifies the pipeline, not
  the model.

## Revisit triggers

- A CDS account exists: add GloFAS discharge as an independent riverine check
  and publish the comparison rather than asserting agreement.
- A higher-resolution hydraulic model for eThekwini (municipal floodline study,
  JRC or a licensed consultancy layer) becomes available and licensed for
  derived use: replace the hazard grid and bump the method version.
- WRI republishes with a `perc_95` coastal file, or a future release separates
  baseline and future forcing datasets so that a delta is identifiable: revisit
  the projection decision.
- The MDB ward release arrives: rerun ward-level statistics on official
  boundaries.
