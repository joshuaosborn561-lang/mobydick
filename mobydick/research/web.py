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


def fetch_text(url: str, *, http: requests.Session | None = None, timeout: int = 15) -> str:
    if not url:
        return ""
    session = http or requests.Session()
    try:
        resp = session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return ""
    if resp.status_code >= 400:
        return ""
    html = resp.text or ""
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    text = re.sub(r"(?is)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
