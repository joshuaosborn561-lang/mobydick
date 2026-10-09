import json

import pytest
import requests

from mobydick.config import Settings
from mobydick.waterfall import (
    ENRICH_ONE_MAX_TIER,
    ENRICH_ONE_NEED,
    EmailWaterfallClient,
    enrich_one_url,
    fill_missing_emails,
    waterfall_http_base,
)


def _settings(tmp_path, **overrides) -> Settings:
    values = dict(
        data_dir=tmp_path,
        getleads_api_key="",
        getleads_endpoint="",
        email_waterfall_url="https://email-waterfall.example/mcp",
        email_waterfall_client_tag="salesglider",
        youtube_api_key="",
        taddy_user_id="",
        taddy_api_key="",
        taddy_endpoint="",
        apify_api_key="",
        apify_actor="",
        anthropic_api_key="",
        openai_api_key="",
        email_waterfall_approve_cost_usd=0.25,
        email_waterfall_run_ceiling_usd=25.0,
    )
    values.update(overrides)
    return Settings(**values)


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class _Session:
    def __init__(self, handler):
        self.handler = handler
        self.posts: list[dict] = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.handler(url, json)


def _missing_row(**overrides) -> dict[str, str]:
    row = {
        "first_name": "Ada",
        "last_name": "Founder",
        "full_name": "Ada Founder",
        "company_name": "Fresh",
        "company_domain": "fresh.com",
        "linkedin_url": "https://linkedin.com/in/ada",
        "email": "",
        "source_note": "getleads",
        "dl_status": "queued",
        "sg_exclude": "0",
        "skip_email": "no",
    }
    row.update(overrides)
    return row


def test_http_base_strips_mcp_suffix():
    assert waterfall_http_base("https://host.example/mcp") == "https://host.example"
    assert enrich_one_url("https://host.example/mcp/") == "https://host.example/enrich-one"


def test_settings_has_no_leadmagic_fields(tmp_path):
    settings = _settings(tmp_path)
    assert not hasattr(settings, "leadmagic_api_key")
    assert not hasattr(settings, "leadmagic_endpoint")


def test_fill_writes_email_from_enrich_one(tmp_path):
    def handler(url, payload):
        assert url == "https://email-waterfall.example/enrich-one"
        assert payload["need"] == ENRICH_ONE_NEED
        assert payload["max_tier"] == ENRICH_ONE_MAX_TIER
        assert payload["approve_cost_usd"] == 0.25
        assert payload["write_supabase"] is False
        assert payload["client_tag"] == "salesglider"
        assert payload["domain"] == "fresh.com"
        for key in ("dl_status", "sg_exclude", "skip_email", "skip_phone", "skip_tiers"):
            assert key not in payload
        return _Resp(
            {
                "ok": True,
                "email": "ada@fresh.com",
                "email_tier": "prospeo",
                "status": "completed",
                "spend": 0.02,
                "estimated_cost_usd": 0.07,
            }
        )

    session = _Session(handler)
    settings = _settings(tmp_path)
    rows = [_missing_row(), {"first_name": "Has", "last_name": "Mail", "email": "has@mail.com", "company_domain": "mail.com"}]
    stats = fill_missing_emails(
        rows,
        settings=settings,
        waterfall=EmailWaterfallClient(settings, http=session),
    )
    assert rows[0]["email"] == "ada@fresh.com"
    assert rows[0]["source_note"] == "getleads prospeo"
    assert stats["filled"] == 1
    assert stats["missing_before"] == 1
    assert stats["still_missing"] == 0
    assert stats["enrich_one_calls"] == 1
    assert stats["estimated_cost_usd"] == 0.25
    assert stats["spend"] == 0.02
    assert stats["stopped_at_ceiling"] is False
    assert len(session.posts) == 1


def test_payload_never_forwards_queue_columns(tmp_path):
    session = _Session(
        lambda url, payload: _Resp({"ok": True, "email": "ada@fresh.com", "email_tier": "aiark", "spend": 0})
    )
    settings = _settings(tmp_path)
    fill_missing_emails(
        [_missing_row()],
        settings=settings,
        waterfall=EmailWaterfallClient(settings, http=session),
    )
    sent = session.posts[0]["json"]
    assert set(sent) == {
        "client_tag",
        "first_name",
        "last_name",
        "full_name",
        "domain",
        "company_name",
        "email",
        "linkedin_url",
        "need",
        "max_tier",
        "write_supabase",
        "approve_cost_usd",
    }


def test_skips_http_when_url_empty(tmp_path):
    session = _Session(lambda url, payload: pytest.fail("must not call enrich-one"))
    settings = _settings(tmp_path, email_waterfall_url="")
    rows = [_missing_row()]
    stats = fill_missing_emails(
        rows,
        settings=settings,
        waterfall=EmailWaterfallClient(settings, http=session),
    )
    assert rows[0]["email"] == ""
    assert stats["enrich_one_calls"] == 0
    assert stats["filled"] == 0
    assert stats["estimated_cost_usd"] == 0.25
    assert session.posts == []


def test_http_error_leaves_email_empty(tmp_path):
    def handler(url, payload):
        raise requests.Timeout("read timed out")

    session = _Session(handler)
    settings = _settings(tmp_path)
    rows = [_missing_row()]
    stats = fill_missing_emails(
        rows,
        settings=settings,
        waterfall=EmailWaterfallClient(settings, http=session),
    )
    assert rows[0]["email"] == ""
    assert stats["filled"] == 0
    assert stats["still_missing"] == 1
    assert stats["enrich_one_calls"] == 1


def test_run_ceiling_stops_further_calls(tmp_path):
    calls = {"n": 0}

    def handler(url, payload):
        calls["n"] += 1
        assert payload["approve_cost_usd"] == 0.25
        return _Resp(
            {
                "ok": True,
                "email": f"p{calls['n']}@co.com",
                "email_tier": "getleads",
                "status": "completed",
                "spend": 0.25,
            }
        )

    session = _Session(handler)
    settings = _settings(tmp_path, email_waterfall_run_ceiling_usd=0.25)
    rows = [
        _missing_row(company_domain="one.com"),
        _missing_row(first_name="Bea", company_domain="two.com"),
        _missing_row(first_name="Cam", company_domain="three.com"),
    ]
    stats = fill_missing_emails(
        rows,
        settings=settings,
        waterfall=EmailWaterfallClient(settings, http=session),
    )
    assert stats["enrich_one_calls"] == 1
    assert stats["filled"] == 1
    assert stats["still_missing"] == 2
    assert stats["stopped_at_ceiling"] is True
    assert stats["estimated_cost_usd"] == 0.75
    assert stats["spend"] == 0.25
    assert rows[0]["email"] == "p1@co.com"
    assert rows[1]["email"] == ""


def test_shrinking_budget_is_passed_then_stops(tmp_path):
    seen_caps: list[float] = []

    def handler(url, payload):
        seen_caps.append(payload["approve_cost_usd"])
        if len(seen_caps) == 1:
            return _Resp(
                {
                    "ok": True,
                    "email": "ada@one.com",
                    "email_tier": "aiark",
                    "status": "completed",
                    "spend": 0.20,
                }
            )
        return _Resp(
            {
                "ok": False,
                "status": "refused_over_ceiling",
                "reason": "estimated_cost_usd=0.07 exceeds approve_cost_usd=0.05",
                "email": "",
            }
        )

    session = _Session(handler)
    settings = _settings(tmp_path, email_waterfall_run_ceiling_usd=0.25)
    rows = [
        _missing_row(company_domain="one.com"),
        _missing_row(first_name="Bea", company_domain="two.com"),
    ]
    stats = fill_missing_emails(
        rows,
        settings=settings,
        waterfall=EmailWaterfallClient(settings, http=session),
    )
    assert seen_caps[0] == 0.25
    assert seen_caps[1] == pytest.approx(0.05)
    assert stats["filled"] == 1
    assert stats["refused_over_ceiling"] == 1
    assert stats["stopped_at_ceiling"] is True
    assert rows[1]["email"] == ""


def test_person_refused_over_default_cap_continues(tmp_path):
    def handler(url, payload):
        domain = payload["domain"]
        if domain == "one.com":
            return _Resp({"ok": False, "status": "refused_over_ceiling", "email": ""})
        return _Resp(
            {
                "ok": True,
                "email": "bea@two.com",
                "email_tier": "smartlead",
                "status": "completed",
                "spend": 0.0,
            }
        )

    session = _Session(handler)
    settings = _settings(tmp_path)
    rows = [
        _missing_row(company_domain="one.com"),
        _missing_row(first_name="Bea", company_domain="two.com"),
    ]
    stats = fill_missing_emails(
        rows,
        settings=settings,
        waterfall=EmailWaterfallClient(settings, http=session),
    )
    assert stats["refused_over_ceiling"] == 1
    assert stats["stopped_at_ceiling"] is False
    assert stats["filled"] == 1
    assert rows[1]["email"] == "bea@two.com"


def test_no_leadmagic_client_export():
    import mobydick.waterfall as wf

    assert not hasattr(wf, "LeadMagicClient")
