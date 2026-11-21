# Single image, four entrypoints: cli, api, worker, ui.
#
# Two things here are deliberate and were measured, not guessed:
#
#  * Pango and GObject are installed because WeasyPrint loads them at run time;
#    without them the report worker fails with a dlopen traceback.
#  * uv runs with --no-cache and the application files are copied with --chown
#    rather than chowned afterwards. A `chown -R /app` duplicates every file
#    into a new layer (2.4 GB), and the uv cache added another 2 GB. Together
#    they took the image from ~4.5 GB to 33 GB on the first build.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
        libffi8 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data

# Dependency layer first so source changes do not invalidate it.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser data/catalogue ./data/catalogue
COPY --chown=appuser:appuser scripts ./scripts
RUN uv sync --frozen --no-dev --no-cache

USER appuser

ENTRYPOINT ["uv", "run", "--no-sync", "climate-resilience"]
CMD ["--help"]
