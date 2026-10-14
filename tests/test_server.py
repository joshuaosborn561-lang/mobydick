import json

from mcp_server.server import health, mcp


def test_health_reports_serper_for_google_search_and_apify_for_scrape(monkeypatch, tmp_path):
    monkeypatch.setenv("MOBYDICK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SERPER_API_KEY", "serper-key")
    monkeypatch.setenv("APIFY_API_KEY", "apify-key")
    payload = json.loads(health())
    assert payload["connectors"]["serper"] is True
    assert payload["connectors"]["apify"] is True

    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("APIFY_API_KEY", raising=False)
    empty = json.loads(health())
    assert empty["connectors"]["serper"] is False
    assert empty["connectors"]["apify"] is False


def test_server_exposes_expected_tools():
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {
        "build_enriched_list",
        "whale_dossier",
        "get_job_status",
        "fetch_job_result",
        "exclude_add",
        "exclude_remove",
        "exclude_check",
        "exclude_count",
        "exclude_import",
        "list_jobs",
        "list_deliveries",
        "download_delivery",
        "health",
    } <= names
