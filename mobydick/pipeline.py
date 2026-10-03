"""Bulk enriched-list pipeline. Counts and samples only in tool results."""

from __future__ import annotations

from typing import Any, Callable

from mobydick.audiences import (
    DEFAULT_FUNDED_SINCE,
    default_filters,
    normalize_audience,
    overfetch_count,
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
    store: Store | None = None,
    getleads: GetLeadsClient | None = None,
    raw_rows: list[dict[str, str]] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    name = normalize_audience(audience)
    wanted = max(1, int(count))
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

    if progress:
        progress({"stage": "dedupe", "unique": len(unique), "fresh": len(fresh), "dropped_prior": dropped_prior})

    waterfall_stats = fill_missing_emails(fresh, progress=progress)
    enriched = enrich_rows(fresh, name, fetch_pages=fetch_pages and enrich, progress=progress)
    keepers = [row for row in enriched if not row.get("dq")]
    dq_rows = [row for row in enriched if row.get("dq")]
    delivered = keepers[:wanted]
    path = store.write_delivery(name, delivered)

    samples = [compact_sample(row) for row in delivered[:10]]
    return {
        "ok": True,
        "audience": name,
        "requested": wanted,
        "pulled_raw": len(raw_rows),
        "unique_companies": len(unique),
        "dropped_prior_domains": dropped_prior,
        "excluded_list_size": len(excluded),
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
        "note": "CSV only. Do not paste the list into chat. Same-day files are also excluded next pull.",
        "waterfall": {
            "missing_before": waterfall_stats.get("missing_before"),
            "filled": waterfall_stats.get("filled"),
            "leadmagic_calls": waterfall_stats.get("leadmagic_calls"),
        },
    }


def _count_by(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts
