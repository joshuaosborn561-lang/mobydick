from mobydick.enrich import apply_enrichment
from mobydick.research.life import extract_life_story, is_junk, passage_for_identity

CAMBRIA = """
About Us Our Approach Investment Criteria Team Contact Us
John Collins Vice President Prior to joining The Cambria Group, John was a member of the United States Army, spending the majority of his career within Special Operations.
John holds an undergraduate degree from Boston University, where he competed on the Rugby and Ski Teams, as well as a master's degree from Stanford University.
René Lajous Principal René grew up in El Paso and played soccer at Rice University.
"""

NAME_LIST = (
    "Chris Anderson Andrea Soros Faustina Fynn-Nyame Children's Investment Fund Foundation (CIFF) "
    "Mohamed Gouled IFC Georgia Levenson Keohane Soros Economic Development Fund Satu Santala "
    "Nordic Development Fund Woochong Um The Global Energy Alliance for People and Planet Jiwoo Choi"
)


def test_team_page_does_not_give_a_coworker_bio_to_the_row():
    life = extract_life_story(
        "René Lajous",
        [{"url": "https://cambriagroup.com/team", "title": "Team", "kind": "bio", "text": CAMBRIA}],
    )
    blob = " ".join(
        life[key]
        for key in ("college", "military_service", "real_story", "hook", "beliefs_or_causes", "causes")
        if life.get(key)
    )
    assert "John" not in blob
    assert "Army" not in blob
    assert "Boston University" not in blob
    assert "Special Operations" not in blob
    assert "El Paso" in life["hometown"]
    assert "Rice" in life["college"]
    assert life["confidence"] != "high" or "El Paso" in life["hometown"]
    assert "Army" not in life["real_story"]
    assert "About Us" not in life["real_story"]


def test_name_lists_and_nav_are_not_a_life_story():
    assert is_junk(NAME_LIST)
    assert is_junk("About Us Our Approach Investment Criteria Contact Us Search Funds Team")
    life = extract_life_story(
        "Chris Anderson",
        [
            {
                "url": "https://www.linkedin.com/in/chris-anderson-3b2a05bb",
                "title": "LinkedIn post",
                "kind": "interview",
                "text": NAME_LIST,
            }
        ],
    )
    assert life["causes"] == ""
    assert life["real_story"] == ""
    assert life["hook"] == ""
    assert life["confidence"] == "low"
    assert life["sources"] == ""


def test_llm_keeps_a_verbatim_quote_and_drops_an_invention(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_llm(prompt, **kwargs):
        return {
            "hometown": "René grew up in El Paso",
            "military_service": "René served in the Army Special Operations.",
            "college": "He studied at Harvard.",
        }

    monkeypatch.setattr("mobydick.research.life.llm_extract", fake_llm)
    life = extract_life_story(
        "René Lajous",
        [{"url": "https://cambriagroup.com/team", "title": "Team", "kind": "bio", "text": CAMBRIA}],
    )
    assert "El Paso" in life["hometown"]
    assert life["military_service"] == ""
    assert "Harvard" not in life["college"]
    assert "Rice" in life["college"]
    assert "cambriagroup.com/team" in life["sources"]


def test_broker_page_and_unresolved_initial_do_not_ship(monkeypatch):
    monkeypatch.setattr(
        "mobydick.enrich.gather_company_pages",
        lambda *args, **kwargs: {"website": "", "pages": [], "mailing_address": ""},
    )
    monkeypatch.setattr(
        "mobydick.enrich.gather_person_sources",
        lambda row: [
            {
                "url": "https://allelecapital.com/team",
                "title": "Team",
                "kind": "bio",
                "text": (
                    "Andrew Eriksen Managing Director Andrew holds FINRA Series 7 and 63 licenses "
                    "at Wilmington Capital Securities."
                ),
            }
        ],
    )
    row = apply_enrichment(
        {
            "full_name": "Andrew Eriksen",
            "first_name": "Andrew",
            "last_name": "Eriksen",
            "title": "Managing Director",
            "email": "andrew@allelecapital.com",
            "company_name": "Allele Capital",
            "company_domain": "allelecapital.com",
            "company_website": "https://allelecapital.com",
            "company_description": "private equity firm",
            "contact_country": "United States",
            "company_hq_country": "United States",
            "location": "Fort Lauderdale, Florida",
        },
        "pe_partners",
        fetch_pages=True,
    )
    assert row["dq"] == "not_pe_firm"
    assert row["firm_type"] == "broker-dealer"
    assert row["why_got_into_pe"] == ""
    assert row["real_story"] == ""

    initial = apply_enrichment(
        {
            "full_name": "Scott J.",
            "first_name": "Scott",
            "last_name": "J.",
            "title": "Partner",
            "email": "scott@winfieldequity.com",
            "company_name": "Winfield Equity",
            "company_domain": "winfieldequity.com",
            "company_description": "private equity firm",
            "linkedin_url": "https://www.linkedin.com/in/scottpjensen",
            "contact_country": "United States",
            "company_hq_country": "United States",
            "location": "Bellevue, Washington",
        },
        "pe_partners",
        fetch_pages=False,
    )
    assert initial["dq"] == "truncated_name"
    assert initial["real_story"] == ""


def test_truncated_name_can_be_resolved_from_the_persons_own_bio(monkeypatch):
    monkeypatch.setattr(
        "mobydick.enrich.gather_company_pages",
        lambda *args, **kwargs: {"website": "", "pages": [], "mailing_address": ""},
    )
    monkeypatch.setattr(
        "mobydick.enrich.gather_person_sources",
        lambda row: [
            {
                "url": "https://winfieldequity.com/team",
                "title": "Team",
                "kind": "bio",
                "text": "Scott Jensen Partner Scott grew up in Bellevue and played baseball at Washington.",
            }
        ],
    )
    row = apply_enrichment(
        {
            "full_name": "Scott J.",
            "first_name": "Scott",
            "last_name": "J.",
            "title": "Partner",
            "email": "scott@winfieldequity.com",
            "company_name": "Winfield Equity",
            "company_domain": "winfieldequity.com",
            "company_description": "private equity firm",
            "linkedin_url": "https://www.linkedin.com/in/scottpjensen",
            "contact_country": "United States",
            "company_hq_country": "United States",
            "location": "Bellevue, Washington",
        },
        "pe_partners",
        fetch_pages=True,
    )
    assert row["dq"] == ""
    assert row["last_name"] == "Jensen"
    assert row["full_name"] == "Scott Jensen"
    assert "Bellevue" in row["hometown_or_from"]


TEAM_WITH_COMMAS = """
About Us Our Approach Team Contact Us
John Collins, Vice President Prior to joining, John was a member of the United States Army Special Operations.
Scott Jensen, Partner Scott grew up in Bellevue and played baseball at Washington.
Scott Smith, Principal Scott Smith grew up in Ohio.
"""


def test_an_initial_last_name_keeps_only_the_matching_bio():
    passage = passage_for_identity(TEAM_WITH_COMMAS, "Scott", "J.")
    assert passage == ""
    only = passage_for_identity(
        "John Collins, Vice President John served in the Army.\n"
        "Scott Jensen, Partner Scott grew up in Bellevue and played baseball at Washington.",
        "Scott",
        "J.",
    )
    assert "Jensen" in only
    assert "Bellevue" in only
    assert "Army" not in only
    assert "John" not in only


def test_joining_a_firm_is_not_a_life_story():
    life = extract_life_story(
        "Andrew Eriksen",
        [
            {
                "url": "https://allelecapital.com/team",
                "title": "Team",
                "kind": "bio",
                "text": (
                    "Andrew Eriksen, Managing Director Andrew joined Allele Capital, "
                    "a private equity firm, in 2023."
                ),
            }
        ],
    )
    assert life["why"] == ""
    assert life["real_story"] == ""
