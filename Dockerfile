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
COPY .env.example .

RUN mkdir -p data/jobs data/deliveries data/dossiers data/exclude

ENV MCP_TRANSPORT=streamable-http
ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "mcp_server"]
