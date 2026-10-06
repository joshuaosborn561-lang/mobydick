"""One Taddy podcast search per prospect."""

from __future__ import annotations

from typing import Any

import requests

from mobydick.config import Settings, settings as default_settings

SEARCH_QUERY = """
query SearchEpisodes($term: String!) {
  search(term: $term, filterForTypes: [PODCASTEPISODE]) {
    searchId
    podcastEpisodes {
      uuid
      name
      description
      datePublished
      audioUrl
      podcastSeries { name }
    }
  }
}
"""


def search_episodes(
    term: str,
    *,
    settings: Settings | None = None,
    http: requests.Session | None = None,
) -> list[dict[str, Any]]:
    cfg = settings or default_settings
    if not (cfg.taddy_api_key and cfg.taddy_user_id and term.strip()):
        return []
    from mobydick.research.trace import note

    note("searches_run")
    session = http or requests.Session()
    try:
        resp = session.post(
            cfg.taddy_endpoint,
            json={"query": SEARCH_QUERY, "variables": {"term": term}},
            headers={
                "Content-Type": "application/json",
                "X-USER-ID": str(cfg.taddy_user_id),
                "X-API-KEY": cfg.taddy_api_key,
            },
            timeout=25,
        )
    except requests.RequestException:
        return []
    if resp.status_code >= 400:
        return []
    try:
        payload = resp.json()
    except ValueError:
        return []
    episodes = (((payload.get("data") or {}).get("search") or {}).get("podcastEpisodes")) or []
    out: list[dict[str, Any]] = []
    for ep in episodes[:8]:
        if not isinstance(ep, dict):
            continue
        series = ep.get("podcastSeries") if isinstance(ep.get("podcastSeries"), dict) else {}
        out.append(
            {
                "uuid": ep.get("uuid") or "",
                "name": ep.get("name") or "",
                "description": (ep.get("description") or "")[:1500],
                "datePublished": ep.get("datePublished") or "",
                "audioUrl": ep.get("audioUrl") or "",
                "podcast": series.get("name") or "",
            }
        )
    return out
