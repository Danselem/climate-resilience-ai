# Single image, two entrypoints: `cli` today, `api` and `worker` in later phases.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first so source changes do not invalidate it.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY data/catalogue ./data/catalogue
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["uv", "run", "--no-sync", "climate-resilience"]
CMD ["--help"]
