"""Fetch public company pages and extract conservative office addresses."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = "MobyDickResearch/1.0 (+https://salesglider.com; public-source research only)"

ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.\- ]{3,40}\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Plaza|Place|Pl|Parkway|Pkwy|Suite|Ste|Floor|Fl)"
    r"\.?(?:[,\s]+(?:Suite|Ste|Unit|#)\s?[A-Za-z0-9\-]+)?[,\s]+[A-Za-z .]{2,40},\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?",
    re.IGNORECASE,
)

HOME_HINTS = (
    "home address",
    "residential",
    "residence",
    "apartment only",
    "private residence",
)

CONTACT_PATHS = (
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/company",
    "/locations",
    "/office",
)


def company_url(website: str, domain: str) -> str:
    site = (website or "").strip()
    if site and not site.startswith("http"):
        site = "https://" + site
    if site:
        return site.rstrip("/")
    domain = (domain or "").strip()
    if not domain:
        return ""
    return f"https://{domain}"


def html_to_text(html: str) -> str:
    cleaned = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html or "")
    cleaned = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", cleaned)
    text = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", text).strip()


def fetch_document(
    url: str,
    *,
    http: requests.Session | None = None,
    timeout: int = 15,
) -> tuple[str, str]:
    """Return (html, visible text). Counts the attempt. Empty when the fetch fails."""
    from mobydick.research.trace import note

    if not url:
        return "", ""
    note("pages_fetched")
    session = http or requests.Session()
    try:
        resp = session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return "", ""
    if resp.status_code >= 400:
        return "", ""
    html = resp.text or ""
    text = html_to_text(html)
    if text:
        note("pages_with_text")
    return html, text


def fetch_text(url: str, *, http: requests.Session | None = None, timeout: int = 15) -> str:
    return fetch_document(url, http=http, timeout=timeout)[1]


def host_key(url: str) -> str:
    host = urlparse(url or "").netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def same_site(url: str, base: str) -> bool:
    left = host_key(url)
    right = host_key(base)
    return bool(left and right and left == right)


_ANCHOR = re.compile(r"(?is)<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")
_TEAMISH = re.compile(
    r"team|people|leadership|leaders|professionals|our-team|biography|bio\b",
    re.IGNORECASE,
)
_SKIP_FILE = re.compile(r"\.(?:pdf|jpe?g|png|gif|zip|css|js|svg|webp)$", re.IGNORECASE)


def page_links(html: str, base: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for href, inner in _ANCHOR.findall(html or ""):
        href = href.strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        url = urljoin(base if base.endswith("/") else base + "/", href)
        parsed = urlparse(url)
        if _SKIP_FILE.search(parsed.path or ""):
            continue
        clean = parsed._replace(query="", fragment="").geturl()
        text = re.sub(r"\s+", " ", re.sub(r"(?is)<[^>]+>", " ", inner)).strip()
        found.append((clean, text))
    return found


def candidate_bio_urls(html: str, base: str, first: str, last: str) -> list[str]:
    """Same-site links that name the person, then links that look like a team page."""
    named: list[str] = []
    team: list[str] = []
    seen: set[str] = set()
    last_re = re.compile(rf"\b{re.escape(last)}\b", re.IGNORECASE) if last else None
    first_re = re.compile(rf"\b{re.escape(first)}\b", re.IGNORECASE) if first else None
    for url, text in page_links(html, base):
        if url in seen or not same_site(url, base):
            continue
        blob = f"{url} {text}"
        if last_re and last_re.search(blob) and (not first_re or first_re.search(blob)):
            named.append(url)
            seen.add(url)
        elif _TEAMISH.search(blob):
            team.append(url)
            seen.add(url)
    return named + team


def extract_office_address(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    if any(hint in lowered for hint in HOME_HINTS) and "headquarters" not in lowered:
        # Still allow HQ lines; skip only when the page is clearly residential.
        if "office" not in lowered and "headquarters" not in lowered:
            return ""
    match = ADDRESS_RE.search(text)
    if not match:
        return ""
    address = re.sub(r"\s+", " ", match.group(0)).strip()
    if len(address) < 12:
        return ""
    return address


def gather_company_pages(
    website: str,
    domain: str,
    *,
    http: requests.Session | None = None,
) -> dict[str, Any]:
    base = company_url(website, domain)
    pages: list[dict[str, str]] = []
    office = ""
    if not base:
        return {"website": "", "pages": pages, "mailing_address": ""}
    urls = [base] + [urljoin(base + "/", path.lstrip("/")) for path in CONTACT_PATHS]
    seen: set[str] = set()
    session = http or requests.Session()
    for url in urls:
        parsed = urlparse(url)
        key = parsed._replace(query="", fragment="").geturl()
        if key in seen:
            continue
        seen.add(key)
        text = fetch_text(url, http=session)
        if not text:
            continue
        pages.append({"url": url, "text": text[:8000]})
        if not office:
            office = extract_office_address(text)
        if len(pages) >= 4:
            break
    return {"website": base, "pages": pages, "mailing_address": office}
