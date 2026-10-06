"""Emotional / personal enrichment plus public office address."""

from __future__ import annotations

import logging
from typing import Any, Callable
from urllib.parse import urlparse

from mobydick.audiences import PE_PARTNERS, normalize_audience
from mobydick.pe_fit import (
    assess_pe,
    firm_self_venture_phrase,
    firm_text_pe_type,
    last_name_from_text,
    page_disqualifies_firm,
)
from mobydick.research.extract import extract_person_fields
from mobydick.research.life import (
    NO_MODEL_WARNING,
    extract_life_story,
    gather_person_sources,
    llm_keys_present,
)
from mobydick.research.trace import current, drop_person, note_not_pe
from mobydick.research.web import gather_company_pages
from mobydick.schemas import empty_row
from mobydick.store import LIST_PE

logger = logging.getLogger("mobydick.enrich")


FOUNDER_TITLE_HINTS = ("founder", "ceo", "chief executive")
_IDENTITY_PATHS = {"/", "/about", "/about-us", "/who-we-are", "/company", "/our-firm", "/our-story"}


def _identity_text(pages: list[dict[str, Any]]) -> str:
    """Homepage and about text only. Team bios and contact pages are not the firm speaking."""
    chunks: list[str] = []
    for page in pages:
        path = urlparse(str(page.get("url") or "")).path.lower() or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        if not path.startswith("/"):
            path = "/" + path
        if path in _IDENTITY_PATHS:
            chunks.append(str(page.get("text") or ""))
    return "\n".join(chunks)[:8000]


def disqualify(row: dict[str, str], audience: str) -> str:
    title = (row.get("title") or "").lower()
    domain = row.get("company_domain") or ""
    name = row.get("full_name") or ""
    if not name:
        return "missing_name"
    if not domain:
        return "missing_domain"
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
        screened = assess_pe({**raw, **{k: v for k, v in row.items() if v}})
        row["firm_type"] = screened["firm_type"]
        if screened.get("company_domain"):
            row["company_domain"] = screened["company_domain"]
        if screened.get("full_name"):
            row["full_name"] = screened["full_name"]
        if screened.get("first_name"):
            row["first_name"] = screened["first_name"]
        if screened.get("last_name"):
            row["last_name"] = screened["last_name"]
    else:
        row["source_note"] = raw.get("source_note") or "getleads"
        row["funding_round"] = raw.get("funding_round") or ""
        row["funding_amount"] = raw.get("funding_amount") or ""
        row["funding_date"] = raw.get("funding_date") or ""

    pages: dict[str, Any] = {"pages": [], "mailing_address": "", "website": row.get("company_website") or ""}
    pe_dq = screened["dq"] if name == PE_PARTNERS else ""
    if fetch_pages and not pe_dq:
        pages = gather_company_pages(row.get("company_website") or "", row.get("company_domain") or "")
    if pages.get("website") and not row.get("company_website"):
        row["company_website"] = pages["website"]
    if pages.get("mailing_address"):
        if name == LIST_PE or name == PE_PARTNERS:
            row["firm_mailing_address"] = pages["mailing_address"]
        else:
            row["mailing_address"] = pages["mailing_address"]

    if name == PE_PARTNERS:
        trace = current()
        before = trace.as_dict() if trace is not None else None
        life_sources: list[dict[str, str]] = []
        if screened.get("unresolved_name") and not pe_dq and not fetch_pages:
            pe_dq = "truncated_name"
        venture_phrase = ""
        if fetch_pages and not pe_dq:
            identity = _identity_text(pages.get("pages") or [])
            venture_phrase = firm_self_venture_phrase(row.get("company_name") or "", identity)
            if venture_phrase:
                row["firm_type"] = "venture capital"
                pe_dq = "not_pe_firm"
                note_not_pe(row.get("company_name") or "", venture_phrase)
            elif (row.get("firm_type") or "") == "unknown":
                claimed = firm_text_pe_type(identity)
                if claimed:
                    row["firm_type"] = claimed
        if fetch_pages and not pe_dq:
            if raw.get("_footprint_hits"):
                row["_footprint_hits"] = raw["_footprint_hits"]
            if "_footprint_score" in raw:
                row["_footprint_score"] = raw["_footprint_score"]
            life_sources = gather_person_sources(row)
            row.pop("_footprint_hits", None)
            row.pop("_footprint_score", None)
            if screened.get("unresolved_name"):
                resolved = last_name_from_text(
                    row.get("first_name") or "",
                    " ".join(source.get("text") or "" for source in life_sources),
                )
                if resolved:
                    row["last_name"] = resolved
                    row["full_name"] = f"{row.get('first_name') or ''} {resolved}".strip()
                else:
                    pe_dq = "truncated_name"
                    life_sources = []
        if pe_dq:
            life_sources = []
        elif life_sources:
            page_text = " ".join(source.get("text") or "" for source in life_sources)[:6000]
            revised = page_disqualifies_firm(f"{raw.get('company_description') or ''} {page_text}")
            if revised:
                row["firm_type"] = revised
                pe_dq = "not_pe_firm"
                life_sources = []
        life = extract_life_story(row.get("full_name") or "", life_sources, firm=row.get("company_name") or "")
        if pe_dq:
            life = {key: "" for key in life}
            life["confidence"] = "low"
            life["research_note"] = life.get("research_note") or (
                f"Public sources only. Empty means not found. No home address. {NO_MODEL_WARNING}"
                if not llm_keys_present()
                else "Public sources only. Empty means not found. No home address."
            )
        row["hometown_or_from"] = life.get("hometown") or ""
        row["family_background"] = life.get("family_background") or ""
        row["college"] = life.get("college") or ""
        row["military_service"] = life.get("military_service") or ""
        row["early_jobs"] = life.get("early_jobs") or ""
        row["why_got_into_pe"] = life.get("why") or ""
        row["beliefs_or_causes"] = life.get("causes") or ""
        row["life_events"] = life.get("life_events") or ""
        row["quotes"] = life.get("quotes") or ""
        row["real_story"] = life.get("real_story") or ""
        row["best_emotional_hook"] = life.get("hook") or ""
        row["research_note"] = life.get("research_note") or ""
        row["sources"] = life.get("sources") or ""
        row["confidence"] = life.get("confidence") or "low"
        row["dq"] = pe_dq
        if pe_dq:
            drop_person(pe_dq)
        elif fetch_pages and before is not None and trace is not None:
            kept_now = int(trace.as_dict()["pages_kept"]) - int(before["pages_kept"])
            if kept_now <= 0:
                row["_no_pages_kept"] = "1"
        if trace is not None and before is not None:
            after = trace.as_dict()
            logger.info(
                "pe person pages_fetched=%s pages_kept=%s pages_dropped=%s drop_reasons=%s searches_run=%s llm_calls=%s facts_extracted=%s facts_rejected=%s reject_reasons=%s",
                int(after["pages_fetched"]) - int(before["pages_fetched"]),
                int(after["pages_kept"]) - int(before["pages_kept"]),
                int(after["pages_dropped"]) - int(before["pages_dropped"]),
                {
                    key: int(after["drop_reasons"].get(key, 0)) - int(before["drop_reasons"].get(key, 0))
                    for key in set(after["drop_reasons"]) | set(before["drop_reasons"])
                    if int(after["drop_reasons"].get(key, 0)) - int(before["drop_reasons"].get(key, 0))
                },
                int(after["searches_run"]) - int(before["searches_run"]),
                int(after["llm_calls"]) - int(before["llm_calls"]),
                int(after["facts_extracted"]) - int(before["facts_extracted"]),
                int(after["facts_rejected"]) - int(before["facts_rejected"]),
                {
                    key: int(after["reject_reasons"].get(key, 0)) - int(before["reject_reasons"].get(key, 0))
                    for key in set(after["reject_reasons"]) | set(before["reject_reasons"])
                    if int(after["reject_reasons"].get(key, 0)) - int(before["reject_reasons"].get(key, 0))
                },
            )
    else:
        extracted = extract_person_fields(
            row.get("full_name") or "",
            row.get("company_name") or "",
            pages.get("pages") or [],
            audience=name,
        )
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
    # Page fetches are the slow part. A few people at a time, still in input order.
    # Sequential when pages are off so tests that record call order stay stable.
    if not fetch_pages or len(raws) <= 1:
        out: list[dict[str, str]] = []
        for index, raw in enumerate(raws, start=1):
            out.append(apply_enrichment(raw, audience, fetch_pages=fetch_pages))
            if progress:
                progress({"enriched": index, "total": len(raws)})
        return out

    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    def _run(raw: dict[str, str]) -> dict[str, str]:
        return apply_enrichment(raw, audience, fetch_pages=fetch_pages)

    workers = min(5, len(raws))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for raw in raws:
            ctx = contextvars.copy_context()
            futures.append(pool.submit(ctx.run, _run, raw))
        out = []
        for index, future in enumerate(futures, start=1):
            out.append(future.result())
            if progress:
                progress({"enriched": index, "total": len(raws)})
    return out
