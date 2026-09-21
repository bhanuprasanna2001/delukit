FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Berlin

WORKDIR /app

FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY delu ./delu
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM base AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser delu ./delu

ENV PATH="/app/.venv/bin:$PATH" \
    DAGSTER_HOME=/app/data/.dagster

RUN mkdir -p data/.dagster data/raw data/clean data/versioned \
    data/forecasts data/scores data/mlflow data/tuning data/ops \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:3000/ || exit 1

CMD ["dagster", "dev", "-m", "delukit.dagster_app.definitions", "-h", "0.0.0.0", "-p", "3000"]
