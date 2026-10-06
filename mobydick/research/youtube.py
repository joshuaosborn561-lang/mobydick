"""Find talks via YouTube Data API and pull transcripts."""

from __future__ import annotations

from typing import Any

import requests

from mobydick.config import Settings, settings as default_settings


def search_videos(
    query: str,
    *,
    settings: Settings | None = None,
    http: requests.Session | None = None,
    max_results: int = 5,
) -> list[dict[str, str]]:
    cfg = settings or default_settings
    if not cfg.youtube_api_key or not query.strip():
        return []
    from mobydick.research.trace import note

    note("searches_run")
    session = http or requests.Session()
    try:
        resp = session.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max(1, min(max_results, 10)),
                "key": cfg.youtube_api_key,
            },
            timeout=20,
        )
    except requests.RequestException:
        return []
    if resp.status_code >= 400:
        return []
    data = resp.json()
    out: list[dict[str, str]] = []
    for item in data.get("items") or []:
        video_id = ((item.get("id") or {}).get("videoId")) or ""
        snippet = item.get("snippet") or {}
        if not video_id:
            continue
        out.append(
            {
                "video_id": video_id,
                "title": str(snippet.get("title") or ""),
                "channel": str(snippet.get("channelTitle") or ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "description": str(snippet.get("description") or ""),
            }
        )
    return out


def transcript_for(video_id: str) -> str:
    if not video_id:
        return ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ""
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
        snippets = getattr(fetched, "snippets", fetched)
        parts = []
        for item in snippets:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text:
                parts.append(str(text))
        return " ".join(parts).strip()
    except Exception:  # noqa: BLE001
        return ""


def talks_with_transcripts(
    person: str,
    firm: str = "",
    *,
    settings: Settings | None = None,
    http: requests.Session | None = None,
    max_videos: int = 3,
) -> list[dict[str, Any]]:
    query = " ".join(part for part in (person, firm, "interview OR podcast OR talk") if part)
    videos = search_videos(query, settings=settings, http=http, max_results=max_videos)
    out: list[dict[str, Any]] = []
    for video in videos:
        text = transcript_for(video["video_id"])
        out.append({**video, "transcript": text[:12000], "has_transcript": bool(text)})
    return out
