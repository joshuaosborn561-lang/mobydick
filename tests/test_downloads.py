import pytest

from mobydick.config import Settings
from mobydick.downloads import (
    build_delivery_download,
    build_http_download,
    signed_url,
    signature_status,
)
from mobydick.store import Store


def _settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        getleads_api_key="",
        getleads_endpoint="",
        email_waterfall_url="",
        email_waterfall_client_tag="salesglider",
        leadmagic_api_key="",
        leadmagic_endpoint="",
        youtube_api_key="",
        taddy_user_id="",
        taddy_api_key="",
        taddy_endpoint="",
        apify_api_key="",
        apify_actor="",
        anthropic_api_key="",
        openai_api_key="",
    )


def _clear_secrets(monkeypatch):
    for key in ("MOBYDICK_DOWNLOAD_SECRET", "GETLEADS_API_KEY", "LEADMAGIC_API_KEY"):
        monkeypatch.setenv(key, "")


def test_signed_download_round_trip(tmp_path, monkeypatch):
    _clear_secrets(monkeypatch)
    monkeypatch.setenv("MOBYDICK_DOWNLOAD_SECRET", "test-secret")
    monkeypatch.setenv("MOBYDICK_PUBLIC_URL", "https://mobydick.example")
    store = Store(_settings(tmp_path))
    path = store.write_delivery(
        "pe_partners",
        [{"full_name": "Pat Partner", "email": "secret@firm.com", "company_domain": "firm.pe"}],
    )
    now = 1_700_000_000
    payload = build_delivery_download(
        filename=path.name,
        deliveries_dir=store.settings.deliveries_dir,
        now=now,
    )
    assert payload["filename"] == path.name
    assert "secret@firm.com" in payload["csv_text"]
    assert payload["download_url"].startswith("https://mobydick.example/deliveries/")
    assert "exp=" in payload["download_url"]
    assert payload["note"].startswith("Save this file")
    exp = payload["download_url"].split("exp=", 1)[1].split("&", 1)[0]
    sig = payload["download_url"].split("sig=", 1)[1]
    status, body, headers = build_http_download(
        path.name,
        exp,
        sig,
        deliveries_dir=store.settings.deliveries_dir,
        now=now + 10,
    )
    assert status == 200
    assert "secret@firm.com" in body
    assert "attachment" in headers["Content-Disposition"]
    assert signature_status(path.name, exp, sig, now=now + 16 * 60) == "expired"
    expired, _, _ = build_http_download(
        path.name,
        exp,
        sig,
        deliveries_dir=store.settings.deliveries_dir,
        now=now + 16 * 60,
    )
    assert expired == 410
    bad, _, _ = build_http_download(
        path.name,
        exp,
        "0" * 64,
        deliveries_dir=store.settings.deliveries_dir,
        now=now + 10,
    )
    assert bad == 403


def test_download_rejects_traversal_and_unsigned_names(tmp_path, monkeypatch):
    _clear_secrets(monkeypatch)
    monkeypatch.setenv("MOBYDICK_DOWNLOAD_SECRET", "test-secret")
    store = Store(_settings(tmp_path))
    with pytest.raises(ValueError):
        build_delivery_download(
            filename="../secrets.csv",
            deliveries_dir=store.settings.deliveries_dir,
        )
    missing, _, _ = build_http_download(
        "pe_partners_enriched_10_2026-10-05_210923.csv",
        "1700000900",
        "not-a-signature",
        deliveries_dir=store.settings.deliveries_dir,
        now=1_700_000_000,
    )
    assert missing == 403
    _clear_secrets(monkeypatch)
    status, _, _ = build_http_download(
        "pe_partners_enriched_10_2026-10-05_210923.csv",
        "1700000900",
        "abc",
        deliveries_dir=store.settings.deliveries_dir,
        now=1_700_000_000,
    )
    assert status == 503
    assert signed_url("pe_partners_enriched_10_2026-10-05_210923.csv") == ""


def test_download_by_job_id(tmp_path, monkeypatch):
    _clear_secrets(monkeypatch)
    monkeypatch.setenv("MOBYDICK_DOWNLOAD_SECRET", "test-secret")
    monkeypatch.delenv("MOBYDICK_PUBLIC_URL", raising=False)
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "mobydick.example")
    store = Store(_settings(tmp_path))
    path = store.write_delivery("series_ab", [{"full_name": "Ada Founder", "company_domain": "fresh.com"}])
    payload = build_delivery_download(
        job_id="abc123",
        deliveries_dir=store.settings.deliveries_dir,
        job_status="completed",
        job_csv_name=str(path),
    )
    assert payload["filename"] == path.name
    assert payload["download_url"].startswith(f"https://mobydick.example/deliveries/{path.name}?")
    assert "Ada Founder" in payload["csv_text"]
    partial = build_delivery_download(
        job_id="abc123",
        deliveries_dir=store.settings.deliveries_dir,
        job_status="completed_partial",
        job_csv_name=path.name,
    )
    assert partial["filename"] == path.name
    with pytest.raises(ValueError):
        build_delivery_download(
            job_id="abc123",
            deliveries_dir=store.settings.deliveries_dir,
            job_status="running",
            job_csv_name=path.name,
        )
