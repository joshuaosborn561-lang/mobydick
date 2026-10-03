#!/bin/sh
set -eu
mkdir -p /app/data/exclude /app/data/deliveries /app/data/jobs /app/data/dossiers
if [ ! -s /app/data/exclude/series_ab.json ] && [ -f /app/seed/series_ab.json ]; then
  cp /app/seed/series_ab.json /app/data/exclude/series_ab.json
fi
if [ ! -s /app/data/exclude/pe.json ] && [ -f /app/seed/pe.json ]; then
  cp /app/seed/pe.json /app/data/exclude/pe.json
fi
exec python -m mcp_server
