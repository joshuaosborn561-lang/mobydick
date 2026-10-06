"""Bulk enriched-list pipeline. Counts and samples only in tool results."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("mobydick.pipeline")

from mobydick.audiences import (
    DEFAULT_FUNDED_SINCE,
    default_filters,
    normalize_audience,
    overfetch_count,
    pe_scan_cap,
)
from mobydick.domains import normalize_domain
from mobydick.enrich import enrich_rows
from mobydick.getleads import GetLeadsClient
from mobydick.schemas import compact_sample
from mobydick.store import Store
from mobydick.waterfall import fill_missing_emails


def _one_per_company(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        domain = normalize_domain(row.get("company_domain"))
        if not domain or domain in seen:
            continue
        seen.add(domain)
        row["company_domain"] = domain
        out.append(row)
    return out


def _drop_excluded(rows: list[dict[str, str]], excluded: set[str]) -> tuple[list[dict[str, str]], int]:
    kept: list[dict[str, str]] = []
    dropped = 0
    for row in rows:
        domain = normalize_domain(row.get("company_domain"))
        if domain in excluded:
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


def _funding_ok(row: dict[str, str], funded_since: str) -> bool:
    if not funded_since:
        return True
    date = (row.get("funding_date") or "")[:10]
    if not date:
        return True
    return date >= funded_since


def build_enriched_list(
    audience: str,
    count: int,
    *,
    filters: dict[str, Any] | None = None,
    funded_since: str = DEFAULT_FUNDED_SINCE,
    require_email: bool = True,
    max_per_company: int = 1,
    overfetch: float = 2.0,
    enrich: bool = True,
    fetch_pages: bool = True,
    story_first: bool | None = None,
    store: Store | None = None,
    getleads: GetLeadsClient | None = None,
    raw_rows: list[dict[str, str]] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    name = normalize_audience(audience)
    wanted = max(1, int(count))
    if story_first is None:
        story_first = name == "pe_partners"
    story_first = bool(story_first) and name == "pe_partners"
    store = store or Store()
    excluded = store.exclude_domains(name)
    merged_filters = default_filters(
        name,
        funded_since=funded_since,
        require_email=require_email,
        extra=filters,
    )
    if excluded:
        # GetLeads exclude_domains is useful but huge lists can 400. Cap the wire set.
        merged_filters["exclude_domains"] = sorted(excluded)[:1500]

    pull_n = overfetch_count(wanted, overfetch)
    if progress:
        progress({"stage": "pull", "requested": wanted, "overfetch": pull_n, "excluded": len(excluded)})

    if name == "pe_partners" and raw_rows is None:
        client = getleads or GetLeadsClient()
        return _build_pe_until_full(
            wanted=wanted,
            store=store,
            excluded=excluded,
            filters=merged_filters,
            client=client,
            fetch_pages=fetch_pages and enrich,
            story_first=story_first,
            progress=progress,
        )

    if raw_rows is None:
        client = getleads or GetLeadsClient()
        raw_rows = client.pull(
            merged_filters,
            max_rows=pull_n,
            max_per_company=max_per_company,
            progress=progress,
        )

    unique = _one_per_company(raw_rows)
    fresh, dropped_prior = _drop_excluded(unique, excluded)
    if name != "pe_partners" and funded_since:
        fresh = [row for row in fresh if _funding_ok(row, funded_since)]

    early_dq: list[dict[str, str]] = []
    if name == "pe_partners":
        from mobydick.pe_fit import assess_pe

        passing: list[dict[str, str]] = []
        for row in fresh:
            verdict = assess_pe(row)
            if verdict.get("company_domain"):
                row["company_domain"] = verdict["company_domain"]
            if verdict.get("full_name"):
                row["full_name"] = verdict["full_name"]
            if verdict.get("first_name"):
                row["first_name"] = verdict["first_name"]
            if verdict.get("last_name"):
                row["last_name"] = verdict["last_name"]
            if verdict["dq"]:
                early_dq.append(
                    {
                        "dq": verdict["dq"],
                        "firm_type": verdict["firm_type"],
                        "firm": row.get("company_name") or "",
                        "phrase": verdict.get("dq_phrase") or "",
                    }
                )
                continue
            passing.append(row)
        fresh = passing

    if progress:
        progress({"stage": "dedupe", "unique": len(unique), "fresh": len(fresh), "dropped_prior": dropped_prior})

    waterfall_stats = fill_missing_emails(fresh, progress=progress)
    research = None
    if name == "pe_partners":
        from mobydick.research.trace import tracing

        with tracing() as trace:
            for item in early_dq:
                from mobydick.research.trace import drop_person, note_not_pe

                drop_person(item.get("dq") or "")
                if item.get("dq") == "not_pe_firm":
                    note_not_pe(item.get("firm") or "", item.get("phrase") or item.get("firm_type") or "")
            enriched = enrich_rows(fresh, name, fetch_pages=fetch_pages and enrich, progress=progress)
            _apply_story_gate(enriched, story_first=story_first and fetch_pages and enrich)
            research = trace.as_dict()
        logger.info("pe research %s", research)
    else:
        enriched = enrich_rows(fresh, name, fetch_pages=fetch_pages and enrich, progress=progress)
    payload = _delivery_payload(
        name=name,
        wanted=wanted,
        store=store,
        raw_count=len(raw_rows),
        unique_count=len(unique),
        dropped_prior=dropped_prior,
        excluded_count=len(excluded),
        waterfall_stats=waterfall_stats,
        enriched=enriched,
        early_dq=early_dq,
    )
    if research is not None:
        payload["research"] = research
    return _attach_model_warning(payload, name)


def _apply_pe_verdict(row: dict[str, str], verdict: dict[str, str]) -> str:
    if verdict.get("company_domain"):
        row["company_domain"] = verdict["company_domain"]
    if verdict.get("full_name"):
        row["full_name"] = verdict["full_name"]
    if verdict.get("first_name"):
        row["first_name"] = verdict["first_name"]
    if verdict.get("last_name"):
        row["last_name"] = verdict["last_name"]
    return verdict.get("dq") or ""


def _score_footprints(pending: list[dict[str, str]], limit: int) -> None:
    """Order the queue. A missing footprint does not remove a candidate."""
    from mobydick.research.life import public_footprint

    scored = 0
    for row in pending:
        if "_footprint_score" in row:
            continue
        if scored >= limit:
            break
        try:
            footprint = public_footprint(row)
        except Exception:
            logger.exception("footprint failed")
            footprint = {"score": 0, "hits": []}
        row["_footprint_score"] = int(footprint.get("score") or 0)
        row["_footprint_hits"] = list(footprint.get("hits") or [])[:6]
        scored += 1


def _apply_story_gate(rows: list[dict[str, str]], *, story_first: bool) -> None:
    if not story_first:
        return
    from mobydick.research.life import cited_personal_facts
    from mobydick.research.trace import drop_person

    for row in rows:
        no_pages = row.pop("_no_pages_kept", "")
        if row.get("dq"):
            continue
        if not cited_personal_facts(row):
            row["dq"] = "no_personal_story"
            drop_person("no_pages_kept" if no_pages and not row.get("sources") else "no_personal_story")


def _build_pe_until_full(
    *,
    wanted: int,
    store: Store,
    excluded: set[str],
    filters: dict[str, Any],
    client: GetLeadsClient,
    fetch_pages: bool,
    story_first: bool,
    progress: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    """Page GetLeads until enough PE keepers pass, or the scan cap is hit."""
    from mobydick.pe_fit import assess_pe
    from mobydick.research.trace import tracing

    cap = pe_scan_cap(wanted, story_first=story_first)
    scanned: list[dict[str, str]] = []
    enriched: list[dict[str, str]] = []
    keepers: list[dict[str, str]] = []
    early_dq: list[dict[str, str]] = []
    kept_domains: set[str] = set()
    offset = 0
    dropped_prior = 0
    pending: list[dict[str, str]] = []
    exhausted = False
    waterfall_parts: list[dict[str, Any]] = []
    with tracing() as trace:
        while len(keepers) < wanted:
            if not pending:
                if exhausted or len(scanned) >= cap:
                    break
                limit = min(100, cap - len(scanned))
                batch = client.search(filters, limit=limit, offset=offset)
                if not batch:
                    break
                offset += len(batch)
                scanned.extend(batch)
                if len(batch) < limit:
                    exhausted = True
                if progress:
                    progress({"stage": "pull", "scanned": len(scanned), "scan_cap": cap, "keepers": len(keepers)})
                for row in batch:
                    domain = normalize_domain(row.get("company_domain"))
                    if domain and domain in excluded:
                        dropped_prior += 1
                        continue
                    if domain and domain in kept_domains:
                        continue
                    verdict = assess_pe(row)
                    reason = _apply_pe_verdict(row, verdict)
                    if reason:
                        early_dq.append(
                            {
                                "dq": reason,
                                "firm_type": verdict.get("firm_type") or "",
                                "firm": row.get("company_name") or "",
                                "phrase": verdict.get("dq_phrase") or "",
                            }
                        )
                        from mobydick.research.trace import drop_person, note_not_pe

                        drop_person(reason)
                        if reason == "not_pe_firm":
                            note_not_pe(row.get("company_name") or "", verdict.get("dq_phrase") or "")
                        continue
                    if domain:
                        kept_domains.add(domain)
                    pending.append(row)
            if not pending:
                continue
            if fetch_pages:
                _score_footprints(pending, max(8, wanted - len(keepers)))
                pending.sort(
                    key=lambda row: row["_footprint_score"] if "_footprint_score" in row else -1,
                    reverse=True,
                )
                scored = [row for row in pending if "_footprint_score" in row]
                rest = [row for row in pending if "_footprint_score" not in row]
                take = min(wanted - len(keepers), len(scored))
                fresh = scored[:take]
                pending = scored[take:] + rest
                if not fresh:
                    continue
            else:
                fresh = pending[: wanted - len(keepers)]
                pending = pending[len(fresh) :]
            waterfall_parts.append(fill_missing_emails(fresh, progress=progress))
            batch_enriched = enrich_rows(fresh, "pe_partners", fetch_pages=fetch_pages, progress=progress)
            _apply_story_gate(batch_enriched, story_first=story_first and fetch_pages)
            enriched.extend(batch_enriched)
            for row in batch_enriched:
                if row.get("dq"):
                    if row.get("company_domain"):
                        kept_domains.discard(normalize_domain(row["company_domain"]))
                    continue
                keepers.append(row)
        research = trace.as_dict()
    logger.info("pe research %s", research)
    unique_domains = {
        domain
        for domain in (normalize_domain(row.get("company_domain")) for row in scanned)
        if domain
    }
    payload = _delivery_payload(
        name="pe_partners",
        wanted=wanted,
        store=store,
        raw_count=len(scanned),
        unique_count=len(unique_domains),
        dropped_prior=dropped_prior,
        excluded_count=len(excluded),
        waterfall_stats=_merge_waterfall(waterfall_parts),
        enriched=enriched,
        early_dq=early_dq,
    )
    payload["research"] = research
    payload["scanned"] = len(scanned)
    payload["scan_cap"] = cap
    return _attach_model_warning(payload, "pe_partners")


def _merge_waterfall(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts:
        return {"missing_before": 0, "filled": 0, "still_missing": 0, "leadmagic_calls": 0}
    return {
        "missing_before": sum(int(part.get("missing_before") or 0) for part in parts),
        "filled": sum(int(part.get("filled") or 0) for part in parts),
        "still_missing": sum(int(part.get("still_missing") or 0) for part in parts),
        "leadmagic_calls": sum(int(part.get("leadmagic_calls") or 0) for part in parts),
    }


def _delivery_payload(
    *,
    name: str,
    wanted: int,
    store: Store,
    raw_count: int,
    unique_count: int,
    dropped_prior: int,
    excluded_count: int,
    waterfall_stats: dict[str, Any],
    enriched: list[dict[str, str]],
    early_dq: list[dict[str, str]],
) -> dict[str, Any]:
    from mobydick.research.life import cited_personal_facts

    keepers = [row for row in enriched if not row.get("dq")]
    keepers.sort(key=lambda row: len(cited_personal_facts(row)), reverse=True)
    dq_rows = early_dq + [row for row in enriched if row.get("dq")]
    delivered = keepers[:wanted]
    path = store.write_delivery(name, delivered)
    samples = [compact_sample(row) for row in delivered[:10]]
    return {
        "ok": True,
        "audience": name,
        "requested": wanted,
        "pulled_raw": raw_count,
        "unique_companies": unique_count,
        "dropped_prior_domains": dropped_prior,
        "excluded_list_size": excluded_count,
        "emails_filled": waterfall_stats.get("filled"),
        "emails_still_missing": waterfall_stats.get("still_missing"),
        "enriched": len(enriched),
        "disqualified": len(dq_rows),
        "dq_reasons": _count_by(dq_rows, "dq"),
        "delivered": len(delivered),
        "shortfall": max(0, wanted - len(delivered)),
        "csv_path": str(path),
        "csv_name": path.name,
        "samples": samples,
        "note": (
            "CSV only. Call download_delivery with job_id or csv_name to save the file. "
            "Do not paste the list into chat. Same-day files are also excluded next pull."
        ),
        "waterfall": {
            "missing_before": waterfall_stats.get("missing_before"),
            "filled": waterfall_stats.get("filled"),
            "leadmagic_calls": waterfall_stats.get("leadmagic_calls"),
        },
    }


def _attach_model_warning(payload: dict[str, Any], audience: str) -> dict[str, Any]:
    if audience != "pe_partners":
        return payload
    from mobydick.research.life import NO_MODEL_WARNING, llm_keys_present

    if llm_keys_present():
        payload["life_extraction"] = "llm"
        return payload
    payload["life_extraction"] = "heuristic"
    payload["enrichment_warning"] = NO_MODEL_WARNING
    logger.warning("%s", NO_MODEL_WARNING)
    return payload


def _count_by(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts
