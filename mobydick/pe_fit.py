"""PE audience screen. US deal partners at real PE firms only."""

from __future__ import annotations

import re

KEEP_FIRM_TYPES = ("private equity", "growth equity", "buyout")

_JUNIOR_TOKENS = {"associate", "analyst", "assistant", "intern", "coordinator"}
_JUNIOR_PHRASES = (("office", "manager"), ("executive", "assistant"))

_NON_DEAL_TOKENS = {
    "economist",
    "research",
    "cyber",
    "cybersecurity",
    "credit",
    "counsel",
    "recruiter",
    "recruiting",
    "marketing",
    "compliance",
    "ir",
    "cfo",
    "finance",
    "data",
    "analytics",
    "operations",
    "talent",
    "venture",
}
_NON_DEAL_PHRASES = (
    ("investor", "relations"),
    ("investor", "relation"),
    ("portfolio", "technology"),
    ("portfolio", "data"),
    ("portfolio", "ai"),
    ("head", "of", "data"),
    ("head", "of", "ai"),
    ("head", "of", "technology"),
    ("head", "of", "talent"),
    ("information", "security"),
    ("capital", "markets"),
    ("investment", "banking"),
    ("investment", "banker"),
    ("human", "resources"),
    ("chief", "of", "staff"),
    ("chief", "technology"),
    ("chief", "data"),
    ("chief", "information"),
    ("chief", "financial"),
    ("chief", "financial", "officer"),
)

_REGION_TOKENS = {
    "europe",
    "european",
    "apac",
    "emea",
    "latam",
    "japan",
    "china",
    "india",
    "singapore",
    "london",
    "canada",
    "australia",
    "asia",
    "africa",
    "germany",
    "france",
    "mexico",
    "brazil",
    "korea",
    "uae",
    "dubai",
    "uk",
}
_REGION_PHRASES = (
    ("united", "kingdom"),
    ("hong", "kong"),
    ("latin", "america"),
    ("middle", "east"),
)

_PARTNER_TOKENS = {"partner", "principal", "founder", "cofounder"}
_PARTNER_PHRASES = (("managing", "director"), ("operating", "partner"))

_US_STATE_WORDS = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "wisconsin",
    "wyoming",
}
_US_STATE_PHRASES = (
    ("new", "hampshire"),
    ("new", "jersey"),
    ("new", "mexico"),
    ("new", "york"),
    ("north", "carolina"),
    ("north", "dakota"),
    ("south", "carolina"),
    ("south", "dakota"),
    ("west", "virginia"),
    ("rhode", "island"),
    ("district", "of", "columbia"),
)
_STATE_ABBR = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}

_FOREIGN_TOKENS = _REGION_TOKENS | {
    "netherlands",
    "sweden",
    "spain",
    "italy",
    "ireland",
    "switzerland",
    "israel",
    "belgium",
    "taiwan",
}
_FOREIGN_CITIES = {
    "tokyo",
    "osaka",
    "kyoto",
    "seoul",
    "beijing",
    "shanghai",
    "shenzhen",
    "mumbai",
    "delhi",
    "sydney",
    "melbourne",
    "paris",
    "berlin",
    "munich",
    "frankfurt",
    "zurich",
    "geneva",
    "amsterdam",
    "stockholm",
    "madrid",
    "barcelona",
    "milan",
    "rome",
    "dublin",
    "toronto",
    "vancouver",
    "montreal",
    "brussels",
    "singapore",
    "dubai",
    "london",
}

_ADVISORY = re.compile(
    r"\b(?:advis(?:e|es|ing)(?:\s+on)?|serv(?:e|es|ing)|works?\s+with)\s+"
    r"(?:private equity|growth equity|buyouts?)\b"
    r"(?:\s+(?:clients?|sponsors?|firms?|funds?|investors?))?",
    re.IGNORECASE,
)
_PE_CLIENTS = re.compile(
    r"\b(?:private equity|growth equity)\s+(?:clients?|sponsors?|investors?)\b",
    re.IGNORECASE,
)
_FOR_PE = re.compile(
    r"\b(?:for|to)\s+(?:private equity|growth equity)\s+firms\b",
    re.IGNORECASE,
)
_BUYOUT = re.compile(r"\b(?:buyouts?|leveraged buyout|lbo)\b", re.IGNORECASE)
_GROWTH = re.compile(r"\bgrowth[ -]?equity\b", re.IGNORECASE)
_PE = re.compile(
    r"\b(?:private equity (?:firm|fund|funds|partnership|group|sponsor)|"
    r"independent sponsor|"
    r"(?:focused on|speciali[sz]\w+ in|invest\w+ in) private equity)\b",
    re.IGNORECASE,
)
_BROKER = re.compile(
    r"\b(?:broker-dealer|broker dealer|finra|series 7|series 63|registered representative)\b",
    re.IGNORECASE,
)
_VC_FIRM = re.compile(r"\b(?:venture capital|venture fund|vc fund)\b", re.IGNORECASE)
_VC_IDENTITY = re.compile(
    r"\bearly[- ]stage venture\b|"
    r"\bventure capital(?:\s+firm|\s+fund)?\b|"
    r"\bpre-seed\b|\bpreseed\b|"
    r"\bseed[- ](?:stage|fund)\b|"
    r"\bearly[- ]stage (?:investor|fund)\b|"
    r"\bventure fund\b",
    re.IGNORECASE,
)
_NAMED_FIRM = re.compile(
    r"\b(?:private equity|buyout|growth equity)\s+(?:firm|fund|funds|partnership)\b",
    re.IGNORECASE,
)
_BANK = re.compile(
    r"\b(?:investment bank|investment banking|m\s*&\s*a advisory|"
    r"sell-side advisor|sell side advisor|capital markets advisory)\b",
    re.IGNORECASE,
)
_RISK = re.compile(
    r"\b(?:risk advisory|risk consulting|corporate investigations|investigations firm)\b",
    re.IGNORECASE,
)
_VC = re.compile(r"\bventure capital\b", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _phrase(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    if width == 1:
        return phrase[0] in tokens
    for index in range(len(tokens) - width + 1):
        if tuple(tokens[index : index + width]) == phrase:
            return True
    return False


def _any_phrase(tokens: list[str], phrases: tuple[tuple[str, ...], ...]) -> bool:
    return any(_phrase(tokens, phrase) for phrase in phrases)


def title_reason(title: str) -> str:
    """Blank when the title is a US deal-partner role. Otherwise a dq code."""
    tokens = _tokens(title)
    if not tokens:
        return "not_partner_grade"
    if any(token in _JUNIOR_TOKENS for token in tokens) or _any_phrase(tokens, _JUNIOR_PHRASES):
        return "junior_title"
    if any(token in _NON_DEAL_TOKENS for token in tokens) or _any_phrase(tokens, _NON_DEAL_PHRASES):
        return "non_deal_role"
    if any(token in _REGION_TOKENS for token in tokens) or _any_phrase(tokens, _REGION_PHRASES):
        return "non_us_role"
    if any(token in _PARTNER_TOKENS for token in tokens) or _any_phrase(tokens, _PARTNER_PHRASES):
        return ""
    return "not_partner_grade"


def _letters_only(value: str) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())


def _is_us_country(value: str) -> bool:
    return _letters_only(value) in {"unitedstates", "unitedstatesofamerica", "usa", "us", "america"}


def _comma_parts(location: str) -> list[str]:
    return [part.strip().lower().rstrip(".") for part in (location or "").split(",") if part.strip()]


def _has_us_state(location: str) -> bool:
    tokens = _tokens(location)
    if any(token in _US_STATE_WORDS for token in tokens):
        return True
    if _any_phrase(tokens, _US_STATE_PHRASES):
        return True
    return any(part in _STATE_ABBR for part in _comma_parts(location))


def _has_foreign_place(location: str) -> bool:
    tokens = _tokens(location)
    parts = _comma_parts(location)
    foreign_country = (
        any(token in _FOREIGN_TOKENS for token in tokens)
        or _phrase(tokens, ("united", "kingdom"))
        or _phrase(tokens, ("hong", "kong"))
        or any(part in {"uk", "u.k", "japan", "china", "prc"} for part in parts)
    )
    if foreign_country and not _has_us_state(location):
        return True
    # Paris, TX and London, KY are US places. Tokyo alone is not.
    if _has_us_state(location):
        return False
    return any(token in _FOREIGN_CITIES for token in tokens) or any(part in _FOREIGN_CITIES for part in parts)


def _location_is_us(location: str) -> bool:
    if _is_us_country(location):
        return True
    tokens = _tokens(location)
    if "united" in tokens and "states" in tokens:
        return True
    if any(token in _US_STATE_WORDS for token in tokens):
        return True
    if _any_phrase(tokens, _US_STATE_PHRASES):
        return True
    parts = _comma_parts(location)
    if any(part in _STATE_ABBR for part in parts):
        return True
    return any(part in {"us", "usa", "u.s", "u.s.a"} for part in parts)


def person_is_us(country: str, location: str) -> bool:
    if _has_foreign_place(location):
        return False
    if _is_us_country(country):
        return True
    if (country or "").strip():
        return False
    return _location_is_us(location)


def hq_is_us(country: str) -> bool:
    return _is_us_country(country)


def _strip_advisory(text: str) -> str:
    cleaned = _ADVISORY.sub(" ", text)
    cleaned = _PE_CLIENTS.sub(" ", cleaned)
    cleaned = _FOR_PE.sub(" ", cleaned)
    return cleaned


def _same_org(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def firm_text_is_venture(text: str) -> bool:
    """The firm itself is venture. A person who left venture capital is not."""
    if not text:
        return False
    cleaned = re.sub(
        r"\b(?:left|leaving|departed|exited|after)\b.{0,48}\bventure\w*\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return _VC_IDENTITY.search(cleaned) is not None


def _looks_like_vc(name: str, description: str, domain: str) -> bool:
    host = (domain or "").lower().strip(".")
    if host.endswith(".vc"):
        return True
    blob = f"{name or ''} {description or ''}"
    if firm_text_is_venture(blob) or _VC_FIRM.search(blob):
        return True
    if re.search(r"\bventures?\b", name or "", re.IGNORECASE):
        if _NAMED_FIRM.search(description or ""):
            return False
        return True
    return False


def classify_firm(name: str, description: str, industry: str = "", domain: str = "") -> str:
    """Honest firm label. Unknown stays unknown. Never defaults to private equity."""
    blob = _strip_advisory(f"{name or ''} {description or ''}")
    industry_text = (industry or "").lower()
    if _FORM_D_VENTURE.search(f"{description or ''} {industry or ''}"):
        return "venture capital"
    if _BROKER.search(blob):
        return "broker-dealer"
    if _looks_like_vc(name, description, domain):
        return "venture capital"
    if re.search(r"\bholdings\b", name or "", re.IGNORECASE) and not _NAMED_FIRM.search(blob) and not _PE.search(blob):
        return "unknown"
    if _BUYOUT.search(blob):
        return "buyout"
    if _GROWTH.search(blob):
        return "growth equity"
    if _PE.search(blob):
        return "private equity"
    if _BANK.search(blob) or "capital markets" in industry_text:
        return "investment bank"
    if _RISK.search(blob):
        return "risk advisory"
    if _VC.search(blob):
        return "venture capital"
    return "unknown"


_TITLE_WORDS = {
    "partner",
    "capital",
    "managing",
    "director",
    "equity",
    "group",
    "fund",
    "ventures",
    "venture",
    "holdings",
    "principal",
    "founder",
    "president",
    "officer",
    "financial",
    "chief",
}


def truncated_last_name(last: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", last or "")
    return len(letters) <= 1


def last_name_from_linkedin(url: str, first: str) -> str:
    """Use a hyphenated LinkedIn slug. Compact slugs like scottpjensen are not guessed."""
    if not url or not first:
        return ""
    slug = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    words = [part for part in slug.split("-") if part and not re.search(r"\d", part)]
    if len(words) < 2:
        return ""
    if words[0].lower() != re.sub(r"[^a-z]", "", first.lower()):
        return ""
    last = words[-1]
    if len(last) < 2 or last.lower() in _TITLE_WORDS:
        return ""
    return last[:1].upper() + last[1:]


def last_name_from_text(first: str, text: str) -> str:
    if not first or not text:
        return ""
    pattern = re.compile(rf"\b{re.escape(first)}\s+([A-Z][a-zA-Z'’-]{{2,}})\b")
    for match in pattern.finditer(text):
        candidate = match.group(1)
        if candidate.lower() in _TITLE_WORDS:
            continue
        return candidate
    return ""


def align_firm_domain(raw: dict[str, str]) -> tuple[str, str]:
    """Return the firm domain and a dq code when the email domain is a different org."""
    from mobydick.domains import normalize_domain

    website = normalize_domain(raw.get("company_website") or "")
    listed = normalize_domain(raw.get("company_domain") or "")
    email_domain = normalize_domain(raw.get("email") or "")
    firm = website or listed
    if email_domain and firm and not _same_org(email_domain, firm):
        return listed or firm, "email_domain_mismatch"
    if website and (not email_domain or _same_org(email_domain, website)):
        return website, ""
    return listed or firm, ""


_FORM_D_VENTURE = re.compile(
    r"\bform\s*d\b.{0,300}\bventure(?:\s+capital|\s+fund)?\b|"
    r"\bventure(?:\s+capital|\s+fund)?\b.{0,300}\bform\s*d\b",
    re.IGNORECASE | re.DOTALL,
)


def page_disqualifies_firm(page_text: str) -> str:
    """A team page or filing can show a broker-dealer or a venture Form D."""
    if _BROKER.search(page_text or ""):
        return "broker-dealer"
    if _FORM_D_VENTURE.search(page_text or ""):
        return "venture capital"
    return ""


def assess_pe(raw: dict[str, str]) -> dict[str, str]:
    """Return firm_type, dq, and any corrected name or domain. Empty dq can still ship."""
    domain, domain_dq = align_firm_domain(raw)
    first = (raw.get("first_name") or "").strip()
    last = (raw.get("last_name") or "").strip()
    full = (raw.get("full_name") or "").strip()
    if truncated_last_name(last):
        resolved = last_name_from_linkedin(raw.get("linkedin_url") or "", first)
        if resolved:
            last = resolved
            full = f"{first} {last}".strip()
    firm_type = classify_firm(
        raw.get("company_name") or "",
        raw.get("company_description") or "",
        raw.get("company_industry") or "",
        domain,
    )
    unresolved = "yes" if truncated_last_name(last) else ""
    if not full:
        reason = "missing_name"
    elif not (domain or raw.get("company_domain") or "").strip():
        reason = "missing_domain"
    elif domain_dq:
        reason = domain_dq
    else:
        reason = title_reason(raw.get("title") or "")
        if not reason and not person_is_us(raw.get("contact_country") or "", raw.get("location") or ""):
            reason = "not_us_person"
        if not reason and not hq_is_us(raw.get("company_hq_country") or ""):
            reason = "not_us_hq"
        if not reason and firm_type not in KEEP_FIRM_TYPES:
            reason = "not_pe_firm"
    return {
        "firm_type": firm_type,
        "dq": reason,
        "company_domain": domain,
        "first_name": first,
        "last_name": last,
        "full_name": full,
        "unresolved_name": unresolved,
    }
