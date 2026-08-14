# syntax=docker/dockerfile:1.7
#
# Dedicated image for ui-review-agent only (ADR-0019 Decision 5). Every
# other service (platform, test-agent, summarize-agent, review-agent)
# builds from infrastructure/Dockerfile and never installs a browser --
# this image exists specifically so Chromium's several-hundred-MB
# footprint and build cost stay isolated to the one service that needs it.
# Build context is the repository root, same as infrastructure/Dockerfile:
#   docker build -f infrastructure/ui-review-agent/Dockerfile -t ui-review-agent:sprint11 .

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
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app

COPY --from=builder /opt/ai-platform /opt/ai-platform
COPY contracts ./contracts

# Installed as root (the default user at this point in the build) since
# --with-deps needs apt; the browser cache is then handed to the non-root
# runtime user so it can actually launch Chromium at container run time.
RUN playwright install --with-deps chromium \
    && chown -R aiplatform:aiplatform /opt/ms-playwright

USER 10001:10001

CMD ["ai-platform-test-agent"]
