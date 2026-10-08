import pytest

from mcp_server.jobs import format_job_error
from mobydick.getleads import GetLeadsClient, contact_from_raw
from mobydick.mcp_http import McpError
from mobydick.schemas import GETLEADS_EXPORT_COLUMNS


# Names that are not in the current GetLeads field catalog. search_contacts
# returns invalid_columns (MCP isError) when any of these are requested.
CLASSIC_COLUMNS = {
    "title",
    "email",
    "location",
    "headquarters_country",
    "funding_type",
    "funding_amount",
    "funding_date",
}


class _FakeMcp:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.timeouts = []

    def call_tool(self, name, args, timeout=None):
        self.calls.append((name, args))
        self.timeouts.append(timeout)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_export_columns_use_current_catalog_names():
    assert CLASSIC_COLUMNS.isdisjoint(GETLEADS_EXPORT_COLUMNS)
    for name in (
        "current_title",
        "work_email",
        "contact_location",
        "company_hq_country",
        "last_funding_type",
        "last_funding_amount",
        "last_funding_date",
    ):
        assert name in GETLEADS_EXPORT_COLUMNS


def test_search_sends_catalog_columns_and_maps_new_fields():
    fake = _FakeMcp(
        {
            "contacts": [
                {
                    "full_name": "Pat Partner",
                    "first_name": "Pat",
                    "last_name": "Partner",
                    "current_title": "Managing Partner",
                    "work_email": "Pat@Firm.example",
                    "company_name": "Firm Capital",
                    "company_domain": "firm.example",
                    "current_employer_website": "https://firm.example",
                    "contact_location": "Austin, Texas",
                    "contact_country": "United States",
                    "company_hq_country": "United States",
                    "company_industry": "Venture Capital and Private Equity Principals",
                    "last_funding_type": "series a",
                    "last_funding_amount": "12000000",
                    "last_funding_date": "2024-06-01",
                }
            ]
        }
    )
    client = GetLeadsClient(client=fake)
    rows = client.search(
        {
            "job_titles": ["Partner"],
            "headquarters_countries": ["United States"],
            "require_email": True,
        },
        limit=10,
        offset=0,
    )
    name, args = fake.calls[0]
    assert name == "search_contacts"
    assert args["limit"] == 10
    assert args["offset"] == 0
    assert args["columns"] == list(GETLEADS_EXPORT_COLUMNS)
    assert CLASSIC_COLUMNS.isdisjoint(args["columns"])
    assert rows[0]["title"] == "Managing Partner"
    assert rows[0]["email"] == "pat@firm.example"
    assert rows[0]["company_website"] == "https://firm.example"
    assert rows[0]["location"] == "Austin, Texas"
    assert rows[0]["contact_country"] == "United States"
    assert rows[0]["company_hq_country"] == "United States"
    assert rows[0]["company_industry"] == "Venture Capital and Private Equity Principals"
    assert rows[0]["funding_round"] == "series a"
    assert rows[0]["funding_date"] == "2024-06-01"
    assert rows[0]["company_domain"] == "firm.example"


def test_contact_from_raw_still_reads_legacy_keys():
    row = contact_from_raw(
        {
            "full_name": "Ada Founder",
            "title": "CEO",
            "email": "Ada@Fresh.com",
            "company_domain": "fresh.com",
            "funding_type": "series b",
            "funding_date": "2024-02-01",
        }
    )
    assert row["email"] == "ada@fresh.com"
    assert row["title"] == "CEO"
    assert row["funding_round"] == "series b"


def test_job_error_includes_upstream_body():
    exc = McpError(
        "MCP tool search_contacts failed: invalid_columns: title",
        is_tool_error=True,
        body="invalid_columns: title",
    )
    text = format_job_error(exc)
    assert "invalid_columns" in text
    assert text.startswith("McpError:")


def test_wide_filters_are_split_and_wait_longer():
    from mobydick.getleads import (
        DROPPED_INDUSTRY_TIMEOUT,
        LARGE_SEARCH_TIMEOUT,
        SEARCH_TIMEOUT,
        industry_probe_slices,
        search_filter_slices,
        search_timeout_for,
    )

    small = {"job_titles": ["Partner"], "states": ["Texas"]}
    assert search_timeout_for(small) == SEARCH_TIMEOUT
    large = {
        "job_titles": ["Partner", "Principal", "Founder", "Director"],
        "states": ["AL", "AK", "AZ", "AR"],
    }
    assert search_timeout_for(large) == LARGE_SEARCH_TIMEOUT
    assert search_timeout_for(small, industries_dropped=True) == DROPPED_INDUSTRY_TIMEOUT

    states = ["AL", "AK", "AZ", "AR", "CA"]
    slices = search_filter_slices(
        {"states": states, "job_titles": ["Partner"] * 6, "industries": ["Private Equity"]}
    )
    assert [item["states"] for item in slices] == [["AL", "AK", "AZ"], ["AR", "CA"]]
    assert all(len(item["states"]) <= 3 for item in slices)

    widened = search_filter_slices(
        {"job_titles": ["Partner", "Principal", "Founder", "Director"], "company_description": "private equity"}
    )
    assert [item["job_titles"] for item in widened] == [
        ["Partner", "Principal", "Founder"],
        ["Director"],
    ]

    industries = ["Private Equity", "Investment Management", "Capital Markets", "Banking"]
    probed = industry_probe_slices({"industries": industries, "states": ["Texas"], "job_titles": ["Partner"]})
    assert [item["industries"] for item in probed] == [
        ["Private Equity"],
        ["Investment Management"],
        ["Capital Markets"],
    ]


def test_search_sends_the_longer_timeout_when_industries_were_dropped():
    from mobydick.getleads import DROPPED_INDUSTRY_TIMEOUT

    fake = _FakeMcp({"contacts": []})
    client = GetLeadsClient(client=fake)
    client.search({"job_titles": ["Partner"], "states": ["Texas"]}, industries_dropped=True)
    assert fake.timeouts == [DROPPED_INDUSTRY_TIMEOUT]


def test_search_failure_message_includes_tool_body():
    detail = "invalid_columns: [\"email\"]"
    fake = _FakeMcp(McpError(f"MCP tool isError: {detail}", is_tool_error=True, body=detail))
    client = GetLeadsClient(client=fake)
    with pytest.raises(McpError) as caught:
        client.search({"job_titles": ["CEO"]}, limit=1)
    assert "invalid_columns" in str(caught.value)
