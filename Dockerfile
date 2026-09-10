# syntax=docker/dockerfile:1.7
#
# A imagem base do Playwright (mcr.microsoft.com/playwright/python) vem com
# Chromium + todas as libs de sistema pré-instaladas em /ms-playwright, com
# PLAYWRIGHT_BROWSERS_PATH já apontando pra lá. Nenhum `playwright install`
# necessário no build.
#
# A tag da imagem PRECISA casar com a versão do pacote `playwright` no
# pyproject.toml — a versão do Chromium é acoplada à versão do Playwright.
# Se subir uma, sobe a outra.

# --- Build stage ---
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble AS builder

# uv não vem na imagem base; instala via pip (só neste stage, é descartado).
RUN pip install --no-cache-dir uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Deps primeiro para cache de camada: só refaz quando pyproject/lock mudam.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Código depois — muda com mais frequência que deps.
COPY feed_service/ ./feed_service/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# --- Runtime stage ---
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

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
