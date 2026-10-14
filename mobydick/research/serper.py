"""Public Google results via Serper. Used to find PE bios and interviews."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("mobydick.research.serper")

SERPER_SEARCH_URL = "https://google.serper.dev/search"


def google_search(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Public Google results for a bio or interview. No-op without SERPER_API_KEY."""
    from mobydick.research.trace import note

    query = (query or "").strip()
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not query or not key:
        return []
    note("searches_run")
    try:
        resp = requests.post(
            SERPER_SEARCH_URL,
            headers={"X-API-KEY": key},
            json={"q": query, "gl": "us", "hl": "en", "num": limit},
            timeout=20,
        )
    except requests.RequestException:
        return []
    if resp.status_code >= 400:
        return []
    try:
        payload = resp.json()
    except ValueError:
        return []
    organic = payload.get("organic") if isinstance(payload, dict) else None
    rows = organic if isinstance(organic, list) else []
    results: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("link") or "")
        if not url.startswith("http"):
            continue
        snippet = str(row.get("snippet") or "")
        results.append(
            {
                "url": url,
                "title": str(row.get("title") or ""),
                # _organic_results() stored snippet as description. life.py reads that key.
                "description": snippet,
                "snippet": snippet,
            }
        )
        if len(results) >= limit:
            break
    logger.info("google search results=%s", len(results))
    return results
