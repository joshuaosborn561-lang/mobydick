"""Default GetLeads filters for Series A/B founders and PE partners."""

from __future__ import annotations

from typing import Any

SERIES_AB = "series_ab"
PE_PARTNERS = "pe_partners"

SAAS_INDUSTRIES = [
    "Software Development",
    "Technology; Information and Internet",
    "Technology; Information and Media",
    "Desktop Computing Software Products",
    "Mobile Computing Software Products",
    "Data Security Software Products",
    "Business Intelligence Platforms",
    "Embedded Software Products",
    "Internet Marketplace Platforms",
    "IT System Custom Software Development",
    "Data Infrastructure and Analytics",
    "Computer and Network Security",
    "E-Learning Providers",
    "Social Networking Platforms",
]

SERIES_AB_TITLES = [
    "CEO",
    "Chief Executive Officer",
    "Founder",
    "Co-Founder",
    "Co-Founder & CEO",
    "Co-Founder and CEO",
    "Founder & CEO",
    "Founder and CEO",
]

SERIES_AB_FUNDING = [
    "series a",
    "series a extension",
    "series b",
    "series b extension",
]

PE_INDUSTRIES = [
    "Venture Capital and Private Equity Principals",
    "Investment Management",
    "Capital Markets",
]

PE_TITLES = [
    "Partner",
    "Managing Partner",
    "General Partner",
    "Founding Partner",
    "Senior Partner",
    "Operating Partner",
    "Equity Partner",
    "Principal",
    "Independent Sponsor",
    "Managing Director",
]

PE_EXCLUDE_TITLES = [
    "Associate",
    "Analyst",
    "Assistant",
    "Intern",
    "Coordinator",
    "Executive Assistant",
    "Office Manager",
]

DEFAULT_FUNDED_SINCE = "2024-01-01"
OVERFETCH_MIN = 1.5
OVERFETCH_MAX = 3.0


def normalize_audience(audience: str) -> str:
    raw = (
        (audience or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
    )
    aliases = {
        "series_ab": SERIES_AB,
        "series_a_b": SERIES_AB,
        "seriesab": SERIES_AB,
        "founders": SERIES_AB,
        "saas": SERIES_AB,
        "saas_founders": SERIES_AB,
        "pe": PE_PARTNERS,
        "pe_partners": PE_PARTNERS,
        "pe_partner": PE_PARTNERS,
        "private_equity": PE_PARTNERS,
    }
    if raw not in aliases:
        raise ValueError("audience must be series_ab or pe_partners")
    return aliases[raw]


def overfetch_count(requested: int, multiplier: float = 2.0) -> int:
    clamped = max(OVERFETCH_MIN, min(OVERFETCH_MAX, float(multiplier)))
    return max(int(requested), int(round(requested * clamped)))


def default_filters(
    audience: str,
    *,
    funded_since: str = DEFAULT_FUNDED_SINCE,
    require_email: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = normalize_audience(audience)
    if name == PE_PARTNERS:
        filters: dict[str, Any] = {
            "industries": list(PE_INDUSTRIES),
            "job_titles": list(PE_TITLES),
            "exclude_job_titles": list(PE_EXCLUDE_TITLES),
            "headquarters_countries": ["United States"],
            "require_email": require_email,
            "company_description": "private equity,buyout,lower middle market,lower-middle,independent sponsor",
        }
    else:
        filters = {
            "industries": list(SAAS_INDUSTRIES),
            "job_titles": list(SERIES_AB_TITLES),
            "funding_types": list(SERIES_AB_FUNDING),
            "headquarters_countries": ["United States"],
            "require_email": require_email,
        }
        if funded_since:
            filters["funded_since"] = funded_since
    if extra:
        for key, value in extra.items():
            if value in (None, "", [], {}):
                continue
            filters[key] = value
    return filters


def getleads_search_args(filters: dict[str, Any]) -> dict[str, Any]:
    """Drop helper keys GetLeads does not accept."""
    skip = {"funded_since"}
    return {k: v for k, v in filters.items() if k not in skip and v not in (None, "", [], {})}
