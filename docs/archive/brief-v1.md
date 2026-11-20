# Climate Resilience Intelligence Platform

**A cloud and local AI engineering project using AWS and OpenRouter**

## 1. What we're looking for

A working proof of concept that demonstrates how an AI-powered climate resilience platform can help municipal planners and analysts:

1. Explore historical climate conditions and future climate projections.
2. Identify areas exposed to climate hazards such as extreme heat, drought, flooding and wildfires.
3. Compare climate exposure with population and socioeconomic vulnerability.
4. Ask questions in natural language and receive answers supported by data.
5. Generate concise, evidence-backed climate risk reports that can inform local planning.

The project is not simply a climate chatbot. It is a reproducible climate-risk analysis system where AI retrieves real data, runs analyses and explains findings with traceable sources.

## 2. Project scenario

**Customer:** A South African municipality or climate adaptation planning team.

**Problem:** Municipalities have access to climate projections, hazard maps, demographic information and environmental datasets, but these are distributed across different platforms and formats. Bringing them together for a local risk assessment requires GIS and climate-data expertise.

The proposed platform provides a common interface for exploring these datasets and translating them into useful planning insights.

**Initial pilot:** eThekwini Municipality, with the option to extend to other municipalities once the workflow is validated. GreenBook provides metropolitan climate-risk profiles and adaptation information for eThekwini.

## 3. Where we're stuck

| Challenge | What the system should address |
|---|---|
| Fragmented data | Ingest climate, hazard, demographic and municipal datasets into one analytical environment. |
| Difficult interpretation | Translate climate indicators and geospatial outputs into understandable explanations. |
| Limited accessibility | Allow users to ask questions without needing to write SQL or GIS scripts. |
| Weak evidence trails | Link every reported result to its underlying dataset, location, period and calculation. |
| Planning implications | Identify exposed communities and infrastructure priorities, not just display climate statistics. |

## 4. What we're envisioning

An interactive climate resilience assistant with two interfaces:

- **AI assistant:** Users ask questions such as, “Which wards in eThekwini have the highest combined exposure to flooding and socioeconomic vulnerability?”
- **Analytical interface:** Users explore maps, charts, indicators, historical trends and future climate scenarios.

The AI should not invent climate-risk scores. It should call analytical tools that calculate results from the underlying datasets, then explain those results.

## 5. Data sources

The project should begin with a manageable number of credible, downloadable datasets. These are the proposed sources and their roles.

| Source | Data to collect | Purpose / access |
|---|---|---|
| [GreenBook](https://www.greenbook.co.za/greenbook-support.html) | Municipal risk profiles, maps and data packages, population distribution, vulnerability, water security and exposure | Primary municipal context. The support page lists municipal Maps & Data Packages. |
| [National Climate Change Information System (NCCIS)](https://nccis.environment.gov.za/climate-services/download-data) | CSIR and SAWS climate projections, historical climate information and climate extremes | South African climate context. |
| [Copernicus Climate Data Store](https://cds.climate.copernicus.eu/en/how-to-api) | ERA5 historical temperature, precipitation and other meteorological variables | Historical climate baseline. Download through the CDS API; account registration and dataset terms acceptance are required. |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/download/) | MODIS and VIIRS active fire detections | Historical and recent wildfire activity. CSV, JSON and shapefile downloads are supported; registration is required for archive access. |
| [Statistics South Africa](https://www.statssa.gov.za/) | Census 2022 population, household and demographic indicators | Population exposure and socioeconomic context. Identify the appropriate Census 2022 tables and geographic level before ingestion. |
| [Municipal Demarcation Board](https://www.demarcation.org.za/) | Municipal and ward boundaries | Common geographic reference for joining and mapping datasets. |

### Data feasibility notes

- GreenBook is the strongest starting point because it brings together municipal climate-risk, vulnerability and adaptation information. Its support page lists municipal Maps & Data Packages, including metropolitan resources.
- NCCIS provides access to South African climate datasets. Its CSIR projections include changes relative to the 1971–2000 baseline and projections for 2021–2050 under RCP4.5 and RCP8.5.
- ERA5 and FIRMS provide complementary historical weather and fire observations.
- Census and boundary data still need to be checked for the exact downloadable tables, geographic identifiers and licensing before implementation.

**Recommended first dataset bundle:** GreenBook municipal data, NCCIS climate projections, ERA5 and municipal/ward boundaries. Add FIRMS and Census 2022 once the initial spatial pipeline works.

## 6. System architecture and tools

The system should support local development and cloud deployment without maintaining two separate codebases.

### Local development

- Docker Compose, Python and `uv`
- FastAPI backend and Streamlit interface
- PostgreSQL/PostGIS for structured and spatial data
- Local data storage for downloaded datasets
- Python analytical tools using GeoPandas, Rasterio, Xarray and Pandas
- OpenRouter API for model inference

### Cloud deployment on AWS

- **Amazon S3:** Raw datasets, processed files and generated reports
- **Amazon ECS Fargate:** Containerised API and analytical services
- **Amazon RDS PostgreSQL/PostGIS:** Structured and spatial data
- **Amazon SQS:** Asynchronous ingestion and analysis jobs
- **Amazon CloudWatch:** Logs, monitoring and operational metrics
- **AWS IAM and Secrets Manager:** Access control and API credentials

### AI layer: OpenRouter

- Natural-language question understanding
- Tool selection and orchestration
- Explanation of analytical results
- Report generation and follow-up questions
- Model comparison across supported models

**Important design decision:** OpenRouter handles language and reasoning. Python and PostGIS perform the actual calculations. The model must not independently estimate rainfall trends, population exposure or climate-risk scores.

## 7. Your task

Build a working proof of concept that can:

1. **Ingest data:** Download and process the selected climate, hazard, demographic and boundary datasets.
2. **Prepare spatial data:** Standardise coordinate systems, geographic identifiers, time periods and spatial resolutions.
3. **Analyse climate indicators:** Calculate temperature and rainfall trends, extreme events, dry spells and other relevant indicators.
4. **Assess exposure:** Overlay climate hazards with municipal boundaries, wards and population information.
5. **Support natural-language queries:** Let users ask questions and trigger the appropriate analytical tools.
6. **Generate reports:** Produce evidence-backed summaries with maps, charts, data references and planning implications.

### Example questions

- Which wards have experienced the greatest increase in extreme temperatures?
- Which areas are projected to experience longer dry spells by 2050?
- Which communities have high flood exposure and socioeconomic vulnerability?
- How do historical rainfall patterns compare with future projections?
- Which areas should be prioritised for further climate adaptation assessment?

## 8. Evaluation and validation

The project should demonstrate measurable performance rather than relying on subjective assessments of chatbot responses.

| Evaluation area | How to evaluate it |
|---|---|
| Data ingestion | Percentage of datasets successfully downloaded, parsed and validated |
| Data quality | Missing values, invalid geometries, coordinate consistency and temporal coverage |
| Analytical correctness | Compare calculated indicators against independently calculated Python/GIS reference results |
| Spatial accuracy | Verify ward and municipal overlays against trusted boundary datasets |
| Retrieval accuracy | Check whether the assistant identifies the correct dataset, location and time period |
| Answer groundedness | Check whether every numerical claim is supported by retrieved data or a reproducible calculation |
| AI reliability | Test hallucinated indicators, unsupported claims and incorrect tool selection |
| Performance | Measure response latency, analytical processing time and API costs |
| Cloud reliability | Test ingestion failures, retries, logging and recovery |

### Evaluation dataset

Create a benchmark of approximately 20–30 questions, covering:

- Historical climate analysis
- Future climate projections
- Hazard exposure
- Population vulnerability
- Spatial comparisons
- Multi-dataset questions
- Questions that cannot be answered because the required data is unavailable

For each question, maintain a reference answer, expected dataset, calculation method and expected geographic scope.

### Key success criteria

- Analytical outputs agree with independently calculated reference values within defined numerical tolerances.
- No unsupported numerical claims in generated reports.
- Correct identification of the underlying datasets and geographic areas.
- Reproducible analytical results.
- Measured latency and inference costs for the selected OpenRouter models.

## 9. Project structure

```text
climate-resilience-ai/
├── README.md
├── pyproject.toml
├── uv.lock
├── docker-compose.yml
├── .env.example
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── reference/
│
├── src/
│   ├── api/
│   ├── ingestion/
│   ├── preprocessing/
│   ├── analytics/
│   ├── spatial/
│   ├── agent/
│   ├── evaluation/
│   └── reporting/
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_analytics.py
│   ├── test_spatial.py
│   └── test_agent.py
│
├── eval/
│   ├── questions.json
│   ├── reference_answers.json
│   └── evaluation_results.json
│
└── infrastructure/
    └── aws/
```

## 10. Required deliverables

1. **Working application:** A climate resilience assistant with a natural-language interface.
2. **Local deployment:** Runnable using `uv` and Docker Compose.
3. **AWS deployment:** Containerised application with documented infrastructure and deployment instructions.
4. **Data pipeline:** Reproducible ingestion and preprocessing scripts.
5. **Analytical tools:** Climate indicators, spatial overlays and exposure analysis.
6. **Evaluation results:** Benchmark questions, reference calculations, measured performance and failure analysis.
7. **Documentation:** Dataset sources, licences, setup instructions, architecture and limitations.
8. **Demonstration:** A short walkthrough showing real questions, analytical outputs and generated reports.

## 11. Scope and expected outcomes

| Phase | Expected outcome |
|---|---|
| 1. Data acquisition | Working downloads and validation for the initial dataset bundle |
| 2. Data engineering | Reproducible ingestion and geospatial processing |
| 3. Climate analytics | Historical trends, future projections and exposure indicators |
| 4. AI assistant | Natural-language interface with analytical tool calling through OpenRouter |
| 5. Evaluation | Benchmark results, accuracy checks, latency and cost measurements |
| 6. AWS deployment | Cloud-hosted application with monitoring and documented deployment |

**Final outcome:** A functioning climate resilience intelligence platform that demonstrates how public climate and environmental data can be transformed into accessible, reproducible and evidence-based decision support for South African municipalities.

## 12. Important implementation decisions

- **Do not attempt to model every climate hazard initially.** Start with heat, drought and wildfire. Add flood analysis once suitable elevation, drainage and flood-hazard datasets are secured.
- **Do not treat climate hazard as climate risk.** Risk assessment requires hazard, exposure and vulnerability. Keep these as separate analytical components.
- **Do not mix historical observations and future projections without labelling them.** Preserve their different sources, periods, scenarios and spatial resolutions.
- **Do not let the LLM perform GIS calculations.** Use deterministic analytical functions and let the LLM interpret their outputs.
- **Keep the local and AWS environments consistent.** Dockerise the application and use environment-based configuration.

**Data qualification:** The sources above have public access routes and documented data offerings, but this is not confirmation that every municipal package has been downloaded and inspected. The first engineering milestone should be to retrieve the eThekwini package, inspect its actual files and metadata, and establish which indicators can be calculated reliably before building the AI layer.

The immediate next step is to build a small, testable dataset pipeline before investing time in the conversational interface.
