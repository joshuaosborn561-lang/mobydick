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

    waterfall_stats = fill_missing_emails(fresh, settings=store.settings, progress=progress)
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


def _apply_footprint(row: dict[str, str]) -> None:
    from mobydick.research.life import public_footprint

    try:
        footprint = public_footprint(row)
    except Exception:
        logger.exception("footprint failed")
        footprint = {"score": 0, "hits": []}
    row["_footprint_score"] = int(footprint.get("score") or 0)
    row["_footprint_hits"] = list(footprint.get("hits") or [])[:6]


def _score_footprints(pending: list[dict[str, str]], limit: int) -> None:
    """Order the queue. A missing footprint does not remove a candidate."""
    todo: list[dict[str, str]] = []
    for row in pending:
        if "_footprint_score" in row:
            continue
        if len(todo) >= limit:
            break
        todo.append(row)
    if len(todo) <= 1:
        for row in todo:
            _apply_footprint(row)
        return
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(5, len(todo))) as pool:
        futures = []
        for row in todo:
            ctx = contextvars.copy_context()
            futures.append(pool.submit(ctx.run, _apply_footprint, row))
        for future in futures:
            future.result()


def _person_key(row: dict[str, str]) -> str:
    linkedin = (row.get("linkedin_url") or "").split("?")[0].rstrip("/").lower()
    if linkedin:
        return "li:" + linkedin
    email = (row.get("email") or "").strip().lower()
    if email:
        return "em:" + email
    return "nm:" + (row.get("full_name") or "").strip().lower() + "|" + normalize_domain(row.get("company_domain"))


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


class _SearchSlice:
    def __init__(self, filters: dict[str, Any], *, industries_dropped: bool = False) -> None:
        self.filters = filters
        self.industries_dropped = industries_dropped


def _extend_pe_plan(
    queue: list[_SearchSlice],
    filters: dict[str, Any],
    *,
    probed: bool,
    broadened: bool,
    empty_industry_queries: int,
) -> tuple[bool, bool, list[str]]:
    """After the current slices are done, probe industries, then drop them.

    Returns the updated probed flag, broadened flag, and industries tried alone.
    """
    from mobydick.getleads import dropped_industry_slices, industry_probe_slices

    industries = filters.get("industries") or []
    if isinstance(industries, str):
        industries = [industries]
    states = filters.get("states") or []
    if isinstance(states, str):
        states = [states]
    tried: list[str] = []
    if not probed:
        probed = True
        extra = industry_probe_slices(filters)
        tried = [str(item) for item in industries[:3]] if len(industries) > 1 else []
        if empty_industry_queries:
            if tried:
                logger.info(
                    "pe industry query empty after excludes industries=%s states=%s; trying %s one at a time",
                    len(industries),
                    len(states),
                    len(tried),
                )
            else:
                logger.info(
                    "pe industry query empty after excludes industries=%s states=%s; dropping industries",
                    len(industries),
                    len(states),
                )
        if extra:
            queue.extend(_SearchSlice(item) for item in extra)
            return probed, broadened, tried
    if not broadened and industries:
        broadened = True
        queue.extend(
            _SearchSlice(item, industries_dropped=True) for item in dropped_industry_slices(filters)
        )
    return probed, broadened, tried


def _search_timeout(exc: BaseException) -> bool:
    """True when GetLeads aborted the search, or the gateway timed out.

    search_timeout is a tool error. The HTTP client does not retry those.
    A longer client wait does not raise GetLeads' 50 second cap.
    """
    import requests

    if isinstance(exc, requests.Timeout):
        return True
    status = getattr(exc, "status", None)
    if status in {502, 503, 504}:
        return True
    text = f"{exc} {getattr(exc, 'body', '')}".lower()
    return "search_timeout" in text or "timed out after 50" in text


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
    import requests

    from mobydick.getleads import MIN_PAGE_SIZE, narrower_filters, search_filter_slices, search_page_limit
    from mobydick.pe_fit import assess_pe
    from mobydick.research.trace import tracing
    from mobydick.getleads_gate import claim_person, release_people, reserve_search_offset
    from mobydick.mcp_http import McpError

    cap = pe_scan_cap(wanted, story_first=story_first)
    scanned: list[dict[str, str]] = []
    enriched: list[dict[str, str]] = []
    keepers: list[dict[str, str]] = []
    early_dq: list[dict[str, str]] = []
    kept_domains: set[str] = set()
    dropped_prior = 0
    pending: list[dict[str, str]] = []
    broadened = False
    probed = False
    stop_reason = "source_exhausted"
    upstream_error = ""
    seen_people: set[str] = set()
    claimed: set[str] = set()
    waterfall_parts: list[dict[str, Any]] = []
    queue = [_SearchSlice(item) for item in search_filter_slices(filters)]
    index = 0
    slice_open = True
    empty_industry_queries = 0
    tried_one_at_a_time: list[str] = []
    timeout_error = ""
    try:
        with tracing() as trace:
            while len(keepers) < wanted:
                if not pending:
                    if len(scanned) >= cap:
                        stop_reason = "scan_cap"
                        break
                    if not slice_open:
                        index += 1
                        slice_open = True
                        if index >= len(queue):
                            probed, broadened, tried = _extend_pe_plan(
                                queue,
                                filters,
                                probed=probed,
                                broadened=broadened,
                                empty_industry_queries=empty_industry_queries,
                            )
                            if tried:
                                tried_one_at_a_time = tried
                            if index >= len(queue):
                                stop_reason = "source_exhausted"
                                break
                        continue
                    spec = queue[index]
                    if spec.industries_dropped:
                        broadened = True
                    limit = search_page_limit(
                        spec.filters,
                        industries_dropped=spec.industries_dropped,
                        remaining=cap - len(scanned),
                    )
                    page_offset = reserve_search_offset(spec.filters, limit, store.settings.data_dir)
                    narrowed = False
                    while True:
                        try:
                            batch = client.search(
                                spec.filters,
                                limit=limit,
                                offset=page_offset,
                                industries_dropped=spec.industries_dropped,
                            )
                            break
                        except (McpError, requests.Timeout) as exc:
                            if _search_timeout(exc) and limit > MIN_PAGE_SIZE:
                                limit = MIN_PAGE_SIZE
                                logger.warning(
                                    "pe search_timeout offset=%s; retrying limit=%s",
                                    page_offset,
                                    limit,
                                )
                                continue
                            smaller = narrower_filters(spec.filters) if _search_timeout(exc) else []
                            if smaller:
                                queue[index + 1 : index + 1] = [
                                    _SearchSlice(item, industries_dropped=spec.industries_dropped)
                                    for item in smaller
                                ]
                                logger.warning(
                                    "pe search_timeout; splitting into %s narrower queries",
                                    len(smaller),
                                )
                                narrowed = True
                                batch = []
                                break
                            if _search_timeout(exc):
                                status = getattr(exc, "status", None)
                                if status:
                                    timeout_error = f"MCP HTTP {status}: {exc}"[:500]
                                else:
                                    timeout_error = str(exc)[:500]
                                logger.warning("pe search_timeout; skipping a query that is already narrow")
                                narrowed = True
                                batch = []
                                break
                            status = getattr(exc, "status", None)
                            if status:
                                upstream_error = f"MCP HTTP {status}: {exc}"[:500]
                            else:
                                upstream_error = str(exc)[:500]
                            stop_reason = "upstream_error"
                            logger.warning("pe search stopped: %s", upstream_error)
                            break
                    if upstream_error:
                        break
                    if narrowed:
                        slice_open = False
                        continue
                    if not batch:
                        if spec.filters.get("industries"):
                            empty_industry_queries += 1
                            industries = spec.filters.get("industries") or []
                            states = spec.filters.get("states") or []
                            logger.info(
                                "pe industry query empty after excludes industries=%s states=%s",
                                len(industries) if isinstance(industries, list) else 1,
                                len(states) if isinstance(states, list) else 1,
                            )
                        slice_open = False
                        continue
                    scanned.extend(batch)
                    timeout_error = ""
                    if len(batch) < limit:
                        slice_open = False
                    if progress:
                        progress(
                            {
                                "stage": "pull",
                                "scanned": len(scanned),
                                "scan_cap": cap,
                                "keepers": len(keepers),
                                "broadened": broadened,
                            }
                        )
                    for row in batch:
                        person = _person_key(row)
                        if person in seen_people:
                            continue
                        if not claim_person(person):
                            continue
                        claimed.add(person)
                        seen_people.add(person)
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
                waterfall_parts.append(
                    fill_missing_emails(fresh, settings=store.settings, progress=progress)
                )
                batch_enriched = enrich_rows(fresh, "pe_partners", fetch_pages=fetch_pages, progress=progress)
                _apply_story_gate(batch_enriched, story_first=story_first and fetch_pages)
                enriched.extend(batch_enriched)
                for row in batch_enriched:
                    if row.get("dq"):
                        if row.get("company_domain"):
                            kept_domains.discard(normalize_domain(row["company_domain"]))
                        continue
                    keepers.append(row)
            if timeout_error and not upstream_error and len(keepers) < wanted:
                upstream_error = timeout_error
                stop_reason = "upstream_error"
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
        if len(keepers) >= wanted:
            stop_reason = "filled"
        if upstream_error:
            stop_reason = "upstream_error"
            payload["partial"] = True
            payload["error"] = upstream_error
            payload["note"] = (
                "Partial list. The pull stopped on an upstream error. "
                "The CSV has the people already verified. "
                + str(payload.get("note") or "")
            ).strip()
        payload["research"] = research
        payload["scanned"] = len(scanned)
        payload["scan_cap"] = cap
        payload["scan_stop"] = stop_reason
        payload["broadened"] = broadened
        if empty_industry_queries or tried_one_at_a_time:
            industries = filters.get("industries") or []
            states = filters.get("states") or []
            payload["industry_probe"] = {
                "industries": len(industries) if isinstance(industries, list) else 1,
                "states": len(states) if isinstance(states, list) else 1,
                "empty_queries": empty_industry_queries,
                "tried_one_at_a_time": tried_one_at_a_time,
            }
        return _attach_model_warning(payload, "pe_partners")
    finally:
        release_people(claimed)


def _merge_waterfall(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts:
        return {
            "missing_before": 0,
            "filled": 0,
            "still_missing": 0,
            "enrich_one_calls": 0,
            "estimated_cost_usd": 0.0,
            "spend": 0.0,
            "stopped_at_ceiling": False,
        }
    return {
        "missing_before": sum(int(part.get("missing_before") or 0) for part in parts),
        "filled": sum(int(part.get("filled") or 0) for part in parts),
        "still_missing": sum(int(part.get("still_missing") or 0) for part in parts),
        "enrich_one_calls": sum(int(part.get("enrich_one_calls") or 0) for part in parts),
        "estimated_cost_usd": round(sum(float(part.get("estimated_cost_usd") or 0) for part in parts), 6),
        "spend": round(sum(float(part.get("spend") or 0) for part in parts), 6),
        "stopped_at_ceiling": any(part.get("stopped_at_ceiling") for part in parts),
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
            "enrich_one_calls": waterfall_stats.get("enrich_one_calls"),
            "estimated_cost_usd": waterfall_stats.get("estimated_cost_usd"),
            "spend": waterfall_stats.get("spend"),
            "stopped_at_ceiling": waterfall_stats.get("stopped_at_ceiling"),
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
