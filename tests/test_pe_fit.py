from mobydick.enrich import apply_enrichment
from mobydick.pe_fit import (
    assess_pe,
    classify_firm,
    firm_self_venture_phrase,
    firm_text_is_venture,
    page_disqualifies_firm,
    person_is_us,
    title_reason,
)


def _pe(**overrides):
    row = {
        "full_name": "Pat Partner",
        "first_name": "Pat",
        "last_name": "Partner",
        "title": "Managing Partner",
        "company_name": "Northline Capital",
        "company_domain": "northline.com",
        "company_description": "lower-middle-market private equity firm",
        "company_industry": "Venture Capital and Private Equity Principals",
        "contact_country": "United States",
        "company_hq_country": "United States",
        "location": "Austin, Texas",
    }
    row.update(overrides)
    return row


def test_titles_match_words_not_substrings():
    assert title_reason("Managing Partner") == ""
    assert title_reason("Operating Partner") == ""
    assert title_reason("Managing Director") == ""
    assert title_reason("Principal") == ""
    assert title_reason("Founder") == ""
    assert title_reason("Co-Founder") == ""
    assert title_reason("Principal Economist") == "non_deal_role"
    assert title_reason("Partnerships Manager") == "not_partner_grade"
    assert title_reason("Head of Investor Relations") == "non_deal_role"
    assert title_reason("Head of Portfolio Technology") == "non_deal_role"
    assert title_reason("Managing Director, Private Credit") == "non_deal_role"
    assert title_reason("Head of PSG Europe") == "non_us_role"
    assert title_reason("Partner, Head of Europe") == "non_us_role"
    assert title_reason("Associate") == "junior_title"
    assert title_reason("Venture Partner") == "non_deal_role"
    assert title_reason("Managing Director – Finance / Data & Analytics") == "non_deal_role"
    assert title_reason("Managing Director, Operations") == "non_deal_role"
    assert title_reason("Partner, Talent") == "non_deal_role"
    assert title_reason("Operating Partner") == ""
    assert title_reason("Independent Sponsor") == "not_partner_grade"


def test_us_person_and_us_hq_only():
    assert person_is_us("United States", "Indianapolis, IN")
    assert person_is_us("", "Austin, TX")
    assert person_is_us("", "Paris, TX")
    assert not person_is_us("", "Tokyo")
    assert not person_is_us("Japan", "Tokyo, Japan")
    assert not person_is_us("United States", "Tokyo, Japan")
    assert not person_is_us("", "")
    japan = assess_pe(
        _pe(
            full_name="Tetsuji Okamoto",
            title="Partner",
            contact_country="Japan",
            location="Tokyo, Japan",
            company_hq_country="Japan",
        )
    )
    assert japan["dq"] == "not_us_person"
    europe = assess_pe(_pe(full_name="Selim Loukil", title="Head of PSG Europe"))
    assert europe["dq"] == "non_us_role"
    missing_hq = assess_pe(_pe(company_hq_country=""))
    assert missing_hq["dq"] == "not_us_hq"


def test_firm_type_is_honest():
    assert classify_firm("Northline", "lower-middle-market private equity firm", "") == "private equity"
    assert classify_firm("Growth Co", "growth equity firm focused on buyouts", "") == "buyout"
    assert classify_firm("Imperial Capital", "middle-market investment bank", "Capital Markets") == "investment bank"
    assert classify_firm("PMCF", "an investment banking firm", "") == "investment bank"
    assert classify_firm("Kroll", "global risk advisory and corporate investigations", "") == "risk advisory"
    assert classify_firm("Advisor", "advises private equity clients", "") == "unknown"
    assert classify_firm("Advisor", "advises private equity clients", "Capital Markets") == "investment bank"
    assert classify_firm("Mystery", "", "Venture Capital and Private Equity Principals") == "unknown"
    imperial = assess_pe(
        _pe(
            company_name="Imperial Capital",
            company_description="middle-market investment bank",
            company_industry="Capital Markets",
        )
    )
    assert imperial["firm_type"] == "investment bank"
    assert imperial["dq"] == "not_pe_firm"
    kroll = assess_pe(
        _pe(company_name="Kroll", company_description="global risk advisory and corporate investigations")
    )
    assert kroll["firm_type"] == "risk advisory"
    assert kroll["dq"] == "not_pe_firm"


def test_enrichment_does_not_invent_private_equity_or_a_life_story(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    row = apply_enrichment(_pe(company_description="", company_industry=""), "pe_partners", fetch_pages=False)
    assert row["firm_type"] == "unknown"
    assert row["dq"] == "not_pe_firm"
    assert row["confidence"] == "low"
    assert row["hometown_or_from"] == ""
    assert row["real_story"] == ""
    kept = apply_enrichment(_pe(), "pe_partners", fetch_pages=False)
    assert kept["dq"] == ""
    assert kept["firm_type"] == "private equity"
    assert kept["confidence"] == "low"
    assert "Empty means not found" in kept["research_note"]
    assert "ANTHROPIC_API_KEY" in kept["research_note"]


def test_email_domain_must_match_the_firm_and_cfo_is_out():
    mismatch = assess_pe(
        _pe(
            full_name="James S.",
            first_name="James",
            last_name="S.",
            email="james@salesforce.com",
            company_domain="salesforce.com",
            company_website="https://allyengage.com",
            linkedin_url="https://www.linkedin.com/in/james84711",
        )
    )
    assert mismatch["dq"] == "email_domain_mismatch"
    ted = assess_pe(
        _pe(
            full_name="Chris Anderson",
            email="chris@ted.com",
            company_domain="allaboard.vc",
            company_website="https://allaboard.vc",
            company_description="growth equity fund",
        )
    )
    assert ted["dq"] in {"email_domain_mismatch", "not_pe_firm"}
    assert classify_firm("All Aboard Fund", "growth equity firm", "", "allaboard.vc") == "venture capital"
    assert classify_firm("2.0 Ventures", "focused on buyouts", "") == "venture capital"
    assert title_reason("Chief Financial Officer/Operating Partner") == "non_deal_role"
    assert classify_firm("Allele Capital", "private equity firm and FINRA Series 7 broker-dealer", "") == "broker-dealer"
    assert classify_firm("Ampersand Holdings", "a diversified holdings company", "") == "unknown"
    assert classify_firm("Drawdown Fund", "SEC Form D lists the offering as venture", "") == "venture capital"
    assert page_disqualifies_firm("Form D filing: venture fund") == "venture capital"
    assert page_disqualifies_firm("She left venture capital to join the private equity firm.") == ""
    assert classify_firm("K20 Fund", "an early-stage venture capital firm", "") == "venture capital"
    assert classify_firm("Seed Co", "a pre-seed fund", "") == "venture capital"
    assert firm_text_is_venture("K20 is an early-stage venture capital firm focused on software")
    assert firm_text_is_venture("She left venture capital to join the private equity firm.") is False
    assert "venture capital" in firm_self_venture_phrase(
        "K20 Fund",
        "K20 is an early-stage venture capital firm focused on software.",
    ).lower()
    assert firm_self_venture_phrase(
        "Northline Capital",
        "Northline Capital is a private equity firm. A portfolio company raised a seed fund.",
    ) == ""
    assert firm_self_venture_phrase(
        "Northline Capital",
        "She left venture capital to join the private equity firm.",
    ) == ""
    assert firm_self_venture_phrase(
        "Polaris Growth Fund",
        "Some other company is an early-stage venture capital firm.",
    ) == ""
    assert "early-stage venture" in firm_self_venture_phrase(
        "Polaris Growth Fund",
        "We are an early-stage venture capital firm.",
    ).lower()
    fixed = assess_pe(
        _pe(
            full_name="Kerry Wei",
            email="kerry@prysmcapital.com",
            company_domain="alembic.com",
            company_website="https://prysmcapital.com",
            company_description="growth equity firm",
        )
    )
    assert fixed["dq"] == ""
    assert fixed["company_domain"] == "prysmcapital.com"


def test_homepage_venture_claim_drops_and_a_portfolio_page_does_not(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    researched: list[str] = []

    monkeypatch.setattr(
        "mobydick.enrich.gather_person_sources",
        lambda row: researched.append(row["full_name"]) or [],
    )

    def pe_pages(website: str, domain: str) -> dict[str, object]:
        return {
            "website": website,
            "mailing_address": "",
            "pages": [
                {"url": f"https://{domain}/", "text": "Northline Capital is a private equity firm in Austin."},
                {"url": f"https://{domain}/portfolio", "text": "A portfolio company raised a seed fund."},
            ],
        }

    monkeypatch.setattr("mobydick.enrich.gather_company_pages", pe_pages)
    kept = apply_enrichment(_pe(), "pe_partners", fetch_pages=True)
    assert kept["dq"] == ""
    assert kept["firm_type"] == "private equity"
    assert researched == ["Pat Partner"]

    def venture_pages(website: str, domain: str) -> dict[str, object]:
        return {
            "website": website,
            "mailing_address": "",
            "pages": [
                {"url": f"https://{domain}/about", "text": "We are an early-stage venture capital firm."},
            ],
        }

    monkeypatch.setattr("mobydick.enrich.gather_company_pages", venture_pages)
    dropped = apply_enrichment(_pe(company_name="K20 Fund", company_domain="k20.com"), "pe_partners", fetch_pages=True)
    assert dropped["dq"] == "not_pe_firm"
    assert dropped["firm_type"] == "venture capital"
    assert researched == ["Pat Partner"]


def test_truncated_last_name_resolves_only_from_a_real_slug():
    resolved = assess_pe(
        _pe(
            full_name="Scott J.",
            first_name="Scott",
            last_name="J.",
            linkedin_url="https://www.linkedin.com/in/scott-jensen",
        )
    )
    assert resolved["last_name"] == "Jensen"
    assert resolved["full_name"] == "Scott Jensen"
    assert resolved["unresolved_name"] == ""
    stuck = assess_pe(
        _pe(
            full_name="Mike T.",
            first_name="Mike",
            last_name="T.",
            linkedin_url="https://www.linkedin.com/in/mthompson123",
        )
    )
    assert stuck["unresolved_name"] == "yes"
    assert stuck["dq"] == ""
