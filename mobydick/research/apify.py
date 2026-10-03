"""Apify scrape, used only when public web is thin."""

from __future__ import annotations

import time
from typing import Any

import requests

from mobydick.config import Settings, settings as default_settings


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
