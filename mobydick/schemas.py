"""CSV column contracts for Series A/B and PE partner deliveries."""

from __future__ import annotations

from typing import Any

SERIES_AB_COLUMNS = [
    "full_name",
    "title",
    "email",
    "linkedin_url",
    "company_name",
    "company_domain",
    "funding_round",
    "funding_amount",
    "funding_date",
    "source_note",
    "company_website",
    "mailing_address",
    "location",
    "why_started",
    "origin_hometown",
    "personal_beliefs_causes",
    "best_emotional_hook",
    "quirky_personal_fact",
    "confidence",
    "dq",
    "sources",
    "research_note",
]

PE_COLUMNS = [
    "first_name",
    "last_name",
    "full_name",
    "email",
    "title",
    "company_name",
    "company_domain",
    "company_website",
    "linkedin_url",
    "location",
    "mailing_address",
    "hometown_or_from",
    "why_got_into_pe",
    "real_story",
    "best_emotional_hook",
    "beliefs_or_causes",
    "firm_type",
    "source_notes",
    "confidence",
    "sources",
    "research_note",
]

SAMPLE_SAFE_FIELDS = (
    "full_name",
    "first_name",
    "last_name",
    "title",
    "company_name",
    "company_domain",
    "funding_round",
    "firm_type",
    "confidence",
    "dq",
    "location",
)

GETLEADS_EXPORT_COLUMNS = [
    "first_name",
    "last_name",
    "full_name",
    "title",
    "email",
    "linkedin_url",
    "company_name",
    "company_domain",
    "company_website",
    "company_description",
    "location",
    "headquarters_country",
    "funding_type",
    "last_funding_type",
    "funding_amount",
    "last_funding_amount",
    "funding_date",
    "last_funding_date",
    "total_funding_amount",
]


def columns_for(audience: str) -> list[str]:
    if audience == "pe_partners":
        return list(PE_COLUMNS)
    return list(SERIES_AB_COLUMNS)


def empty_row(audience: str) -> dict[str, str]:
    return {col: "" for col in columns_for(audience)}


def compact_sample(row: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    """Safe preview: identity + company, never email or enrichment dumps."""
    out: dict[str, Any] = {}
    for key in SAMPLE_SAFE_FIELDS:
        value = row.get(key)
        if value not in (None, ""):
            out[key] = value
    return out
