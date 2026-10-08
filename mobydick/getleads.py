"""GetLeads pull via hosted MCP (count / search / export)."""

from __future__ import annotations

import csv
import io
import time
from typing import Any, Callable

import requests

from mobydick.audiences import getleads_search_args
from mobydick.config import Settings, settings as default_settings
from mobydick.domains import normalize_domain
from mobydick.getleads_gate import getleads_slot
from mobydick.mcp_http import McpError, McpHttpClient
from mobydick.schemas import GETLEADS_EXPORT_COLUMNS


def _first(*values: Any) -> str:
    for value in values:
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            inner = value.get("value") or value.get("name") or value.get("email")
            if inner:
                return str(inner).strip()
            continue
        return str(value).strip()
    return ""


def unwrap_records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("contacts", "people", "leads", "results", "items", "data", "records"):
        nested = data.get(key)
        if isinstance(nested, list):
            return [r for r in nested if isinstance(r, dict)]
        if isinstance(nested, dict):
            inner = unwrap_records(nested)
            if inner:
                return inner
    if any(k in data for k in ("email", "full_name", "company_name", "first_name")):
        return [data]
    return []


def contact_from_raw(raw: dict[str, Any]) -> dict[str, str]:
    company = raw.get("company") if isinstance(raw.get("company"), dict) else {}
    email = _first(raw.get("email"), raw.get("work_email"), raw.get("email_address"))
    domain = normalize_domain(
        _first(
            raw.get("company_domain"),
            raw.get("domain"),
            raw.get("org_domain"),
            company.get("domain") if company else "",
            email.split("@", 1)[1] if "@" in email else "",
        )
    )
    first = _first(raw.get("first_name"), raw.get("firstname"))
    last = _first(raw.get("last_name"), raw.get("lastname"))
    full = _first(raw.get("full_name"), raw.get("name"), f"{first} {last}".strip())
    website = _first(
        raw.get("company_website"),
        raw.get("current_employer_website"),
        raw.get("current_company_website"),
        raw.get("website"),
        company.get("website") if company else "",
    )
    return {
        "first_name": first,
        "last_name": last,
        "full_name": full,
        "title": _first(raw.get("title"), raw.get("current_title"), raw.get("job_title")),
        "email": email.lower() if email else "",
        "linkedin_url": _first(raw.get("linkedin_url"), raw.get("linkedin")),
        "company_name": _first(
            raw.get("company_name"),
            raw.get("current_employer"),
            raw.get("co_name"),
            company.get("name") if company else "",
        ),
        "company_domain": domain,
        "company_website": website,
        "company_description": _first(
            raw.get("company_description"),
            raw.get("co_description"),
            raw.get("description"),
        ),
        "location": _first(
            raw.get("location"),
            raw.get("contact_location"),
            raw.get("current_location"),
            raw.get("contact_city"),
            raw.get("city"),
            raw.get("contact_state"),
            raw.get("state"),
        ),
        "contact_country": _first(raw.get("contact_country"), raw.get("person_country"), raw.get("country")),
        "company_hq_country": _first(raw.get("company_hq_country"), raw.get("headquarters_country")),
        "company_industry": _first(
            raw.get("company_industry"),
            raw.get("main_industry"),
            raw.get("current_company_industry"),
        ),
        "funding_round": _first(
            raw.get("funding_round"),
            raw.get("last_funding_type"),
            raw.get("funding_type"),
        ),
        "funding_amount": _first(
            raw.get("funding_amount"),
            raw.get("last_funding_amount"),
            raw.get("total_funding_amount"),
        ),
        "funding_date": _first(
            raw.get("funding_date"),
            raw.get("last_funding_date"),
        ),
        "source_note": "getleads",
    }


# A state-heavy query with no industry filter was dying at about 50 seconds.
# Large searches wait longer. Dropping industries waits longer still.
SEARCH_TIMEOUT = 90
LARGE_SEARCH_TIMEOUT = 150
DROPPED_INDUSTRY_TIMEOUT = 210
STATE_BATCH = 3
TITLE_BATCH = 3
INDUSTRY_PROBE = 3


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _with_key(filters: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    copied = dict(filters)
    copied[key] = value
    return copied


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    width = max(1, int(size))
    return [items[index : index + width] for index in range(0, len(items), width)]


def search_timeout_for(filters: dict[str, Any], *, industries_dropped: bool = False) -> int:
    """Seconds to wait on search_contacts. Wider filters get more time."""
    if industries_dropped:
        return DROPPED_INDUSTRY_TIMEOUT
    states = _as_list(filters.get("states"))
    titles = _as_list(filters.get("job_titles"))
    excludes = _as_list(filters.get("exclude_domains"))
    if len(states) > STATE_BATCH or len(titles) > TITLE_BATCH or len(excludes) >= 100:
        return LARGE_SEARCH_TIMEOUT
    return SEARCH_TIMEOUT


def search_filter_slices(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Split a wide filter so one search_contacts call can finish.

    Many states go out in batches of three. After industries are gone, a long
    title list is split the same way. A short filter stays one query.
    """
    states = _as_list(filters.get("states"))
    titles = _as_list(filters.get("job_titles"))
    if len(states) > STATE_BATCH:
        return [_with_key(filters, "states", chunk) for chunk in _chunks(states, STATE_BATCH)]
    if not _as_list(filters.get("industries")) and len(titles) > TITLE_BATCH:
        return [_with_key(filters, "job_titles", chunk) for chunk in _chunks(titles, TITLE_BATCH)]
    return [dict(filters)]


def industry_probe_slices(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """A few industries, one at a time, before the industry filter is removed."""
    industries = _as_list(filters.get("industries"))
    if len(industries) <= 1:
        return []
    slices: list[dict[str, Any]] = []
    for industry in industries[:INDUSTRY_PROBE]:
        slices.extend(search_filter_slices(_with_key(filters, "industries", [industry])))
    return slices


def dropped_industry_slices(filters: dict[str, Any]) -> list[dict[str, Any]]:
    if not _as_list(filters.get("industries")):
        return []
    dropped = {key: value for key, value in filters.items() if key != "industries"}
    return search_filter_slices(dropped)


class GetLeadsClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: McpHttpClient | None = None,
        http: requests.Session | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.http = http or requests.Session()
        self._client = client
        self.errors: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.settings.getleads_api_key and self.settings.getleads_endpoint)

    def client(self) -> McpHttpClient:
        if self._client is None:
            if not self.enabled:
                raise RuntimeError("GETLEADS_API_KEY and GETLEADS_ENDPOINT are required")
            self._client = McpHttpClient(
                url=self.settings.getleads_endpoint,
                token=self.settings.getleads_api_key,
                timeout=90,
            )
        return self._client

    def count(self, filters: dict[str, Any]) -> dict[str, Any]:
        args = getleads_search_args(filters)
        with getleads_slot():
            return self.client().call_tool("count_contacts", args)

    def search(
        self,
        filters: dict[str, Any],
        *,
        limit: int = 100,
        offset: int = 0,
        timeout: int | None = None,
        industries_dropped: bool = False,
    ) -> list[dict[str, str]]:
        args = getleads_search_args(filters)
        args["limit"] = max(1, min(int(limit), 100))
        args["offset"] = max(0, int(offset))
        args["columns"] = list(GETLEADS_EXPORT_COLUMNS)
        chosen = search_timeout_for(filters, industries_dropped=industries_dropped)
        if timeout is not None:
            chosen = timeout
        with getleads_slot():
            data = self.client().call_tool("search_contacts", args, timeout=chosen)
        return [contact_from_raw(row) for row in unwrap_records(data)]

    def pull(
        self,
        filters: dict[str, Any],
        *,
        max_rows: int,
        max_per_company: int = 1,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, str]]:
        """Search in pages first; use export when the ask is bigger than 200."""
        if max_rows > 200:
            try:
                return self.export(
                    filters,
                    max_rows=max_rows,
                    max_per_company=max_per_company,
                    progress=progress,
                )
            except (McpError, RuntimeError) as exc:
                self.errors.append(f"export_fallback: {exc}")
        rows: list[dict[str, str]] = []
        offset = 0
        page_size = 100
        while len(rows) < max_rows:
            batch = self.search(filters, limit=min(page_size, max_rows - len(rows)), offset=offset)
            if not batch:
                break
            rows.extend(batch)
            offset += len(batch)
            if progress:
                progress({"pulled": len(rows), "target": max_rows, "mode": "search"})
            if len(batch) < page_size:
                break
        return rows[:max_rows]

    def export(
        self,
        filters: dict[str, Any],
        *,
        max_rows: int,
        max_per_company: int = 1,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, str]]:
        args = getleads_search_args(filters)
        args["confirmed"] = True
        args["max_rows"] = max(1, min(int(max_rows), 50000))
        args["max_per_company"] = max(1, min(int(max_per_company), 50))
        args["columns"] = list(GETLEADS_EXPORT_COLUMNS)
        with getleads_slot():
            started = self.client().call_tool("export_contacts", args)
        export_id = str(started.get("export_id") or started.get("id") or "")
        if not export_id:
            raise RuntimeError(f"export_contacts did not return export_id: {started}")
        deadline = time.time() + 180
        status: dict[str, Any] = {}
        while time.time() < deadline:
            with getleads_slot():
                status = self.client().call_tool("check_contact_export", {"export_id": export_id})
            job_status = str(status.get("job_status") or status.get("status") or "").lower()
            if progress:
                progress({"export_id": export_id, "status": job_status})
            if job_status in {"completed", "complete", "done", "success"}:
                break
            if job_status in {"failed", "error"}:
                raise RuntimeError(f"GetLeads export failed: {status}")
            time.sleep(2)
        url = str(status.get("export_url") or status.get("url") or "")
        if not url:
            raise RuntimeError(f"GetLeads export had no URL: {status}")
        resp = self.http.get(url, timeout=90)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        return [contact_from_raw(dict(row)) for row in reader]
