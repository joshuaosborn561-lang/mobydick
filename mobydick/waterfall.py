"""Fill missing emails: GetLeads already tried, then LeadMagic, plus waterfall MCP write."""

from __future__ import annotations

from typing import Any, Callable

import requests

from mobydick.config import Settings, settings as default_settings
from mobydick.mcp_http import McpHttpClient


class LeadMagicClient:
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
        return bool(self.settings.leadmagic_api_key)

    def find_email(self, first_name: str, last_name: str, domain: str) -> str:
        if not self.enabled or not (first_name and last_name and domain):
            return ""
        self.calls += 1
        url = self.settings.leadmagic_endpoint.rstrip("/") + "/v1/people/email-finder"
        try:
            resp = self.http.post(
                url,
                json={
                    "first_name": first_name,
                    "last_name": last_name,
                    "domain": domain,
                },
                headers={
                    "X-API-Key": self.settings.leadmagic_api_key,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
        except requests.RequestException:
            return ""
        if resp.status_code >= 400:
            return ""
        try:
            data = resp.json()
        except ValueError:
            return ""
        nested = data.get("data") if isinstance(data.get("data"), dict) else {}
        email = data.get("email") or data.get("work_email") or nested.get("email") or ""
        email = str(email or "").strip().lower()
        if email and "@" in email and "*" not in email:
            self.hits += 1
            return email
        return ""


class EmailWaterfallClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: McpHttpClient | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.settings.email_waterfall_url)

    def client(self) -> McpHttpClient:
        if self._client is None:
            self._client = McpHttpClient(
                url=self.settings.email_waterfall_url,
                token="",
                timeout=90,
            )
        return self._client

    def ensure_client(self) -> dict[str, Any]:
        return self.client().call_tool(
            "ensure_client",
            {
                "client_tag": self.settings.email_waterfall_client_tag,
                "display_name": "SalesGlider / Moby Dick",
                "profile": "owner",
            },
        )

    def enrich(self, rows: list[dict[str, Any]], *, background: bool = False) -> dict[str, Any]:
        """Write missing-email rows into the salesglider waterfall tables.

        The MCP never returns contact payloads. Local LeadMagic fills the CSV.
        """
        if not rows:
            return {"ok": True, "skipped": True, "reason": "no_rows"}
        payload = []
        for row in rows:
            payload.append(
                {
                    "domain": row.get("company_domain") or "",
                    "company_name": row.get("company_name") or "",
                    "first_name": row.get("first_name") or "",
                    "last_name": row.get("last_name") or "",
                    "title": row.get("title") or "",
                    "email": row.get("email") or "",
                    "linkedin_url": row.get("linkedin_url") or "",
                }
            )
        try:
            self.ensure_client()
            return self.client().call_tool(
                "enrich_waterfall",
                {
                    "rows": payload,
                    "client_tag": self.settings.email_waterfall_client_tag,
                    "need": "email",
                    "max_tier": "leadmagic",
                    "background": background,
                    "require_title_match": False,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:300]}


def fill_missing_emails(
    rows: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    leadmagic: LeadMagicClient | None = None,
    waterfall: EmailWaterfallClient | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cfg = settings or default_settings
    lm = leadmagic or LeadMagicClient(cfg)
    wf = waterfall or EmailWaterfallClient(cfg)
    missing = [r for r in rows if not (r.get("email") or "").strip()]
    filled = 0
    for row in missing:
        email = lm.find_email(
            row.get("first_name") or "",
            row.get("last_name") or "",
            row.get("company_domain") or "",
        )
        if email:
            row["email"] = email
            row["source_note"] = ((row.get("source_note") or "") + " leadmagic").strip()
            filled += 1
        if progress:
            progress({"missing": len(missing), "filled": filled})
    wf_result: dict[str, Any] = {"skipped": True}
    still_missing = [r for r in rows if not (r.get("email") or "").strip()]
    if still_missing and wf.enabled:
        wf_result = wf.enrich(still_missing, background=True)
    return {
        "missing_before": len(missing),
        "filled": filled,
        "still_missing": sum(1 for r in rows if not (r.get("email") or "").strip()),
        "leadmagic_calls": lm.calls,
        "waterfall": wf_result,
    }
