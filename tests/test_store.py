import json

from mobydick.config import Settings
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


def test_exclude_add_check_count(tmp_path):
    store = Store(_settings(tmp_path))
    added = store.exclude_add(["https://www.One.com", "one.com", "two.io"], "series_ab")
    assert added["added"] == 2
    assert added["total"] == 2
    check = store.exclude_check(["one.com", "new.co"], "series_ab")
    assert check["already_delivered"] == ["one.com"]
    assert check["new"] == ["new.co"]
    counts = store.exclude_count("series_ab")
    assert counts["persisted"] == 2
    assert counts["effective"] >= 2


def test_same_day_delivery_counts_as_excluded(tmp_path):
    store = Store(_settings(tmp_path))
    store.write_delivery(
        "series_ab",
        [
            {
                "full_name": "A Person",
                "title": "CEO",
                "company_name": "Acme",
                "company_domain": "acme.test",
            }
        ],
    )
    assert "acme.test" in store.exclude_domains("series_ab")
    counts = store.exclude_count("series_ab")
    assert counts["persisted"] == 1


def test_exclude_remove_overrides_same_day_and_unverified_rows(tmp_path):
    store = Store(_settings(tmp_path))
    store.write_delivery(
        "pe_partners",
        [
            {
                "full_name": "Good Person",
                "company_name": "Good",
                "company_domain": "good.com",
                "person_verified": "yes",
            },
            {
                "full_name": "Bad Person",
                "company_name": "Ardan Equity",
                "company_domain": "ardanequity.com",
                "person_verified": "",
            },
        ],
    )
    payload = json.loads(store._exclude_path("pe_partners").read_text(encoding="utf-8"))
    assert payload["domains"] == ["good.com"]
    # Today's file still lists the unverified domain, so it counts until remove.
    assert "ardanequity.com" in store.exclude_domains("pe_partners")
    removed = store.exclude_remove(
        ["ardanequity.com", "celeritypartners.com", "enterprise.fund"],
        "pe_partners",
    )
    assert removed["removed"] == 3
    blocked = store.exclude_domains("pe_partners")
    assert "ardanequity.com" not in blocked
    assert "celeritypartners.com" not in blocked
    assert "enterprise.fund" not in blocked
    assert "good.com" in blocked
    store.exclude_add(["celeritypartners.com"], "pe_partners")
    assert "celeritypartners.com" in store.exclude_domains("pe_partners")


def test_exclude_import_json_and_csv(tmp_path):
    store = Store(_settings(tmp_path))
    json_path = tmp_path / "prior.json"
    json_path.write_text(json.dumps({"domains": ["old.com", "https://www.old.com"]}), encoding="utf-8")
    imported = store.exclude_import(str(json_path), "pe_partners")
    assert imported["added"] == 1
    csv_path = tmp_path / "more.csv"
    csv_path.write_text("company_domain\nnewpe.com\n", encoding="utf-8")
    imported2 = store.exclude_import(str(csv_path), "pe")
    assert imported2["total"] == 2
