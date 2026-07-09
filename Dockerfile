# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:24-bookworm-slim AS pi-cli
ARG PI_CODING_AGENT_VERSION=0.80.3
RUN npm install -g @earendil-works/pi-coding-agent@${PI_CODING_AGENT_VERSION}

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY --from=pi-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=pi-cli /usr/local/bin/npm /usr/local/bin/npm
COPY --from=pi-cli /usr/local/bin/npx /usr/local/bin/npx
COPY --from=pi-cli /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js /usr/local/bin/pi \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY scripts ./scripts
COPY frontend ./frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN pip install --upgrade pip \
    && pip install -e .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "trade_proposer_app.app:app", "--host", "0.0.0.0", "--port", "8000"]
