"""Cited personal facts for PE letters. Empty when a source does not say it."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin

from mobydick.config import settings as default_settings
from mobydick.research.apify import google_search, linkedin_posts
from mobydick.research.extract import llm_extract
from mobydick.research.taddy import search_episodes
from mobydick.research.trace import keep_fact, note, reject
from mobydick.research.web import candidate_bio_urls, company_url, fetch_document, host_key
from mobydick.research.youtube import talks_with_transcripts

logger = logging.getLogger("mobydick.research.life")

TEAM_PATHS = ("/team", "/people", "/leadership", "/our-team", "/about")
RESEARCH_NOTE = "Public sources only. Empty means not found. No home address."
NO_MODEL_WARNING = (
    "No ANTHROPIC_API_KEY or OPENAI_API_KEY is set. "
    "PE life extraction is heuristic only and leaves a field empty when it is not sure. "
    "Set ANTHROPIC_API_KEY or OPENAI_API_KEY to turn on cited model extraction."
)

_NAME_WORD = r"[A-Z][A-Za-z\u00C0-\u024F'’-]*"
_BIO_START = re.compile(
    rf"\b({_NAME_WORD}(?:\s+[A-Z]\.)?\s+{_NAME_WORD})\s*[,:|\-–—]?\s+"
    r"(?=(?i:Vice President|Principal|Managing Director|Managing Partner|Operating Partner|"
    r"Partner|Director|Founder|Co-Founder|President|CFO|Associate|Analyst)\b)",
)
_NAV = (
    "about us",
    "our approach",
    "contact us",
    "investment criteria",
    "search funds",
    "privacy policy",
    "cookie",
    "skip to",
    "working with management",
    "working with sellers",
)
_NOT_A_PERSON = {
    "university",
    "college",
    "group",
    "capital",
    "partners",
    "fund",
    "foundation",
    "states",
    "state",
    "operations",
    "holdings",
    "ventures",
    "venture",
    "equity",
    "street",
    "avenue",
    "lane",
    "road",
    "drive",
    "court",
    "boulevard",
    "way",
    "place",
    "park",
    "team",
    "board",
    "conferences",
    "school",
    "institute",
    "battalion",
    "principal",
    "partner",
    "director",
    "president",
    "founder",
    "managing",
    "chief",
    "vice",
    "analyst",
    "associate",
    "officer",
    "fitness",
    "company",
    "inc",
    "llc",
    "consulting",
    "resources",
    "solutions",
    "systems",
    "services",
}
_RESUME = re.compile(
    r"\b(years of experience|series 7|series 63|finra|progressively senior)\b",
    re.IGNORECASE,
)

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
    r"family business|worked as|worked at|worked for|started a|started an|started my|"
    r"prior to|previously|before joining|before founding|served as|was the ceo|was ceo|"
    r"began his career|began her career|started his career|started her career)\b",
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
_WHY_PERSONAL = re.compile(r"\b(got into|left|because|started)\b", re.IGNORECASE)

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


def llm_keys_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip())


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"\s+", (full_name or "").strip()) if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1].strip(".,")


def _other_people(sentence: str, first: str, last: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(rf"\b({_NAME_WORD})\s+({_NAME_WORD})\b", sentence or ""):
        left, right = match.group(1), match.group(2)
        if len(left) < 3 or len(right) < 3:
            continue
        if right.lower() in _NOT_A_PERSON or left.lower() in _NOT_A_PERSON:
            continue
        if first and left.lower() == first.lower() and last and right.lower() == last.lower():
            continue
        found.append(f"{left} {right}")
    return found


def is_junk(text: str) -> bool:
    """Nav, menus, and lists of other people's names are not a life story."""
    if not text:
        return True
    lowered = text.lower()
    if sum(1 for phrase in _NAV if phrase in lowered) >= 2:
        return True
    return len(_other_people(text, "", "")) >= 3


def _heading_is_person(heading: str, first: str, last: str) -> bool:
    tokens = [re.sub(r"[^A-Za-z\u00C0-\u024F'’-]", "", token) for token in heading.split()]
    tokens = [token for token in tokens if token]
    if not tokens or not last:
        return False
    if tokens[-1].lower() != last.lower():
        return False
    if not first:
        return True
    return tokens[0].lower() == first.lower()


def _unique_last_name(first: str, text: str) -> str:
    """The only surname written next to this first name. Empty when none or several."""
    if not first or not text:
        return ""
    pattern = re.compile(rf"\b{re.escape(first)}\s+([A-Z][A-Za-z\u00C0-\u024F'’-]{{2,}})\b")
    found: list[str] = []
    for match in pattern.finditer(text):
        candidate = match.group(1)
        if candidate.lower() in _NOT_A_PERSON:
            continue
        if candidate.lower() not in {item.lower() for item in found}:
            found.append(candidate)
    if len(found) != 1:
        return ""
    return found[0]


def passage_for_identity(text: str, first: str, last: str) -> str:
    """Pick this person's bio. An initial last name is resolved only when one surname fits."""
    letters = re.sub(r"[^A-Za-z]", "", last or "")
    use_last = last
    if len(letters) <= 1:
        use_last = _unique_last_name(first, text)
        if not use_last:
            return ""
    return bio_for(text, first, use_last)


def bio_for(text: str, first: str, last: str) -> str:
    """Keep the block under this person's heading. Drop the rest of a team page."""
    matches = list(_BIO_START.finditer(text or ""))
    if not matches:
        if is_junk(text):
            return ""
        if _mentions(text, last) and (not first or _mentions(text, first)) and not _other_people(text, first, last):
            return text
        return ""
    pieces: list[str] = []
    for index, match in enumerate(matches):
        start = match.start(1)
        end = matches[index + 1].start(1) if index + 1 < len(matches) else len(text)
        if _heading_is_person(match.group(1), first, last):
            pieces.append(text[start:end])
    return " ".join(pieces).strip()


def passage_for_source(source: dict[str, str], first: str, last: str) -> str:
    title = source.get("title") or source.get("name") or ""
    text = source.get("text") or source.get("transcript") or source.get("description") or ""
    kind = (source.get("kind") or "").lower()
    titled = _mentions(title, last) and (not first or _mentions(title, first))
    if kind in {"interview", "podcast", "transcript"} and titled:
        # Sentence filters still drop other people. A real interview names more than one person.
        return "" if is_junk(text) and not _mentions(text, last) else text
    if kind == "interview" and "linkedin" in (source.get("url") or "").lower():
        if is_junk(text) or _other_people(text, first, last):
            return ""
        return text if _mentions(text, last) else ""
    return bio_for(text, first, last)


def _opens_with_person(text: str, first: str, last: str) -> bool:
    """A split bio starts with the person's name. Later sentences often use only the first name."""
    opening = (text or "")[:120]
    if not first or not last:
        return False
    return _mentions(opening, first) and _mentions(opening, last)


def _sentence_about(sentence: str, first: str, last: str, passage_is_theirs: bool) -> bool:
    if _blocked(sentence) or is_junk(sentence):
        return False
    if _mentions(sentence, last):
        return True
    if passage_is_theirs and first and _mentions(sentence, first):
        return True
    if passage_is_theirs and _ABOUT.search(sentence) and not _other_people(sentence, first, last):
        return True
    return False


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


def _usable_passages(full_name: str, sources: list[dict[str, str]]) -> list[dict[str, str]]:
    first, last = _split_name(full_name)
    passages: list[dict[str, str]] = []
    for source in sources:
        text = passage_for_source(source, first, last)
        if not text:
            continue
        passages.append(
            {
                "url": source.get("url") or "",
                "title": source.get("title") or source.get("name") or "",
                "text": text,
                "kind": source.get("kind") or "",
            }
        )
    return passages


def _heuristic_from_passages(full_name: str, passages: list[dict[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    first, last = _split_name(full_name)
    found: dict[str, str] = {key: "" for key in (*_LIFE_KEYS, "why")}
    cites: dict[str, str] = {}
    for source in passages:
        url = source.get("url") or ""
        titled = _mentions(source.get("title") or "", last) and (not first or _mentions(source.get("title") or "", first))
        passage_is_theirs = titled or _opens_with_person(source.get("text") or "", first, last)
        for sentence in _sentences(source.get("text") or ""):
            about = _sentence_about(sentence, first, last, passage_is_theirs)
            resume_only = bool(_RESUME.search(sentence)) and not (
                _HOMETOWN.search(sentence)
                or _FAMILY.search(sentence)
                or _MILITARY.search(sentence)
                or _COLLEGE.search(sentence)
            )
            clipped = _clip(sentence)

            def consider(key: str, matched: Any, value: str = clipped) -> None:
                if not matched or found.get(key):
                    return
                if not about:
                    if is_junk(sentence):
                        reject("junk")
                    elif _other_people(sentence, first, last):
                        reject("other_person")
                    else:
                        reject("not_about_person")
                    return
                if resume_only and key not in {"hometown", "family_background", "military_service", "college"}:
                    reject("resume_only")
                    return
                _take(found, cites, key, True, value, url)
                if found.get(key):
                    keep_fact()

            consider("hometown", _HOMETOWN.search(sentence) and not _FIRM_VOICE.search(sentence))
            consider("family_background", _FAMILY.search(sentence))
            consider("college", _COLLEGE.search(sentence))
            consider("military_service", _MILITARY.search(sentence))
            consider("early_jobs", _EARLY.search(sentence))
            consider("causes", _CAUSES.search(sentence))
            consider("life_events", _EVENTS.search(sentence))
            consider("why", _WHY.search(sentence) and (_FIRST_PERSON.search(sentence) or _WHY_PERSONAL.search(sentence)))
            if _quote_ok(source):
                quoted = _QUOTE.search(sentence)
                if quoted and _sentence_about(quoted.group(1), first, last, True):
                    consider("quotes", True, _clip(quoted.group(1)))
    return found, cites


def _ground_quote(value: str, corpus: str) -> str:
    quote = re.sub(r"\s+", " ", (value or "")).strip().strip("\"'")
    if len(quote) < 12:
        return ""
    compact = re.sub(r"\s+", " ", corpus or "")
    if quote in compact:
        return quote
    index = compact.lower().find(quote.lower())
    if index < 0:
        return ""
    return compact[index : index + len(quote)]


def _cite_for(quote: str, passages: list[dict[str, str]]) -> str:
    folded = re.sub(r"\s+", " ", quote).lower()
    for source in passages:
        if folded in re.sub(r"\s+", " ", source.get("text") or "").lower():
            return source.get("url") or ""
    return ""


def _llm_fill(full_name: str, firm: str, passages: list[dict[str, str]], found: dict[str, str], cites: dict[str, str]) -> None:
    if not passages or not llm_keys_present():
        return
    first, last = _split_name(full_name)
    blocks = []
    for source in passages[:6]:
        blocks.append(f"URL: {source.get('url') or ''}\n{(source.get('text') or '')[:2500]}")
    prompt = (
        f"Extract personal facts for a handwritten letter about {full_name}"
        + (f" at {firm}" if firm else "")
        + ".\n"
        f"Use only facts explicitly about {full_name}. Ignore coworkers, menus, and lists of other people.\n"
        "Every value must be a verbatim quote copied from the sources. If you are not sure, use an empty string.\n"
        "Do not infer, summarize, or combine facts. No home addresses.\n"
        "Return JSON with keys hometown, family_background, college, military_service, early_jobs, why, causes, life_events, quotes.\n"
        "Sources:\n" + "\n\n".join(blocks)
    )
    cfg = replace(
        default_settings,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
    )
    note("llm_calls")
    provider = "anthropic" if cfg.anthropic_api_key else "openai"
    logger.info("pe llm_call provider=%s", provider)
    parsed = llm_extract(prompt, settings=cfg) or {}
    if not any(str(parsed.get(key) or "").strip() for key in (*_LIFE_KEYS, "why")):
        reject("llm_empty")
        return
    corpus = "\n".join(source.get("text") or "" for source in passages)
    for key in (*_LIFE_KEYS, "why"):
        if found.get(key):
            continue
        raw_value = str(parsed.get(key) or "").strip()
        if not raw_value:
            continue
        grounded = _ground_quote(raw_value, corpus)
        if not grounded:
            reject("not_grounded")
            continue
        if is_junk(grounded):
            reject("junk")
            continue
        if not _sentence_about(grounded, first, last, True):
            reject("not_about_person")
            continue
        found[key] = _clip(grounded)
        keep_fact()
        url = _cite_for(grounded, passages)
        if url:
            cites[key] = url


def extract_life_story(
    full_name: str,
    sources: list[dict[str, str]],
    *,
    firm: str = "",
) -> dict[str, str]:
    """Copy sentences from the named person's own passage. Never paraphrase."""
    passages = _usable_passages(full_name, sources)
    found, cites = _heuristic_from_passages(full_name, passages)
    _llm_fill(full_name, firm, passages, found, cites)
    out = _blank()
    out.update(found)
    filled = [key for key in _LIFE_KEYS if found[key]]
    if len(filled) >= 3:
        out["confidence"] = "high"
    elif filled:
        out["confidence"] = "medium"
    story = []
    for key in _HOOK_ORDER:
        value = found.get(key) or ""
        if value and value not in story:
            story.append(value)
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
    if not llm_keys_present():
        out["research_note"] = f"{RESEARCH_NOTE} {NO_MODEL_WARNING}"
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


_SKIP_FETCH_HOSTS = {
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
}


def _skip_fetch(url: str) -> bool:
    host = host_key(url)
    return any(host == blocked or host.endswith("." + blocked) for blocked in _SKIP_FETCH_HOSTS)


def _bio_paths(first: str, last: str) -> list[str]:
    paths = list(TEAM_PATHS) + ["/about-us", "/professionals", "/our-people"]
    if first and last and len(re.sub(r"[^A-Za-z]", "", last)) > 1:
        slug = re.sub(r"[^a-z-]", "", f"{first}-{last}".lower())
        if slug:
            paths.extend((f"/team/{slug}", f"/people/{slug}", f"/leadership/{slug}"))
    return paths


def _has_bio(sources: list[dict[str, str]]) -> bool:
    return any(source.get("kind") == "bio" and source.get("text") for source in sources)


def gather_person_sources(row: dict[str, str]) -> list[dict[str, str]]:
    """Firm bios found from the site's own links or web search, plus interviews."""
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    full = row.get("full_name") or ""
    last = row.get("last_name") or last_name_of(full)
    first = row.get("first_name") or _split_name(full)[0]
    firm = row.get("company_name") or ""
    domain = row.get("company_domain") or ""
    base = company_url(row.get("company_website") or "", domain)

    def store(url: str, title: str, text: str, kind: str) -> None:
        passage = passage_for_source(
            {"url": url, "title": title, "text": text, "kind": kind},
            first,
            last,
        )
        if not passage:
            return
        sources.append({"url": url, "title": title, "text": passage[:8000], "kind": kind})
        note("pages_kept")

    def fetch_unique(url: str) -> tuple[str, str]:
        key = (url or "").split("#")[0].rstrip("/")
        if not key or key in seen or _skip_fetch(url):
            return "", ""
        seen.add(key)
        try:
            return fetch_document(url)
        except Exception:
            logger.exception("page fetch failed")
            return "", ""

    if base and last:
        home_html, _home_text = fetch_unique(base)
        discovered = candidate_bio_urls(home_html, base, first, last)
        guessed = [urljoin(base + "/", path.lstrip("/")) for path in _bio_paths(first, last)]
        queue: list[str] = []
        queued: set[str] = set()
        for url in discovered + guessed:
            key = url.split("#")[0].rstrip("/")
            if key not in queued:
                queued.add(key)
                queue.append(url)
        fetched = 0
        while queue and fetched < 8 and not _has_bio(sources):
            url = queue.pop(0)
            html, text = fetch_unique(url)
            fetched += 1
            if not text:
                continue
            before = len(sources)
            store(url, f"{firm} bio", text, "bio")
            if len(sources) == before:
                for extra in candidate_bio_urls(html, url, first, last):
                    key = extra.split("#")[0].rstrip("/")
                    if key not in queued and key not in seen:
                        queued.add(key)
                        queue.append(extra)

    _add_search_pages(
        full,
        firm,
        domain,
        base,
        first,
        last,
        store,
        fetch_unique,
        need_bio=not _has_bio(sources),
    )

    try:
        talks = talks_with_transcripts(full, firm, max_videos=2)
    except Exception:
        logger.exception("youtube lookup failed")
        talks = []
    for talk in talks:
        text = talk.get("transcript") or talk.get("description") or ""
        title = str(talk.get("title") or "")
        if text and _mentions(f"{title} {text}", last):
            store(str(talk.get("url") or ""), title, str(text)[:12000], "interview")
    try:
        episodes = search_episodes(f"{full} {firm}".strip())[:3]
    except Exception:
        logger.exception("podcast lookup failed")
        episodes = []
    for episode in episodes:
        title = str(episode.get("name") or "")
        text = f"{title} {episode.get('description') or ''}"
        if _mentions(text, last):
            store(str(episode.get("audioUrl") or ""), title, text[:8000], "podcast")
    if _thin(sources) and row.get("linkedin_url"):
        try:
            posts = linkedin_posts(row["linkedin_url"])
        except Exception:
            logger.exception("linkedin posts lookup failed")
            posts = []
        for post in posts:
            text = _post_text(post)
            if text and _mentions(text, last):
                store(
                    str(post.get("url") or post.get("postUrl") or row.get("linkedin_url") or ""),
                    "LinkedIn post",
                    text[:4000],
                    "interview",
                )
    return sources


def _add_search_pages(
    full: str,
    firm: str,
    domain: str,
    base: str,
    first: str,
    last: str,
    store: Any,
    fetch_unique: Any,
    *,
    need_bio: bool,
) -> None:
    """Find the bio page and interviews. Apify Google search when a key is set."""
    if not full:
        return
    queries: list[str] = []
    host = host_key(base) or (domain or "").lower().removeprefix("www.")
    if need_bio and host:
        queries.append(f'site:{host} "{full}"')
    if firm:
        queries.append(f'"{full}" "{firm}" interview')
    elif full:
        queries.append(f'"{full}" interview')
    fetched = 0
    for query in queries:
        try:
            results = google_search(query)
        except Exception:
            logger.exception("web search failed")
            results = []
        for result in results:
            if fetched >= 4:
                return
            url = result.get("url") or ""
            if not url or _skip_fetch(url):
                continue
            title = result.get("title") or ""
            kind = "interview" if re.search(r"interview|podcast", f"{title} {url}", re.IGNORECASE) else "bio"
            if not need_bio and kind == "bio" and host and host_key(url) == host:
                continue
            _html, text = fetch_unique(url)
            fetched += 1
            if text:
                store(url, title or firm or "search", text, kind)
            elif result.get("description") and _mentions(result["description"], last):
                store(url, title or "search", result["description"], kind)
