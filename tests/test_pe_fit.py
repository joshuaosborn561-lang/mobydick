from mobydick.enrich import apply_enrichment
from mobydick.pe_fit import assess_pe, classify_firm, person_is_us, title_reason


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


def test_enrichment_does_not_invent_private_equity_or_a_life_story():
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
    assert "not found" in kept["research_note"].lower() or "Empty means not found" in kept["research_note"]
