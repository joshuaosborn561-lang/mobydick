from mobydick.config import Settings
from mobydick.pipeline import build_enriched_list
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


def test_pipeline_dedupes_excludes_and_writes_csv(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings)
    store.exclude_add(["already.com"], "series_ab")

    raw = [
        {
            "full_name": "Ada Founder",
            "first_name": "Ada",
            "last_name": "Founder",
            "title": "CEO & Founder",
            "email": "ada@fresh.com",
            "company_name": "Fresh",
            "company_domain": "fresh.com",
            "funding_round": "series a",
            "funding_date": "2024-08-01",
            "linkedin_url": "https://linkedin.com/in/ada",
        },
        {
            "full_name": "Old One",
            "title": "CEO",
            "email": "old@already.com",
            "company_name": "Already",
            "company_domain": "already.com",
            "funding_round": "series b",
            "funding_date": "2024-02-01",
        },
        {
            "full_name": "Dup Fresh",
            "title": "Founder",
            "email": "dup@fresh.com",
            "company_name": "Fresh",
            "company_domain": "www.fresh.com",
        },
        {
            "full_name": "Intern Person",
            "title": "Intern",
            "email": "intern@nope.com",
            "company_name": "Nope",
            "company_domain": "nope.com",
        },
    ]

    result = build_enriched_list(
        "series_ab",
        10,
        store=store,
        raw_rows=raw,
        fetch_pages=False,
        enrich=True,
    )
    assert result["delivered"] == 1
    assert result["dropped_prior_domains"] == 1
    assert result["disqualified"] == 1
    assert result["samples"][0]["full_name"] == "Ada Founder"
    assert "email" not in result["samples"][0]
    assert result["csv_path"].endswith(".csv")
    assert "fresh.com" in store.exclude_domains("series_ab")


def test_samples_never_include_email_or_hooks(tmp_path):
    store = Store(_settings(tmp_path))
    result = build_enriched_list(
        "pe_partners",
        1,
        store=store,
        fetch_pages=False,
        raw_rows=[
            {
                "full_name": "Pat Partner",
                "first_name": "Pat",
                "last_name": "Partner",
                "title": "Managing Partner",
                "email": "secret@firm.pe",
                "company_name": "Firm",
                "company_domain": "firm.pe",
                "company_description": "lower-middle-market private equity firm",
                "company_industry": "Venture Capital and Private Equity Principals",
                "contact_country": "United States",
                "company_hq_country": "United States",
                "location": "Austin, Texas",
            }
        ],
    )
    sample = result["samples"][0]
    assert "email" not in sample
    assert "best_emotional_hook" not in sample
    assert "quotes" not in sample
    assert sample["full_name"] == "Pat Partner"
    assert sample["firm_type"] == "private equity"


def test_pe_pipeline_drops_wrong_country_title_and_firm(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(_settings(tmp_path))
    good = {
        "full_name": "Pat Partner",
        "first_name": "Pat",
        "last_name": "Partner",
        "title": "Managing Partner",
        "email": "secret@northline.com",
        "company_name": "Northline",
        "company_domain": "northline.com",
        "company_description": "lower-middle-market private equity firm",
        "contact_country": "United States",
        "company_hq_country": "United States",
        "location": "Austin, Texas",
    }
    result = build_enriched_list(
        "pe_partners",
        10,
        store=store,
        fetch_pages=False,
        raw_rows=[
            good,
                {
                    **good,
                    "full_name": "Tetsuji Okamoto",
                    "email": "tetsuji@apollo.example",
                    "company_domain": "apollo.example",
                    "contact_country": "Japan",
                    "company_hq_country": "Japan",
                    "location": "Tokyo, Japan",
                },
                {
                    **good,
                    "full_name": "Selim Loukil",
                    "email": "selim@advent.example",
                    "title": "Head of PSG Europe",
                    "company_domain": "advent.example",
                },
                {
                    **good,
                    "full_name": "Matt Sepulveda",
                    "email": "matt@econ.example",
                    "title": "Principal Economist",
                    "company_domain": "econ.example",
                },
                {
                    **good,
                    "full_name": "Banker One",
                    "email": "banker@imperial.example",
                    "company_name": "Imperial Capital",
                    "company_domain": "imperial.example",
                    "company_description": "middle-market investment bank",
                    "company_industry": "Capital Markets",
                },
                {
                    **good,
                    "full_name": "Advisor One",
                    "email": "advisor@kroll.example",
                    "company_name": "Kroll",
                    "company_domain": "kroll.example",
                    "company_description": "global risk advisory and corporate investigations",
                },
        ],
    )
    assert result["delivered"] == 1
    assert result["samples"][0]["full_name"] == "Pat Partner"
    assert "email" not in result["samples"][0]
    assert result["dq_reasons"]["not_us_person"] == 1
    assert result["dq_reasons"]["non_us_role"] == 1
    assert result["dq_reasons"]["non_deal_role"] == 1
    assert result["dq_reasons"]["not_pe_firm"] == 2
    assert result["life_extraction"] == "heuristic"
    assert "ANTHROPIC_API_KEY" in result["enrichment_warning"]
    assert "OPENAI_API_KEY" in result["enrichment_warning"]
