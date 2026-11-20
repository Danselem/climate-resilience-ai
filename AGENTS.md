# AGENTS.md

## Mission
Build a climate-resilience intelligence platform for South African municipalities. Users explore climate hazards, exposure and vulnerability through reproducible analytics and an AI assistant. Start with the eThekwini pilot; do not expand scope before the MVP works.

## Core stack
- Python 3.12+; manage dependencies and commands with `uv`.
- API: FastAPI, Pydantic, Uvicorn, HTTPX.
- UI: Streamlit for the MVP.
- Data: Pandas, GeoPandas, Shapely, PyProj, Rasterio, Xarray, rioxarray; use Dask only when data size requires it.
- Climate indices: xclim where its definitions fit the selected indicator.
- Spatial database: PostgreSQL + PostGIS; SQLAlchemy and GeoAlchemy2.
- AI: OpenRouter through its OpenAI-compatible API. Keep model ID and API key in environment configuration.
- AWS: S3, ECS Fargate, RDS PostgreSQL/PostGIS, SQS, ECR, CloudWatch and Secrets Manager. Provision cloud resources with Terraform.
- Quality: pytest, Ruff and type hints.

Use these packages where needed; do not add a framework or dependency without a concrete MVP requirement. Check current package/API documentation before adopting unfamiliar features.

## Non-negotiable rules
- Python/PostGIS perform calculations. The LLM selects tools and explains returned results; it must not invent or calculate climate indicators.
- Keep raw source files immutable. Store processed outputs separately and record source URL, retrieval date, licence, version, units, CRS, spatial/temporal coverage and processing steps.
- Preserve distinctions between observations, reanalysis and projections. Record scenario, model, baseline and period for every projection.
- Never combine datasets until units, CRS, spatial resolution, time basis and geographic identifiers have been checked.
- Keep hazard, exposure and vulnerability separate. Do not label a result a risk score unless its method and inputs are explicitly defined and validated.
- Every displayed metric must be traceable to its source and reproducible calculation. Show uncertainty and missing-data limitations; abstain when evidence is insufficient.
- Never commit secrets, credentials, private data or downloaded datasets. Use `.env.example` for variable names only and AWS Secrets Manager in cloud deployments.
- Keep local Docker Compose and AWS deployments configuration-driven; do not fork application logic for each environment.

## Implementation workflow
1. Inspect the repository and existing instructions before changing files. Do not replace working components without evidence.
2. Build the data pipeline first: acquire one real pilot dataset, inspect its format/licence/coverage, validate it, then add the next source.
3. Implement and test deterministic climate and spatial functions before adding LLM orchestration.
4. Expose analytics as small typed tools with validated inputs/outputs. Use bounded tool calls and handle unavailable data explicitly.
5. Keep OpenRouter behind a small provider adapter; make model selection configurable and log model, latency, token usage and estimated cost without logging secrets or sensitive data.
6. Add tests with known reference values and edge cases as each component is built. Run the relevant tests after every change.
7. Update README and `.env.example` when setup, commands or configuration change. Do not claim a feature or dataset works until it has been exercised.

## Validation
- Run `uv run pytest` and `uv run ruff check .` before considering a change complete.
- Test ingestion, schema/CRS/units, geometry validity, missing values and temporal coverage.
- Compare analytical outputs with independently calculated reference results; test spatial joins against known locations.
- Evaluate the assistant for correct tool selection, numerical correctness, source attribution, unsupported-question abstention, latency and OpenRouter cost.
- Record failed tests and known limitations. Never hide a failed check or fabricate evaluation results.

## Scope discipline
Deliver a working, measurable MVP before adding orchestration frameworks, vector databases, workflow schedulers or Kubernetes. Prefer simple Python functions and SQL queries unless measured requirements justify additional infrastructure. Keep detailed architecture, data inventory and evaluation methodology in separate project documents, not this file.
