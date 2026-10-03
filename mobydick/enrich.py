"""Emotional / personal enrichment plus public office address."""

from __future__ import annotations

from typing import Any, Callable

from mobydick.audiences import PE_PARTNERS, SERIES_AB, normalize_audience
from mobydick.research.extract import extract_person_fields
from mobydick.research.web import gather_company_pages
from mobydick.schemas import empty_row
from mobydick.store import LIST_PE


FOUNDER_TITLE_HINTS = ("founder", "ceo", "chief executive")
PE_TITLE_HINTS = (
    "partner",
    "principal",
    "managing director",
    "independent sponsor",
    "general partner",
)
PE_DQ_HINTS = ("associate", "analyst", "assistant", "intern", "coordinator")


def disqualify(row: dict[str, str], audience: str) -> str:
    title = (row.get("title") or "").lower()
    domain = row.get("company_domain") or ""
    name = row.get("full_name") or ""
    if not name:
        return "missing_name"
    if not domain:
        return "missing_domain"
    if audience == PE_PARTNERS:
        if any(hint in title for hint in PE_DQ_HINTS):
            return "junior_title"
        if title and not any(hint in title for hint in PE_TITLE_HINTS):
            return "not_partner_grade"
    else:
        if title and not any(hint in title for hint in FOUNDER_TITLE_HINTS):
            return "not_founder_or_ceo"
    return ""


def apply_enrichment(
    raw: dict[str, str],
    audience: str,
    *,
    fetch_pages: bool = True,
) -> dict[str, str]:
    name = normalize_audience(audience)
    row = empty_row(name)
    row.update({k: v for k, v in raw.items() if k in row})
    if name == LIST_PE or name == PE_PARTNERS:
        if not row.get("first_name") and raw.get("first_name"):
            row["first_name"] = raw["first_name"]
        if not row.get("last_name") and raw.get("last_name"):
            row["last_name"] = raw["last_name"]
        row["source_notes"] = raw.get("source_note") or raw.get("source_notes") or "getleads"
        row["firm_type"] = raw.get("firm_type") or "private equity"
    else:
        row["source_note"] = raw.get("source_note") or "getleads"
        row["funding_round"] = raw.get("funding_round") or ""
        row["funding_amount"] = raw.get("funding_amount") or ""
        row["funding_date"] = raw.get("funding_date") or ""

    pages: dict[str, Any] = {"pages": [], "mailing_address": "", "website": row.get("company_website") or ""}
    if fetch_pages:
        pages = gather_company_pages(row.get("company_website") or "", row.get("company_domain") or "")
    if pages.get("website") and not row.get("company_website"):
        row["company_website"] = pages["website"]
    if pages.get("mailing_address"):
        row["mailing_address"] = pages["mailing_address"]

    extracted = extract_person_fields(
        row.get("full_name") or "",
        row.get("company_name") or "",
        pages.get("pages") or [],
        audience=name,
    )
    if name == PE_PARTNERS:
        row["hometown_or_from"] = extracted["hometown"]
        row["why_got_into_pe"] = extracted["why"]
        row["real_story"] = extracted["quirk"] or extracted["why"]
        row["beliefs_or_causes"] = extracted["causes"]
        row["best_emotional_hook"] = extracted["hook"]
        row["research_note"] = extracted["research_note"]
        row["sources"] = extracted["sources"]
    else:
        row["origin_hometown"] = extracted["hometown"]
        row["why_started"] = extracted["why"]
        row["personal_beliefs_causes"] = extracted["causes"]
        row["quirky_personal_fact"] = extracted["quirk"]
        row["best_emotional_hook"] = extracted["hook"]
        row["research_note"] = extracted["research_note"]
        row["sources"] = extracted["sources"]
    row["confidence"] = extracted["confidence"]
    row["dq"] = disqualify(row, name)
    if not row.get("location"):
        row["location"] = raw.get("location") or ""
    return row


def enrich_rows(
    raws: list[dict[str, str]],
    audience: str,
    *,
    fetch_pages: bool = True,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for index, raw in enumerate(raws, start=1):
        out.append(apply_enrichment(raw, audience, fetch_pages=fetch_pages))
        if progress:
            progress({"enriched": index, "total": len(raws)})
    return out
