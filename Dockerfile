FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mobydick ./mobydick
COPY mcp_server ./mcp_server
COPY data ./data
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh
COPY .env.example .

RUN mkdir -p data/jobs data/deliveries data/dossiers data/exclude seed \
    && cp data/exclude/series_ab.json seed/series_ab.json \
    && cp data/exclude/pe.json seed/pe.json \
    && chmod +x scripts/entrypoint.sh

ENV MCP_TRANSPORT=streamable-http
ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV MOBYDICK_DATA_DIR=/app/data

EXPOSE 8000

CMD ["/app/scripts/entrypoint.sh"]
