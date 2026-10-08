"""Moby Dick MCP. Claude calls these tools. Lists stay in CSVs, not chat."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from mcp_server.playbook import INSTRUCTIONS, WHEN_TO_USE
from mobydick.config import ROOT, load_settings

mcp = MCPServer(
    name="mobydick",
    title="Moby Dick",
    description=(
        "SalesGlider prospect research and personalization. "
        "Bulk enriched founder/PE lists and whale gift dossiers. "
        "Never dumps lead lists into chat."
    ),
    instructions=INSTRUCTIONS,
    version="1.0.0",
)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _ensure_cwd() -> None:
    os.chdir(ROOT)


def _http_mode() -> bool:
    return os.environ.get("MCP_TRANSPORT", "stdio").lower() in (
        "streamable-http",
        "http",
        "sse",
    )


def _store():
    from mobydick.store import Store

    return Store()


@mcp.resource(
    "mobydick://playbook",
    name="playbook",
    description="How Moby Dick builds lists and whale dossiers.",
    mime_type="text/markdown",
)
def playbook_resource() -> str:
    return INSTRUCTIONS


@mcp.prompt(
    name="when_to_use",
    description="Decide whether Moby Dick applies.",
)
def when_to_use_prompt() -> str:
    return WHEN_TO_USE


@mcp.tool(
    annotations=ToolAnnotations(
        title="Health / config check",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def health() -> str:
    """Show which connectors are configured. Never prints secrets."""
    _ensure_cwd()
    settings = load_settings()
    store = _store()
    return _json(
        {
            "ok": True,
            "service": "mobydick",
            "product": "prospect_research_personalization",
            "never": ["flowers_engine", "free_poc", "home_address", "chat_list_dump"],
            "connectors": {
                "getleads": bool(settings.getleads_api_key),
                "email_waterfall": bool(settings.email_waterfall_url),
                "leadmagic": bool(settings.leadmagic_api_key),
                "youtube": bool(settings.youtube_api_key),
                "taddy": bool(settings.taddy_api_key and settings.taddy_user_id),
                "apify": bool(settings.apify_api_key),
                "anthropic": bool(settings.anthropic_api_key),
                "openai": bool(settings.openai_api_key),
            },
            "client_tag": settings.email_waterfall_client_tag,
            "download_signing": _download_signing(),
            "life_extraction": _life_extraction_status(settings),
            "exclude": {
                "series_ab": store.exclude_count("series_ab"),
                "pe_partners": store.exclude_count("pe_partners"),
            },
            "data_dir": str(settings.data_dir),
        }
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Build an enriched lead list",
        readOnlyHint=False,
        openWorldHint=True,
        destructiveHint=False,
    )
)
def build_enriched_list(
    audience: str,
    count: int = 100,
    filters: dict[str, Any] | None = None,
    funded_since: str = "2024-01-01",
    require_email: bool = True,
    overfetch: float = 2.0,
    background: bool = True,
    enrich: bool = True,
    story_first: bool = True,
) -> str:
    """Pull, de-dupe, enrich, and write one CSV.

    audience = series_ab | pe_partners
    count = how many NEW unique companies to deliver
    filters = optional GetLeads overrides (job_titles, industries, states, ...)
    story_first defaults on for pe_partners. A row ships only with a cited personal fact.
    If the scan cap is hit first, the shortfall is the number still missing.
    scan_stop says filled, scan_cap, source_exhausted, or upstream_error. GetLeads stops a search at 50 seconds. A wide state list is searched three states at a time, 25 rows a page. An empty industry slice is tried one industry at a time, then paged without that filter. A timeout still writes the people already verified.
    Long jobs return job_id. Poll get_job_status. Never dumps the list into chat.
    """
    _ensure_cwd()
    from mobydick.audiences import normalize_audience
    from mobydick.pipeline import build_enriched_list as _build

    name = normalize_audience(audience)
    wanted = max(1, min(int(count), 2000))

    def _run(job: Any | None = None) -> dict[str, Any]:
        def on_progress(snapshot: dict[str, Any]) -> None:
            if job is not None:
                from mcp_server.jobs import update_job_progress

                update_job_progress(job.id, {"stage_update": snapshot})

        return _build(
            name,
            wanted,
            filters=filters,
            funded_since=funded_since,
            require_email=require_email,
            overfetch=overfetch,
            enrich=enrich,
            story_first=story_first,
            progress=on_progress,
        )

    if background and (_http_mode() or wanted > 25):
        from mcp_server.jobs import start_job

        job = start_job(
            "build_enriched_list",
            lambda j: _run(j),
            meta={"audience": name, "count": wanted},
        )
        return _json(
            {
                "job_id": job.id,
                "status": job.status,
                "audience": name,
                "requested": wanted,
                "message": (
                    f"Poll get_job_status with job_id={job.id}. "
                    "When it finishes, call download_delivery to save the CSV. "
                    "Do not paste the list into chat."
                ),
            }
        )
    return _json(_run())


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get job status",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def get_job_status(job_id: str) -> str:
    """Poll a background list or dossier job."""
    from mcp_server.jobs import get_job

    return _json(get_job(job_id).to_public())


@mcp.tool(
    annotations=ToolAnnotations(
        title="Fetch job result (counts + CSV path)",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def fetch_job_result(job_id: str) -> str:
    """Return counts, samples, and the CSV/dossier path. Never the full list."""
    from mcp_server.jobs import get_job

    job = get_job(job_id)
    public = job.to_public()
    result = public.get("result") or {}
    if isinstance(result, dict):
        result.pop("rows", None)
        result.pop("contacts", None)
        if result.get("csv_name") or result.get("csv_path"):
            result["download_tool"] = "download_delivery"
            result["download_note"] = (
                "Call download_delivery with this job_id or csv_name. Do not paste the list into chat."
            )
    return _json(public)


@mcp.tool(
    annotations=ToolAnnotations(
        title="List background jobs",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def list_jobs(limit: int = 20) -> str:
    """List recent Moby Dick jobs."""
    from mcp_server.jobs import list_jobs as _list

    return _json([j.to_public() for j in _list(limit=limit)])


@mcp.tool(
    annotations=ToolAnnotations(
        title="Whale gift dossier",
        readOnlyHint=False,
        openWorldHint=True,
        destructiveHint=False,
    )
)
def whale_dossier(
    full_name: str,
    firm: str,
    title: str = "",
    linkedin_url: str = "",
    company_website: str = "",
    company_domain: str = "",
    use_apify: bool = False,
) -> str:
    """Deep public research + ~$100 gift ideas for one PE prospect.

    Cuts bait if the footprint is only LinkedIn. Never contacts the person.
    """
    _ensure_cwd()
    from mobydick.dossier import build_dossier

    payload = build_dossier(
        full_name,
        firm,
        title=title,
        linkedin_url=linkedin_url,
        company_website=company_website,
        company_domain=company_domain,
        use_apify=use_apify,
        store=_store(),
    )
    return _json(payload)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Add delivered domains to the exclude list",
        readOnlyHint=False,
        openWorldHint=False,
        destructiveHint=False,
    )
)
def exclude_add(domains: list[str], list_name: str = "series_ab") -> str:
    """Add company domains so they never ship again."""
    return _json(_store().exclude_add(domains, list_name))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Remove domains from the exclude list",
        readOnlyHint=False,
        openWorldHint=False,
        destructiveHint=False,
    )
)
def exclude_remove(domains: list[str], list_name: str = "series_ab") -> str:
    """Take domains off the exclude list, including ones in today's delivery files."""
    return _json(_store().exclude_remove(domains, list_name))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check domains against the exclude list",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def exclude_check(domains: list[str], list_name: str = "series_ab") -> str:
    """See which domains were already delivered."""
    return _json(_store().exclude_check(domains, list_name))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Count exclude-list domains",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def exclude_count(list_name: str = "series_ab") -> str:
    """How many domains are blocked, including same-day files."""
    return _json(_store().exclude_count(list_name))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Import an exclude list file",
        readOnlyHint=False,
        openWorldHint=False,
        destructiveHint=False,
    )
)
def exclude_import(path: str, list_name: str = "series_ab") -> str:
    """Import domains from a JSON list or a CSV with company_domain."""
    return _json(_store().exclude_import(path, list_name))


@mcp.tool(
    annotations=ToolAnnotations(
        title="List delivered CSV files",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def list_deliveries(limit: int = 20) -> str:
    """Recent delivery files. Paths only, not contents."""
    return _json(_store().list_deliveries(limit=limit))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Download a delivery CSV",
        readOnlyHint=True,
        openWorldHint=False,
    )
)
def download_delivery(job_id: str = "", filename: str = "") -> str:
    """Return one delivery CSV by completed job id or delivery filename.

    csv_text is the file. download_url is a 15-minute signed link when signing
    is configured. Save the file locally. Do not paste the list into chat.
    Samples on other tools stay redacted.
    """
    _ensure_cwd()
    from mcp_server.jobs import get_job

    from mobydick.downloads import build_delivery_download

    job_status = None
    job_csv = None
    if (job_id or "").strip():
        job = get_job(job_id)
        job_status = job.status
        result = job.result if isinstance(job.result, dict) else {}
        job_csv = str(result.get("csv_name") or "")
        if not job_csv and result.get("csv_path"):
            job_csv = Path(str(result["csv_path"])).name
    payload = build_delivery_download(
        job_id=job_id,
        filename=filename,
        deliveries_dir=_store().settings.deliveries_dir,
        job_status=job_status,
        job_csv_name=job_csv,
    )
    return _json(payload)


def _life_extraction_status(settings: Any) -> dict[str, Any]:
    from mobydick.research.life import NO_MODEL_WARNING, llm_keys_present

    enabled = llm_keys_present() or bool(
        getattr(settings, "anthropic_api_key", "") or getattr(settings, "openai_api_key", "")
    )
    return {
        "mode": "llm" if enabled else "heuristic",
        "env": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
        "warning": "" if enabled else NO_MODEL_WARNING,
    }


def _download_signing() -> bool:
    from mobydick.downloads import signing_configured

    return signing_configured()


def _mount_http_routes() -> None:
    try:
        from starlette.requests import Request
        from starlette.responses import JSONResponse, PlainTextResponse
    except ImportError:
        return

    @mcp.custom_route("/", methods=["GET"])
    async def root_page(_request: Request) -> PlainTextResponse:
        return PlainTextResponse(
            "Moby Dick MCP\n"
            "Claude connector URL: /mcp\n"
            "Health: /health\n"
            "Delivery CSV: signed link from the download_delivery tool\n"
        )

    @mcp.custom_route("/health", methods=["GET"])
    async def health_live(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "service": "mobydick",
                "transport": "streamable-http",
                "mcp_path": "/mcp",
            }
        )

    @mcp.custom_route("/deliveries/{filename}", methods=["GET"])
    async def download_csv(request: Request):
        from starlette.responses import Response

        from mobydick.downloads import build_http_download

        filename = request.path_params.get("filename", "")
        status, body, headers = build_http_download(
            filename,
            request.query_params.get("exp", ""),
            request.query_params.get("sig", ""),
            deliveries_dir=_store().settings.deliveries_dir,
        )
        return Response(content=body, status_code=status, headers=headers)


_mount_http_routes()


def _configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s %(message)s",
            stream=sys.stderr,
        )
    logging.getLogger("mobydick").setLevel(logging.INFO)


def main() -> None:
    _configure_logging()
    _ensure_cwd()
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    if transport in ("streamable-http", "http"):
        kwargs: dict[str, Any] = {
            "transport": "streamable-http",
            "host": host,
            "port": port,
        }
        try:
            from mcp.server.transport_security import TransportSecuritySettings

            kwargs.update(
                {
                    "streamable_http_path": "/mcp",
                    "stateless_http": True,
                    "transport_security": TransportSecuritySettings(
                        enable_dns_rebinding_protection=False
                    ),
                }
            )
        except Exception:
            kwargs["path"] = "/mcp"
        mcp.run(**kwargs)
        return

    if transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
