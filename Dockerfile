# DE_261 demo image: React client built by Node, served by the FastAPI demo server.
#   docker compose up --build      ->  http://localhost:8000
#
# Stage 1 - build the web client
FROM node:20-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# Stage 2 - Python runtime
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EDU_ENV=docker
WORKDIR /app

# Install the package first so source edits do not invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[demo]"

# Runtime assets the server reads from the repo layout (rules, contracts, docs).
COPY infra/notification ./infra/notification
COPY schemas ./schemas
COPY docs/api.md ./docs/api.md
COPY --from=web /web/dist ./apps/web/dist

# Run as a non-root user; the demo sandbox spawns python subprocesses as this user.
RUN useradd --create-home --uid 1000 demo && chown -R demo:demo /app
USER demo

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

CMD ["python", "-m", "uvicorn", "edu_platform.entrypoints.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
