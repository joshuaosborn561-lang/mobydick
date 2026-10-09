"""Fill missing emails via Email Waterfall POST /enrich-one.

LeadMagic is gone. Order on the service is getleads → Smartlead → AI Ark →
Prospeo → FullEnrich. Each person is estimated first (approve_cost_usd,
default $0.25). A run stops when spend would exceed the run ceiling.
Payloads never include dl_status, sg_exclude, or skip_* — those columns
are not read or written. Data stays server to server.
"""

from __future__ import annotations

from typing import Any, Callable

import requests

from mobydick.config import Settings, settings as default_settings

FORBIDDEN_ROW_KEYS = frozenset(
    {
        "dl_status",
        "sg_exclude",
        "skip_email",
        "skip_phone",
        "skip_enrich",
        "skip_tiers",
    }
)
ENRICH_ONE_NEED = "email"
ENRICH_ONE_MAX_TIER = "fullenrich"
ENRICH_ONE_TIMEOUT = 90


def waterfall_http_base(mcp_url: str) -> str:
    """Derive the HTTP origin from EMAIL_WATERFALL_MCP_URL (.../mcp)."""
    url = (mcp_url or "").strip().rstrip("/")
    if url.endswith("/mcp"):
        url = url[: -len("/mcp")]
    return url.rstrip("/")


def enrich_one_url(mcp_url: str) -> str:
    base = waterfall_http_base(mcp_url)
    return f"{base}/enrich-one" if base else ""


def _clean_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if email and "@" in email and "*" not in email:
        return email
    return ""


def _is_skip_column(key: str) -> bool:
    return key == "sg_exclude" or key == "dl_status" or key.startswith("skip_")


class EmailWaterfallClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http: requests.Session | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.http = http or requests.Session()
        self.calls = 0
        self.hits = 0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.email_waterfall_url and enrich_one_url(self.settings.email_waterfall_url))

    def enrich_one(
        self,
        row: dict[str, Any],
        *,
        approve_cost_usd: float | None = None,
    ) -> dict[str, Any]:
        """POST /enrich-one. Returns the compact hit or an error-shaped dict."""
        url = enrich_one_url(self.settings.email_waterfall_url)
        if not url:
            return {"ok": False, "reason": "email_waterfall_unconfigured"}
        first = str(row.get("first_name") or "").strip()
        last = str(row.get("last_name") or "").strip()
        domain = str(row.get("company_domain") or row.get("domain") or "").strip()
        company = str(row.get("company_name") or "").strip()
        full_name = str(row.get("full_name") or row.get("name") or "").strip()
        if not domain and not (first and last and company):
            return {"ok": False, "reason": "need_domain_or_name_company"}
        ceiling = (
            self.settings.email_waterfall_approve_cost_usd
            if approve_cost_usd is None
            else float(approve_cost_usd)
        )
        payload = {
            "client_tag": self.settings.email_waterfall_client_tag,
            "first_name": first,
            "last_name": last,
            "full_name": full_name,
            "domain": domain,
            "company_name": company,
            "email": _clean_email(row.get("email")),
            "linkedin_url": str(row.get("linkedin_url") or "").strip(),
            "need": ENRICH_ONE_NEED,
            "max_tier": ENRICH_ONE_MAX_TIER,
            "write_supabase": False,
            "approve_cost_usd": ceiling,
        }
        leaked = [key for key in payload if _is_skip_column(key) or key in FORBIDDEN_ROW_KEYS]
        if leaked:
            raise RuntimeError(f"enrich-one payload must not include {leaked}")
        self.calls += 1
        try:
            resp = self.http.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=ENRICH_ONE_TIMEOUT,
            )
        except requests.RequestException as exc:
            return {"ok": False, "reason": f"http_error: {exc}"[:300]}
        try:
            data = resp.json()
        except ValueError:
            return {"ok": False, "reason": f"non_json:{resp.status_code}"}
        if not isinstance(data, dict):
            return {"ok": False, "reason": "invalid_json"}
        if resp.status_code >= 400 and "ok" not in data:
            data = {**data, "ok": False, "reason": data.get("reason") or f"http_{resp.status_code}"}
        email = _clean_email(data.get("email"))
        if email:
            self.hits += 1
        return data


def fill_missing_emails(
    rows: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    waterfall: EmailWaterfallClient | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cfg = settings or default_settings
    wf = waterfall or EmailWaterfallClient(cfg)
    missing = [r for r in rows if not (r.get("email") or "").strip()]
    per_person = float(cfg.email_waterfall_approve_cost_usd)
    run_ceiling = float(cfg.email_waterfall_run_ceiling_usd)
    estimated = round(len(missing) * per_person, 6)
    filled = 0
    spend = 0.0
    refused = 0
    stopped = False
    if missing and wf.enabled:
        for row in missing:
            remaining = run_ceiling - spend
            if remaining <= 0:
                stopped = True
                break
            person_cap = min(per_person, remaining)
            hit = wf.enrich_one(row, approve_cost_usd=person_cap)
            status = str(hit.get("status") or "")
            if status == "refused_over_ceiling":
                refused += 1
                if person_cap < per_person:
                    stopped = True
                    break
                continue
            spend += float(hit.get("spend") or 0.0)
            email = _clean_email(hit.get("email"))
            if email:
                row["email"] = email
                tier = str(hit.get("email_tier") or "email_waterfall").strip() or "email_waterfall"
                row["source_note"] = ((row.get("source_note") or "") + f" {tier}").strip()
                filled += 1
            if status == "stopped_at_ceiling" or hit.get("reason") == "stopped_at_ceiling":
                stopped = True
                break
            if progress:
                progress({"missing": len(missing), "filled": filled, "spend": spend})
    elif progress:
        progress({"missing": len(missing), "filled": 0})
    return {
        "missing_before": len(missing),
        "filled": filled,
        "still_missing": sum(1 for r in rows if not (r.get("email") or "").strip()),
        "enrich_one_calls": wf.calls,
        "estimated_cost_usd": estimated,
        "spend": round(spend, 6),
        "approve_cost_usd": per_person,
        "run_ceiling_usd": run_ceiling,
        "stopped_at_ceiling": stopped,
        "refused_over_ceiling": refused,
        "need": ENRICH_ONE_NEED,
        "max_tier": ENRICH_ONE_MAX_TIER,
    }
