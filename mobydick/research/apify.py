"""Apify scrape, used only when public web is thin."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from typing import Any

import requests

from mobydick.config import Settings, settings as default_settings

logger = logging.getLogger("mobydick.research.apify")

# LinkedIn posts stay on APIFY_ACTOR. Web search uses Apify's Google Search actor.
GOOGLE_SEARCH_ACTOR = "apify~google-search-scraper"
# Renders JS pages when a plain GET comes back empty or blocked.
RENDER_ACTOR = "apify~website-content-crawler"


def run_actor(
    run_input: dict[str, Any],
    *,
    settings: Settings | None = None,
    http: requests.Session | None = None,
    wait_secs: int = 45,
) -> list[dict[str, Any]]:
    cfg = settings or default_settings
    if not cfg.apify_api_key:
        return []
    session = http or requests.Session()
    actor = cfg.apify_actor.replace("/", "~")
    try:
        started = session.post(
            f"https://api.apify.com/v2/acts/{actor}/runs",
            params={"token": cfg.apify_api_key},
            json=run_input,
            timeout=30,
        )
    except requests.RequestException:
        return []
    if started.status_code >= 400:
        logger.warning("apify actor http_status=%s", started.status_code)
        return []
    body = started.json()
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    run_id = data.get("id")
    dataset_id = (data.get("defaultDatasetId") or "") if isinstance(data, dict) else ""
    if not run_id:
        return []
    deadline = time.time() + wait_secs
    while time.time() < deadline:
        try:
            status_resp = session.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                params={"token": cfg.apify_api_key},
                timeout=20,
            )
        except requests.RequestException:
            break
        if status_resp.status_code >= 400:
            break
        status_body = status_resp.json()
        status_data = status_body.get("data") if isinstance(status_body.get("data"), dict) else {}
        status = str(status_data.get("status") or "").upper()
        dataset_id = status_data.get("defaultDatasetId") or dataset_id
        if status in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
            break
        time.sleep(3)
    if not dataset_id:
        return []
    try:
        items = session.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
            params={"token": cfg.apify_api_key, "limit": 20},
            timeout=30,
        )
    except requests.RequestException:
        return []
    if items.status_code >= 400:
        return []
    payload = items.json()
    return payload if isinstance(payload, list) else []


def linkedin_posts(profile_url: str, **kwargs: Any) -> list[dict[str, Any]]:
    if not profile_url:
        return []
    return run_actor({"profileUrls": [profile_url], "maxPosts": 10}, **kwargs)


def _organic_results(items: list[dict[str, Any]], limit: int) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for item in items:
        organic = item.get("organicResults") if isinstance(item, dict) else None
        rows = organic if isinstance(organic, list) else [item]
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or row.get("link") or "")
            if not url.startswith("http"):
                continue
            found.append(
                {
                    "url": url,
                    "title": str(row.get("title") or ""),
                    "description": str(row.get("description") or row.get("snippet") or ""),
                }
            )
            if len(found) >= limit:
                return found
    return found


def google_search(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Public Google results for a bio or interview. No-op without APIFY_API_KEY."""
    from mobydick.research.trace import note

    query = (query or "").strip()
    key = os.environ.get("APIFY_API_KEY", "").strip() or default_settings.apify_api_key
    if not query or not key:
        return []
    note("searches_run")
    cfg = replace(default_settings, apify_api_key=key, apify_actor=GOOGLE_SEARCH_ACTOR)
    items = run_actor(
        {
            "queries": query,
            "maxPagesPerQuery": 1,
            "countryCode": "us",
            "languageCode": "en",
            "searchLanguage": "en",
            "maximumLeadsEnrichmentRecords": 0,
            "geminiSearch": {"enableGemini": False},
            "perplexitySearch": {"enablePerplexity": False},
            "chatGptSearch": {"enableChatGpt": False},
            "copilotSearch": {"enableCopilot": False},
            "aiModeSearch": {"enableAiMode": False},
        },
        settings=cfg,
        wait_secs=35,
    )
    results = _organic_results(items, limit)
    logger.info("google search results=%s", len(results))
    return results


def fetch_rendered_page(url: str) -> str:
    """Visible text from Apify's website crawler. Empty without APIFY_API_KEY."""
    from mobydick.research.trace import note

    url = (url or "").strip()
    key = os.environ.get("APIFY_API_KEY", "").strip() or default_settings.apify_api_key
    if not url or not key:
        return ""
    note("pages_rendered")
    cfg = replace(default_settings, apify_api_key=key, apify_actor=RENDER_ACTOR)
    items = run_actor(
        {
            "startUrls": [{"url": url}],
            "maxCrawlPages": 1,
            "maxCrawlDepth": 0,
            "crawlerType": "playwright:adaptive",
            "saveHtml": False,
            "saveMarkdown": True,
            "htmlTransformer": "readableText",
            "removeCookieWarnings": True,
        },
        settings=cfg,
        wait_secs=60,
    )
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("markdown") or "")
        if text.strip():
            return text.strip()
    return ""
