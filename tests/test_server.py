from mcp_server.server import mcp


def test_server_exposes_expected_tools():
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {
        "build_enriched_list",
        "whale_dossier",
        "get_job_status",
        "fetch_job_result",
        "exclude_add",
        "exclude_check",
        "exclude_count",
        "exclude_import",
        "list_jobs",
        "list_deliveries",
        "health",
    } <= names
