FROM docker.devneeds.ir/python:3.11-slim

# Install uv
COPY --from=docker.devneeds.ir/ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer-cached until pyproject.toml / uv.lock change)
COPY pyproject.toml uv.lock ./
RUN UV_INDEX_URL=https://pypi.devneeds.ir/simple/ \
    uv sync --frozen --no-dev --no-install-project

# Copy source
COPY . .

# Persist the database outside the container image
VOLUME ["/app/data"]

CMD [".venv/bin/python", "app.py"]
