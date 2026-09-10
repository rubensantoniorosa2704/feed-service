# syntax=docker/dockerfile:1.7

# --- Build stage ---
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY feed_service/ ./feed_service/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# --- Runtime stage ---
FROM python:3.11-slim-bookworm

RUN groupadd --system feed \
    && useradd --system --gid feed --home /app feed \
    && mkdir -p /app/data \
    && chown -R feed:feed /app

WORKDIR /app

COPY --from=builder --chown=feed:feed /app /app

USER feed

ENV PATH="/app/.venv/bin:$PATH"

VOLUME ["/app/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz').read()"

CMD ["feed-service"]
