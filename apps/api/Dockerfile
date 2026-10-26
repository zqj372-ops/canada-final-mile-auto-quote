FROM node:22-bookworm-slim AS schedule-node
FROM python:3.11-slim

COPY --from=schedule-node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY packages ./packages
COPY reference ./reference
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
