"""Normalize and compare company domains for de-dupe."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_WWW_RE = re.compile(r"^www\.", re.IGNORECASE)


def normalize_domain(value: str | None) -> str:
    """Strip scheme, www, path, port, and trailing dots. Lowercase."""
    text = (value or "").strip()
    if not text:
        return ""
    if "@" in text and "://" not in text and "/" not in text:
        text = text.rsplit("@", 1)[-1]
    if not _SCHEME_RE.match(text):
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or parsed.netloc or "").strip().lower()
    host = _WWW_RE.sub("", host)
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def domains_from_values(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values or []:
        domain = normalize_domain(raw)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        out.append(domain)
    return out
