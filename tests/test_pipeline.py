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
    assert result["research"]["llm_calls"] == 0
    assert result["research"]["facts_extracted"] == 0


def _pe_row(name: str, domain: str, **overrides: str) -> dict[str, str]:
    first, last = name.split(" ", 1)
    row = {
        "full_name": name,
        "first_name": first,
        "last_name": last,
        "title": "Managing Partner",
        "email": f"{first.lower()}@{domain}",
        "company_name": "Northline",
        "company_domain": domain,
        "company_website": f"https://{domain}",
        "company_description": "lower-middle-market private equity firm",
        "contact_country": "United States",
        "company_hq_country": "United States",
        "location": "Austin, Texas",
    }
    row.update(overrides)
    return row


def test_pe_keeps_paging_until_the_requested_keepers(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(_settings(tmp_path))
    calls: list[int] = []

    class FakeLeads:
        def search(self, filters: dict, limit: int = 100, offset: int = 0) -> list[dict[str, str]]:
            calls.append(offset)
            if offset == 0:
                page = [
                    _pe_row(
                        "Bad Ventures",
                        "badventures.com",
                        company_name="Bad Ventures",
                        company_description="SEC Form D lists the offering as venture",
                    ),
                    _pe_row("Cfo Person", "cfo.com", title="Chief Financial Officer/Operating Partner"),
                    _pe_row("Ann Keeper", "ann.com"),
                ]
                page.extend(
                    _pe_row(f"Extra {index}", f"extra{index}.com", company_name="Nope Holdings", company_description="a holdings company")
                    for index in range(limit - 3)
                )
                return page
            return [_pe_row("Bea Keeper", "bea.com"), _pe_row("Cam Keeper", "cam.com")]

    monkeypatch.setattr("mobydick.pipeline.pe_scan_cap", lambda wanted, story_first=False: 150)
    result = build_enriched_list(
        "pe_partners",
        3,
        store=store,
        getleads=FakeLeads(),
        fetch_pages=False,
    )
    assert calls[0] == 0
    assert calls[1] > 0
    assert result["delivered"] == 3
    assert result["shortfall"] == 0
    assert result["scanned"] > 3
    assert result["scan_cap"] == 150
    assert result["scan_stop"] == "filled"
    assert result["broadened"] is False
    names = {sample["full_name"] for sample in result["samples"]}
    assert names == {"Ann Keeper", "Bea Keeper", "Cam Keeper"}
    assert "email" not in result["samples"][0]
    assert result["research"]["pages_fetched"] == 0


def test_story_first_skips_resume_only_rows_and_ranks_personal_facts(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(_settings(tmp_path))

    def fake_pages(*args: object, **kwargs: object) -> dict[str, object]:
        return {"website": "", "pages": [], "mailing_address": ""}

    researched: list[str] = []

    def fake_sources(row: dict[str, str], **kwargs: object) -> list[dict[str, str]]:
        researched.append(row["full_name"])
        name = row["full_name"]
        if name == "Bea Keeper":
            text = (
                "Bea Keeper grew up in Dayton, Ohio. "
                "She served in the U.S. Navy. "
                "Her father ran a diner."
            )
        elif name == "Dee Keeper":
            text = 'Dee Keeper said "I still write letters to my mother every week."'
        else:
            text = (
                "Ada Keeper Partner Prior to founding, Ada was the CEO of Liberty Fitness. "
                "Ada received an MBA from Stanford University."
            )
        domain = row.get("company_domain") or "example.com"
        return [{"url": f"https://{domain}/team", "title": name, "kind": "bio", "text": text}]

    def fake_footprint(row: dict[str, str]) -> dict[str, object]:
        score = 9 if row["full_name"] == "Bea Keeper" else 0
        return {"score": score, "hits": []}

    monkeypatch.setattr("mobydick.enrich.gather_company_pages", fake_pages)
    monkeypatch.setattr("mobydick.enrich.gather_person_sources", fake_sources)
    monkeypatch.setattr("mobydick.research.life.public_footprint", fake_footprint)
    monkeypatch.setattr("mobydick.pipeline.pe_scan_cap", lambda wanted, story_first=False: 150)

    class FakeLeads:
        def search(self, filters: dict, limit: int = 100, offset: int = 0) -> list[dict[str, str]]:
            if offset == 0:
                page = [
                    _pe_row("Ada Keeper", "ada.com"),
                    _pe_row("Bea Keeper", "bea.com"),
                ]
                page.extend(
                    _pe_row(
                        f"Extra {index}",
                        f"extra{index}.com",
                        company_name="Nope Holdings",
                        company_description="a holdings company",
                    )
                    for index in range(limit - 2)
                )
                return page
            return [_pe_row("Dee Keeper", "dee.com")]

    result = build_enriched_list(
        "pe_partners",
        2,
        store=store,
        getleads=FakeLeads(),
        fetch_pages=True,
    )
    assert result["delivered"] == 2
    assert result["shortfall"] == 0
    assert result["dq_reasons"].get("no_personal_story", 0) >= 1
    assert "Bea Keeper" in researched
    assert "Ada Keeper" in researched
    assert [sample["full_name"] for sample in result["samples"]] == ["Bea Keeper", "Dee Keeper"]
    assert "ada.com" not in store.exclude_domains("pe_partners")
    assert "bea.com" in store.exclude_domains("pe_partners")
    assert result["research"]["person_drops"].get("no_personal_story", 0) >= 1

    class OnlyResume:
        def search(self, filters: dict, limit: int = 100, offset: int = 0) -> list[dict[str, str]]:
            return [_pe_row("Ada Keeper", "ada2.com")]

    short = build_enriched_list(
        "pe_partners",
        1,
        store=Store(_settings(tmp_path / "short")),
        getleads=OnlyResume(),
        fetch_pages=True,
    )
    assert short["delivered"] == 0
    assert short["shortfall"] == 1
    assert short["scan_stop"] == "source_exhausted"
    assert short["broadened"] is True


def test_scan_broadens_when_the_industry_slice_runs_out(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(_settings(tmp_path))
    calls: list[dict[str, object]] = []

    class FakeLeads:
        def search(self, filters: dict, limit: int = 100, offset: int = 0) -> list[dict[str, str]]:
            calls.append({"industries": "industries" in filters, "offset": offset})
            if filters.get("industries"):
                return [
                    _pe_row(
                        "Nope Holdings",
                        "nope.com",
                        company_name="Nope Holdings",
                        company_description="a holdings company",
                    )
                ]
            if offset == 0:
                return [_pe_row("Ann Keeper", "ann.com")]
            return []

    monkeypatch.setattr("mobydick.pipeline.pe_scan_cap", lambda wanted, story_first=False: 150)
    result = build_enriched_list(
        "pe_partners",
        1,
        store=store,
        getleads=FakeLeads(),
        fetch_pages=False,
    )
    assert result["delivered"] == 1
    assert result["shortfall"] == 0
    assert result["broadened"] is True
    assert result["scan_stop"] == "filled"
    assert result["scanned"] >= 2
    assert calls[0]["industries"] is True
    assert any(call["industries"] is False for call in calls)


def test_paging_failure_keeps_people_already_verified(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from mobydick.mcp_http import McpError

    store = Store(_settings(tmp_path))
    offsets: list[int] = []

    class FakeLeads:
        def search(self, filters: dict, limit: int = 100, offset: int = 0) -> list[dict[str, str]]:
            offsets.append(offset)
            if len(offsets) == 1:
                page = [_pe_row("Ann Keeper", "ann.com")]
                page.extend(
                    _pe_row(
                        f"Extra {index}",
                        f"extra{index}.com",
                        company_name="Nope Holdings",
                        company_description="a holdings company",
                    )
                    for index in range(limit - 1)
                )
                return page
            raise McpError("MCP HTTP 504: cloudfront", status=504, body="504 Gateway Time-out")

    monkeypatch.setattr("mobydick.pipeline.pe_scan_cap", lambda wanted, story_first=False: 150)
    result = build_enriched_list(
        "pe_partners",
        2,
        store=store,
        getleads=FakeLeads(),
        fetch_pages=False,
    )
    assert offsets[0] == 0
    assert offsets[1] == 100
    assert result["delivered"] == 1
    assert result["shortfall"] == 1
    assert result["partial"] is True
    assert result["scan_stop"] == "upstream_error"
    assert "504" in result["error"]
    assert result["csv_path"]
    assert {sample["full_name"] for sample in result["samples"]} == {"Ann Keeper"}


def test_partial_result_marks_the_job_completed_partial(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr("mcp_server.jobs.JOBS_DIR", tmp_path)
    from mcp_server.jobs import get_job, start_job

    job = start_job(
        "build_enriched_list",
        lambda j: {"partial": True, "error": "MCP HTTP 504", "shortfall": 14, "delivered": 11},
    )
    fresh = job
    for _ in range(100):
        fresh = get_job(job.id)
        if fresh.status in {"completed", "completed_partial", "failed"}:
            break
        time.sleep(0.01)
    assert fresh.status == "completed_partial"
    assert fresh.result["shortfall"] == 14
    assert "504" in (fresh.error or "")
