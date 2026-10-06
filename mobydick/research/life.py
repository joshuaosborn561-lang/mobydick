"""Cited personal facts for PE letters. Empty when a source does not say it."""

from __future__ import annotations

import html
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
from mobydick.research.trace import drop_page, keep_fact, note, reject
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
    "operations",
    "associates",
    "securities",
    "bank",
    "banking",
    "trust",
    "committee",
    "properties",
    "natural",
    "energy",
    "media",
    "communications",
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
    r"\b(college|university|varsity|bachelor|alumnus|alumna|mba|m\.b\.a|b\.a|b\.s|undergraduate)\b|"
    r"\bplayed\b.{0,40}\b(at|for)\b",
    re.IGNORECASE,
)
_MILITARY = re.compile(
    r"\b(navy|army|marines|marine corps|air force|coast guard|veteran|west point|served in the)\b",
    re.IGNORECASE,
)
_EMPLOYER = re.compile(
    r"\b("
    r"prior to|before joining|before founding|"
    r"worked at|worked for|worked as|first job|"
    r"food truck|restaurant|"
    r"began (?:his|her|their) career|started (?:his|her|their) career|"
    r"spent\s+\w+(?:\s+\w+){0,5}\s+(?:at|with)|"
    r"was (?:a |an |the )?(?:(?:co-|co )?(?:managing|operating) )?"
    r"(?:director|partner|principal|ceo|president|founder|analyst|associate|banker) (?:at|with|of)|"
    r"served as (?:a |an |the )?(?:(?:co-|co )?(?:managing|operating) )?"
    r"(?:director|partner|principal|ceo|president|founder)"
    r")\b",
    re.IGNORECASE,
)
_CORPORATE_BOARD = re.compile(
    r"\b(board of directors|serves on the board|served on the board|board seat|"
    r"member of the board|on the board of)\b",
    re.IGNORECASE,
)
_CAUSES = re.compile(
    r"\b(nonprofit|non-profit|foundation|charity|charitable|faith|church|synagogue|mosque|philanthrop)\b",
    re.IGNORECASE,
)
_ATHLETICS = re.compile(
    r"\b(varsity|athlete|lettered|football|basketball|soccer|baseball|hockey|lacrosse|"
    r"wrestl\w*|swimmer|track and field)\b|"
    r"\bplayed\b.{0,40}\b(?:at|for|on)\b",
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
_STORY_ORDER = (
    "hometown",
    "family_background",
    "military_service",
    "life_events",
    "causes",
    "college",
    "early_jobs",
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


def _decode(text: str) -> str:
    return html.unescape(text or "")


def _clip(text: str, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", _decode(text)).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _is_personal_text(text: str) -> bool:
    if not text:
        return False
    if _HOMETOWN.search(text) and _FIRM_VOICE.search(text) and not any(
        pattern.search(text) for pattern in (_FAMILY, _MILITARY, _ATHLETICS, _EVENTS, _CAUSES)
    ):
        return False
    if _HOMETOWN.search(text) and not _FIRM_VOICE.search(text):
        return True
    return any(pattern.search(text) for pattern in (_FAMILY, _MILITARY, _ATHLETICS, _EVENTS, _CAUSES))


def _is_employer(sentence: str) -> bool:
    """Prior employers and roles. A corporate board seat is not an early job."""
    if not _EMPLOYER.search(sentence or ""):
        return False
    if _MILITARY.search(sentence) and not re.search(
        r"\b(worked at|worked for|first job|spent\s+\w+)\b",
        sentence,
        re.IGNORECASE,
    ):
        return False
    if _CORPORATE_BOARD.search(sentence) and not re.search(
        r"\b(prior to|worked at|worked for|first job|spent\s+\w+)\b",
        sentence,
        re.IGNORECASE,
    ):
        return False
    return True


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


def _bare_people(text: str) -> list[tuple[int, str]]:
    """Name headings that are not glued to a title word. Skip mid-sentence pairs."""
    pattern = re.compile(rf"\b({_NAME_WORD}(?:\s+[A-Z]\.)?\s+{_NAME_WORD})\b")
    hits: list[tuple[int, str]] = []
    for match in pattern.finditer(text or ""):
        heading = match.group(1)
        tokens = [re.sub(r"[^A-Za-z\u00C0-\u024F'’-]", "", token) for token in heading.split()]
        tokens = [token for token in tokens if token]
        if not tokens or any(len(token.strip(".")) < 2 for token in tokens):
            continue
        if any(token.lower().strip(".") in _NOT_A_PERSON for token in tokens):
            continue
        prev = (text[: match.start()] or "").rstrip()
        if prev and prev[-1] not in ".!?":
            continue
        hits.append((match.start(1), heading))
    return hits


def _harvest_sentences(text: str, first: str, last: str) -> str:
    kept = [sentence for sentence in _sentences(text) if _sentence_about(sentence, first, last, False)]
    return " ".join(kept).strip()


def bio_for(text: str, first: str, last: str) -> str:
    """Keep the block under this person's heading. Drop the rest of a team page."""
    text = _decode(text)
    matches = list(_BIO_START.finditer(text or ""))
    if matches:
        pieces: list[str] = []
        for index, match in enumerate(matches):
            start = match.start(1)
            end = matches[index + 1].start(1) if index + 1 < len(matches) else len(text)
            if _heading_is_person(match.group(1), first, last):
                pieces.append(text[start:end])
        return " ".join(pieces).strip()
    bare = _bare_people(text)
    if bare:
        pieces = []
        for index, (start, heading) in enumerate(bare):
            end = bare[index + 1][0] if index + 1 < len(bare) else len(text)
            if _heading_is_person(heading, first, last):
                pieces.append(text[start:end])
        if pieces:
            return " ".join(pieces).strip()
        if len(bare) >= 2:
            return ""
    if _opens_with_person(text, first, last) and not is_junk(text) and len(_other_people(text, first, last)) < 2:
        return text
    if is_junk(text) and not _mentions(text, last):
        return ""
    if _mentions(text, last):
        harvested = _harvest_sentences(text, first, last)
        if harvested:
            return harvested
    if is_junk(text):
        return ""
    if _mentions(text, last) and (not first or _mentions(text, first)) and not _other_people(text, first, last):
        return text
    return ""


def passage_for_source(source: dict[str, str], first: str, last: str) -> str:
    title = source.get("title") or source.get("name") or ""
    text = _decode(source.get("text") or source.get("transcript") or source.get("description") or "")
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
    opening = (text or "")[:160]
    if last and re.search(rf"\b(?:Mr|Ms|Mrs|Dr)\.?\s+{re.escape(last)}\b", opening, re.IGNORECASE):
        return True
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


def _spoken_quote(sentence: str) -> str:
    """First-person words inside quotation marks. A third-person blurb is not a quote."""
    quoted = _QUOTE.search(sentence or "")
    if not quoted:
        return ""
    inner = quoted.group(1).strip()
    if not _FIRST_PERSON.search(inner):
        return ""
    return inner


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
            resume_only = bool(_RESUME.search(sentence)) and not _is_personal_text(sentence)
            clipped = _clip(sentence)
            slots: list[tuple[str, str]] = []
            if _HOMETOWN.search(sentence) and not _FIRM_VOICE.search(sentence):
                slots.append(("hometown", clipped))
            if _FAMILY.search(sentence):
                slots.append(("family_background", clipped))
            if _COLLEGE.search(sentence):
                slots.append(("college", clipped))
            if _MILITARY.search(sentence):
                slots.append(("military_service", clipped))
            if _is_employer(sentence):
                slots.append(("early_jobs", clipped))
            if _CAUSES.search(sentence):
                slots.append(("causes", clipped))
            if _EVENTS.search(sentence):
                slots.append(("life_events", clipped))
            if _WHY.search(sentence) and (_FIRST_PERSON.search(sentence) or _WHY_PERSONAL.search(sentence)):
                slots.append(("why", clipped))
            spoken = _spoken_quote(sentence) if _quote_ok(source) else ""
            if spoken and _sentence_about(spoken, first, last, True):
                slots.append(("quotes", _clip(spoken)))
            if not slots:
                continue
            if not about:
                if is_junk(sentence):
                    reject("junk")
                elif _other_people(sentence, first, last):
                    reject("other_person")
                else:
                    reject("not_about_person")
                continue
            for key, value in slots:
                if found.get(key):
                    continue
                if resume_only and key not in {"hometown", "family_background", "military_service", "college", "quotes"}:
                    reject("resume_only")
                    continue
                _take(found, cites, key, True, value, url)
                if found.get(key):
                    keep_fact()
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


def _fits_field(key: str, text: str) -> bool:
    if key == "quotes":
        return bool(_FIRST_PERSON.search(text))
    if key == "early_jobs":
        return _is_employer(text)
    if key == "causes":
        return bool(_CAUSES.search(text))
    if key == "hometown":
        return bool(_HOMETOWN.search(text) and not _FIRM_VOICE.search(text))
    if key == "college":
        return bool(_COLLEGE.search(text))
    if key == "military_service":
        return bool(_MILITARY.search(text))
    if key == "family_background":
        return bool(_FAMILY.search(text))
    if key == "life_events":
        return bool(_EVENTS.search(text) or _ATHLETICS.search(text))
    if key == "why":
        return bool(_WHY.search(text))
    return False


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
        "Put each fact in exactly one field. early_jobs means prior employers and roles, not a board seat.\n"
        "causes means a nonprofit, charity, faith, or philanthropy, not a portfolio company board.\n"
        "quotes must be first-person words the person said. Do not quote a third-person description.\n"
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
        if not _fits_field(key, grounded):
            reject("wrong_field")
            continue
        if any(grounded == existing for existing in found.values() if existing):
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
    personal: list[str] = []
    for key in _STORY_ORDER:
        value = found.get(key) or ""
        if value and _is_personal_text(value) and value not in personal:
            personal.append(value)
    if len(personal) >= 3:
        out["confidence"] = "high"
    elif personal:
        out["confidence"] = "medium"
    out["real_story"] = " ".join(personal[:3])
    out["hook"] = personal[0] if personal else ""
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


def _name_slugs(full: str, first: str, last: str) -> list[str]:
    parts = [re.sub(r"[^A-Za-z]", "", part) for part in re.split(r"\s+", (full or "").strip()) if part]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        if first and last:
            parts = [first, last]
        else:
            return []
    if len(re.sub(r"[^A-Za-z]", "", parts[-1])) <= 1:
        return []
    first_s = re.sub(r"[^a-z]", "", parts[0].lower())
    last_s = re.sub(r"[^a-z]", "", parts[-1].lower())
    if not first_s or not last_s:
        return []
    slugs = [f"{first_s}-{last_s}"]
    if len(parts) >= 3:
        mid = re.sub(r"[^a-z]", "", parts[1].lower())
        if mid:
            slugs.append(f"{first_s}-{mid}-{last_s}")
            if len(mid) > 1:
                slugs.append(f"{first_s}-{mid[0]}-{last_s}")
    return slugs


def _bio_paths(full: str, first: str, last: str) -> list[str]:
    paths = list(TEAM_PATHS) + [
        "/about-us",
        "/professionals",
        "/our-people",
        "/team.php",
        "/people.php",
        "/our-team.php",
    ]
    for slug in _name_slugs(full, first, last):
        paths.extend((f"/team/{slug}", f"/people/{slug}", f"/leadership/{slug}"))
    return paths


_SUBSTANCE = re.compile(
    r"\b(university|college|mba|bachelor|prior to|previously|worked at|worked for|grew up|"
    r"born|hometown|nonprofit|army|navy|marines|career|alumni)\b",
    re.IGNORECASE,
)


def _substantive_text(text: str) -> bool:
    return bool(_SUBSTANCE.search(text or ""))


def _has_substantive_bio(sources: list[dict[str, str]]) -> bool:
    return any(source.get("kind") == "bio" and _substantive_text(source.get("text") or "") for source in sources)


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
            if is_junk(text):
                drop_page("junk")
            else:
                drop_page("no_person_passage")
            return
        sources.append({"url": url, "title": title, "text": passage[:8000], "kind": kind})
        note("pages_kept")

    def fetch_unique(url: str) -> tuple[str, str]:
        key = (url or "").split("#")[0].rstrip("/")
        if not key or _skip_fetch(url):
            if url:
                drop_page("skipped_host")
            return "", ""
        if key in seen:
            drop_page("duplicate")
            return "", ""
        seen.add(key)
        try:
            html, text = fetch_document(url)
        except Exception:
            logger.exception("page fetch failed")
            drop_page("empty_page")
            return "", ""
        if not text:
            drop_page("empty_page")
        return html, text

    def enqueue(urls: list[str], *, front: bool) -> None:
        ordered = list(reversed(urls)) if front else list(urls)
        for url in ordered:
            key = (url or "").split("#")[0].rstrip("/")
            if not key or key in queued or key in seen:
                continue
            queued.add(key)
            if front:
                queue.insert(0, url)
            else:
                queue.append(url)

    def person_link(url: str) -> bool:
        if not last or not re.search(rf"\b{re.escape(last)}\b", url, re.IGNORECASE):
            return False
        if first and not re.search(rf"\b{re.escape(first)}\b", url, re.IGNORECASE):
            return False
        return True

    if base and last:
        home_html, _home_text = fetch_unique(base)
        discovered = candidate_bio_urls(home_html, base, first, last)
        guessed = [urljoin(base + "/", path.lstrip("/")) for path in _bio_paths(full, first, last)]
        queue: list[str] = []
        queued: set[str] = set()
        enqueue(discovered + guessed, front=False)
        attempts = 0
        while queue and attempts < 14 and not _has_substantive_bio(sources):
            url = queue.pop(0)
            html, text = fetch_unique(url)
            attempts += 1
            if not text:
                continue
            store(url, f"{firm} bio", text, "bio")
            extras = candidate_bio_urls(html, url, first, last)
            named = [extra for extra in extras if person_link(extra)]
            rest = [extra for extra in extras if extra not in named]
            enqueue(named, front=True)
            enqueue(rest, front=False)

    _add_search_pages(
        full,
        firm,
        domain,
        base,
        first,
        last,
        store,
        fetch_unique,
        have_bio=_has_substantive_bio(sources),
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


def _search_queries(full: str, firm: str, host: str) -> list[str]:
    """Site bio plus interviews, alumni, and personal-life terms. A few queries, not one per word."""
    queries: list[str] = []
    if host:
        queries.append(f'site:{host} "{full}"')
    who = f'"{full}" "{firm}"' if firm else f'"{full}"'
    queries.append(f"{who} (podcast OR interview OR alumni OR speaker)")
    queries.append(f'{who} ("grew up" OR hometown OR family OR veteran OR athlete OR charity)')
    return queries


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
    have_bio: bool,
) -> None:
    """Find the bio page and the person's own interviews. Apify Google search when a key is set."""
    if not full:
        return
    host = host_key(base) or (domain or "").lower().removeprefix("www.")
    queries = _search_queries(full, firm, host)
    fetched = 0
    for query in queries:
        try:
            results = google_search(query)
        except Exception:
            logger.exception("web search failed")
            results = []
        per_query = 0
        for result in results:
            if fetched >= 6 or per_query >= 3:
                break
            url = result.get("url") or ""
            if not url:
                continue
            title = result.get("title") or ""
            blob = f"{title} {url}"
            personalish = re.search(
                r"interview|podcast|alumni|speaker|hometown|charity|news",
                blob,
                re.IGNORECASE,
            )
            kind = "interview" if personalish else "bio"
            if have_bio and kind == "bio" and host and host_key(url) == host:
                continue
            if _skip_fetch(url):
                drop_page("skipped_host")
                continue
            _html, text = fetch_unique(url)
            fetched += 1
            per_query += 1
            if text:
                store(url, title or firm or "search", text, kind)
            elif result.get("description") and _mentions(result["description"], last):
                store(url, title or "search", result["description"], kind)
