# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.8-python3.14-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/ai-platform

WORKDIR /build

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.14-slim-trixie AS runtime

RUN groupadd --system --gid 10001 aiplatform \
    && useradd --system --uid 10001 --gid aiplatform --home-dir /nonexistent aiplatform

ENV PATH=/opt/ai-platform/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /opt/ai-platform /opt/ai-platform
COPY contracts ./contracts

USER 10001:10001

CMD ["ai-platform"]
