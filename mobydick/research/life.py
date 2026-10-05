"""Cited personal facts for PE letters. Empty when a source does not say it."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from mobydick.research.apify import linkedin_posts
from mobydick.research.taddy import search_episodes
from mobydick.research.web import company_url, fetch_text
from mobydick.research.youtube import talks_with_transcripts

logger = logging.getLogger("mobydick.research.life")

TEAM_PATHS = ("/team", "/people", "/leadership", "/our-team", "/about")
RESEARCH_NOTE = "Public sources only. Empty means not found. No home address."

_STREET = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.\- ]{2,40}\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct)\b",
    re.IGNORECASE,
)
_FIRST_PERSON = re.compile(r"\b(I|I'm|I’m|I'd|I’d|I've|I’ve|my|me)\b")
_ABOUT = re.compile(
    r"\b(I|I'm|I’m|I'd|I’d|I've|I’ve|my|me|she|he|her|hers|his|him)\b",
    re.IGNORECASE,
)
_FIRM_VOICE = re.compile(r"\b(as a firm|our firm|the firm|the company|we are|we're|we’re)\b", re.IGNORECASE)
_QUOTE = re.compile(r"[\"“]([^\"”]{12,280})[\"”]")

_HOMETOWN = re.compile(r"\b(grew up|raised in|born in|hometown|originally from)\b", re.IGNORECASE)
_FAMILY = re.compile(
    r"\b(parents|father|mother|dad|mom|immigrat\w*|first-generation|first generation|"
    r"sibling|brother|sister|family business)\b",
    re.IGNORECASE,
)
_COLLEGE = re.compile(
    r"\b(college|university|varsity|bachelor|alumnus|alumna)\b|\bplayed\b.{0,40}\b(at|for)\b",
    re.IGNORECASE,
)
_MILITARY = re.compile(
    r"\b(navy|army|marines|marine corps|air force|coast guard|veteran|west point|served in the)\b",
    re.IGNORECASE,
)
_EARLY = re.compile(
    r"\b(first job|before private equity|founded|co-founded|cofounded|food truck|restaurant|"
    r"family business|worked as|started a|started an|started my)\b",
    re.IGNORECASE,
)
_CAUSES = re.compile(
    r"\b(board of|nonprofit|non-profit|foundation|faith|church|synagogue|mosque|philanthrop)\b",
    re.IGNORECASE,
)
_EVENTS = re.compile(
    r"\b(marathon|triathlon|ironman|pilot|cancer|adopted|widow|divorc|olympian)\b|"
    r"\blost (his|her|their)\b",
    re.IGNORECASE,
)
_WHY = re.compile(r"\b(private equity|buyout|growth equity)\b", re.IGNORECASE)
_WHY_PERSONAL = re.compile(r"\b(got into|joined|left|because|started)\b", re.IGNORECASE)

_LIFE_KEYS = (
    "hometown",
    "family_background",
    "college",
    "military_service",
    "early_jobs",
    "causes",
    "life_events",
    "quotes",
)
_FIELD_SOURCE = {
    "hometown": "hometown_or_from",
    "family_background": "family_background",
    "college": "college",
    "military_service": "military_service",
    "early_jobs": "early_jobs",
    "why": "why_got_into_pe",
    "causes": "beliefs_or_causes",
    "life_events": "life_events",
    "quotes": "quotes",
}
_HOOK_ORDER = (
    "family_background",
    "military_service",
    "early_jobs",
    "hometown",
    "college",
    "life_events",
    "causes",
    "quotes",
)


def last_name_of(full_name: str) -> str:
    parts = [part for part in re.split(r"\s+", (full_name or "").strip()) if part]
    if not parts:
        return ""
    return parts[-1].strip(".,")


def _mentions(text: str, last: str) -> bool:
    if not last or not text:
        return False
    return re.search(rf"\b{re.escape(last)}\b", text, re.IGNORECASE) is not None


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text or "").strip()
    # Keep initials such as U.S. from becoming a sentence break.
    compact = re.sub(r"\b([A-Za-z])\.", r"\1<dot>", compact)
    parts = re.split(r"(?<=[.!?])\s+", compact)
    restored = [part.replace("<dot>", ".").strip() for part in parts]
    return [part for part in restored if len(part) >= 20]


def _clip(text: str, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _blocked(sentence: str) -> bool:
    lowered = sentence.lower()
    if "home address" in lowered or "private residence" in lowered:
        return True
    return _STREET.search(sentence) is not None


def _about_person(sentence: str, last: str, source_names_person: bool) -> bool:
    if _mentions(sentence, last):
        return True
    return bool(source_names_person and _ABOUT.search(sentence))


def _quote_ok(source: dict[str, str]) -> bool:
    kind = (source.get("kind") or "").lower()
    if kind in {"interview", "podcast", "bio", "transcript"}:
        return True
    blob = f"{source.get('title') or ''} {source.get('url') or ''}".lower()
    return any(token in blob for token in ("interview", "podcast", "bio", "transcript"))


def _blank() -> dict[str, str]:
    fields = {key: "" for key in (*_LIFE_KEYS, "why", "real_story", "hook", "sources")}
    fields["confidence"] = "low"
    fields["research_note"] = RESEARCH_NOTE
    return fields


def extract_life_story(full_name: str, sources: list[dict[str, str]]) -> dict[str, str]:
    """Copy sentences from sources that name the person. Never paraphrase."""
    last = last_name_of(full_name)
    found: dict[str, str] = {key: "" for key in (*_LIFE_KEYS, "why")}
    cites: dict[str, str] = {}
    story: list[str] = []

    for source in sources:
        text = source.get("text") or source.get("transcript") or source.get("description") or ""
        title = source.get("title") or source.get("name") or ""
        if not (_mentions(text, last) or _mentions(title, last)):
            continue
        source_names = _mentions(f"{title} {text[:400]}", last)
        url = source.get("url") or ""
        for sentence in _sentences(text):
            if _blocked(sentence) or not _about_person(sentence, last, source_names):
                continue
            clipped = _clip(sentence)
            if clipped not in story:
                story.append(clipped)
            hometown_hit = _HOMETOWN.search(sentence) and not _FIRM_VOICE.search(sentence)
            _take(found, cites, "hometown", hometown_hit, clipped, url)
            _take(found, cites, "family_background", _FAMILY.search(sentence), clipped, url)
            _take(found, cites, "college", _COLLEGE.search(sentence), clipped, url)
            _take(found, cites, "military_service", _MILITARY.search(sentence), clipped, url)
            _take(found, cites, "early_jobs", _EARLY.search(sentence), clipped, url)
            _take(found, cites, "causes", _CAUSES.search(sentence), clipped, url)
            _take(found, cites, "life_events", _EVENTS.search(sentence), clipped, url)
            if _WHY.search(sentence) and (_FIRST_PERSON.search(sentence) or _WHY_PERSONAL.search(sentence)):
                _take(found, cites, "why", True, clipped, url)
            if _quote_ok(source):
                quoted = _QUOTE.search(sentence)
                if quoted:
                    _take(found, cites, "quotes", True, _clip(quoted.group(1)), url)

    out = _blank()
    out.update(found)
    filled = [key for key in _LIFE_KEYS if found[key]]
    if len(filled) >= 3:
        out["confidence"] = "high"
    elif filled:
        out["confidence"] = "medium"
    out["real_story"] = " ".join(story[:3])
    for key in _HOOK_ORDER:
        if found.get(key):
            out["hook"] = found[key]
            break
    parts = []
    for key, value in found.items():
        if not value:
            continue
        url = cites.get(key) or ""
        if url:
            parts.append(f"{_FIELD_SOURCE[key]}={url}")
    out["sources"] = " | ".join(parts)
    return out


def _take(
    found: dict[str, str],
    cites: dict[str, str],
    key: str,
    matched: Any,
    sentence: str,
    url: str,
) -> None:
    if not matched or found.get(key):
        return
    found[key] = sentence
    if url:
        cites[key] = url


def _post_text(item: dict[str, Any]) -> str:
    for key in ("text", "content", "commentary", "postText", "description"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _thin(sources: list[dict[str, str]]) -> bool:
    text = " ".join(source.get("text") or "" for source in sources)
    return len(text.strip()) < 280


def gather_person_sources(row: dict[str, str]) -> list[dict[str, str]]:
    """Podcasts, interviews, and bios that actually name the person."""
    sources: list[dict[str, str]] = []
    full = row.get("full_name") or ""
    last = row.get("last_name") or last_name_of(full)
    firm = row.get("company_name") or ""
    base = company_url(row.get("company_website") or "", row.get("company_domain") or "")
    if base and last:
        for path in TEAM_PATHS:
            url = urljoin(base + "/", path.lstrip("/"))
            try:
                text = fetch_text(url)
            except Exception:
                logger.exception("bio page failed for %s", url)
                text = ""
            if text and _mentions(text, last):
                sources.append({"url": url, "title": f"{firm} bio", "text": text[:8000], "kind": "bio"})
    try:
        talks = talks_with_transcripts(full, firm, max_videos=2)
    except Exception:
        logger.exception("youtube lookup failed for %s", full)
        talks = []
    for talk in talks:
        text = talk.get("transcript") or talk.get("description") or ""
        title = str(talk.get("title") or "")
        if _mentions(f"{title} {text}", last):
            sources.append(
                {
                    "url": str(talk.get("url") or ""),
                    "title": title,
                    "text": str(text)[:12000],
                    "kind": "interview",
                }
            )
    try:
        episodes = search_episodes(f"{full} {firm}".strip())[:3]
    except Exception:
        logger.exception("taddy lookup failed for %s", full)
        episodes = []
    for episode in episodes:
        title = str(episode.get("name") or "")
        text = f"{title} {episode.get('description') or ''}"
        if _mentions(text, last):
            sources.append(
                {
                    "url": str(episode.get("audioUrl") or ""),
                    "title": title,
                    "text": text[:8000],
                    "kind": "podcast",
                }
            )
    if _thin(sources) and row.get("linkedin_url"):
        try:
            posts = linkedin_posts(row["linkedin_url"])
        except Exception:
            logger.exception("apify lookup failed for %s", full)
            posts = []
        for post in posts:
            text = _post_text(post)
            if text and _mentions(text, last):
                sources.append(
                    {
                        "url": str(post.get("url") or post.get("postUrl") or row.get("linkedin_url") or ""),
                        "title": "LinkedIn post",
                        "text": text[:4000],
                        "kind": "interview",
                    }
                )
    return sources
