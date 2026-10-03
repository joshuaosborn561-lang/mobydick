"""Conservative signal extraction. Never invent hometowns, addresses, or stories."""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from mobydick.config import Settings, settings as default_settings

HOMETOWN_RE = re.compile(
    r"\b(?:grew up in|raised in|originally from|born in)\s+([A-Z][A-Za-z.'-]{2,24}(?:\s+[A-Z][A-Za-z.'-]{2,24})?)",
)
WHY_RE = re.compile(
    r"\b(?:founded|started|because|mission is|we started|I started)\b[^.!?]{10,240}",
    re.IGNORECASE,
)
CAUSE_RE = re.compile(
    r"\b(?:nonprofit|non-profit|charity|veteran|military|church|faith|climate|cancer|mental health|scholarship|foundation)\b[^.!?]{0,160}",
    re.IGNORECASE,
)
QUIRK_RE = re.compile(
    r"\b(?:marathon|triathlon|pilot|fly fishing|woodwork|guitar|jazz|chess|ultra|ironman|beekeep|pottery|sailing|climbing)\b[^.!?]{0,160}",
    re.IGNORECASE,
)

IDENTITY_HINTS = (
    "grew up",
    "raised in",
    "hometown",
    "my dad",
    "my mom",
    "military",
    "veteran",
    "cancer",
    "faith",
    "church",
    "hobby",
    "book",
    "podcast",
    "marathon",
    "coach",
    "community",
)


def _clip(text: str, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def heuristic_extract(blobs: list[str]) -> dict[str, str]:
    joined = " ".join(blob for blob in blobs if blob)
    hometown = ""
    match = HOMETOWN_RE.search(joined)
    if match:
        hometown = match.group(1).strip(" .,")
    why = ""
    why_match = WHY_RE.search(joined)
    if why_match:
        why = _clip(why_match.group(0))
    causes = ""
    cause_match = CAUSE_RE.search(joined)
    if cause_match:
        causes = _clip(cause_match.group(0))
    quirk = ""
    quirk_match = QUIRK_RE.search(joined)
    if quirk_match:
        quirk = _clip(quirk_match.group(0))
    hook = why or causes or quirk or ""
    confidence = "low"
    if hometown and (why or quirk):
        confidence = "high"
    elif why or causes or quirk:
        confidence = "medium"
    return {
        "hometown": hometown,
        "why": why,
        "causes": causes,
        "quirk": quirk,
        "hook": _clip(hook, 220),
        "confidence": confidence,
    }


def llm_extract(
    prompt: str,
    *,
    settings: Settings | None = None,
    http: requests.Session | None = None,
) -> dict[str, Any] | None:
    cfg = settings or default_settings
    session = http or requests.Session()
    if cfg.anthropic_api_key:
        try:
            resp = session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": cfg.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 800,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=45,
            )
            if resp.status_code < 400:
                content = (resp.json().get("content") or [{}])[0].get("text") or ""
                return _parse_json_object(content)
        except requests.RequestException:
            return None
    if cfg.openai_api_key:
        try:
            resp = session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                },
                timeout=45,
            )
            if resp.status_code < 400:
                content = (
                    ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content")
                    or ""
                )
                return _parse_json_object(content)
        except requests.RequestException:
            return None
    return None


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_person_fields(
    name: str,
    company: str,
    sources: list[dict[str, str]],
    *,
    audience: str,
    settings: Settings | None = None,
) -> dict[str, str]:
    blobs = [src.get("text") or src.get("transcript") or src.get("description") or "" for src in sources]
    urls = [src.get("url") for src in sources if src.get("url")]
    heur = heuristic_extract(blobs)
    prompt = (
        f"Extract ONLY publicly stated personal facts about {name} at {company}. "
        "Return JSON with keys: hometown, why, causes, quirk, hook, confidence, research_note. "
        "If a fact is not explicitly in the sources, leave it blank. Never invent. "
        "Identity signals only (origin, hobbies, books, causes, military, family stories they told). "
        "Not resume items. Sources:\n"
        + "\n\n".join((src.get("text") or src.get("transcript") or "")[:1500] for src in sources[:6])
    )
    llm = llm_extract(prompt, settings=settings) or {}
    merged = {
        "hometown": str(llm.get("hometown") or heur["hometown"]),
        "why": str(llm.get("why") or heur["why"]),
        "causes": str(llm.get("causes") or heur["causes"]),
        "quirk": str(llm.get("quirk") or heur["quirk"]),
        "hook": str(llm.get("hook") or heur["hook"]),
        "confidence": str(llm.get("confidence") or heur["confidence"]),
        "research_note": str(llm.get("research_note") or ""),
        "sources": " | ".join(urls),
    }
    if audience == "pe_partners":
        if not merged["research_note"]:
            merged["research_note"] = "Public sources only. Blank fields were not stated."
    return merged


def footprint_is_thin(sources: list[dict[str, Any]]) -> bool:
    texts = [src.get("text") or src.get("transcript") or src.get("description") or "" for src in sources]
    joined = " ".join(texts).lower()
    if any(hint in joined for hint in IDENTITY_HINTS):
        return False
    has_talk = any(src.get("has_transcript") or src.get("podcast") for src in sources)
    return not has_talk
