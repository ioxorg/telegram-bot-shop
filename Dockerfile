# Registry / index overrides — set these for air-gapped / mirrored environments.
ARG PYTHON_IMAGE=python:3.11-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:latest

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE}
ARG UV_INDEX_URL=https://pypi.org/simple/

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer-cached until pyproject.toml / uv.lock change)
COPY pyproject.toml uv.lock ./
RUN UV_INDEX_URL=${UV_INDEX_URL} \
    uv sync --frozen --no-dev --no-install-project

# Copy source
COPY . .

# Persist the database outside the container image
VOLUME ["/app/data"]
CMD [".venv/bin/python", "app.py"]
