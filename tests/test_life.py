from mobydick.enrich import apply_enrichment
from mobydick.research.life import extract_life_story


BIO = (
    "Jane Okonkwo grew up in Dayton, Ohio. "
    "Her parents immigrated from Ghana and her father ran a small diner. "
    "She played basketball at Ohio State University. "
    "She served in the U.S. Navy before private equity. "
    "Her first job was washing dishes in that diner. "
    "She sits on the board of a literacy nonprofit and has talked about her church. "
    'In the interview she said "I still write letters by hand."'
)


def test_life_story_cites_concrete_facts_and_stays_empty_without_them():
    sources = [
        {
            "url": "https://example.com/interview",
            "title": "Interview with Jane Okonkwo",
            "kind": "interview",
            "text": BIO,
        }
    ]
    life = extract_life_story("Jane Okonkwo", sources)
    assert "Dayton" in life["hometown"]
    assert "immigrated" in life["family_background"].lower() or "father" in life["family_background"].lower()
    assert "Ohio State" in life["college"] or "basketball" in life["college"].lower()
    assert "Navy" in life["military_service"]
    assert life["early_jobs"]
    assert "church" in life["causes"].lower() or "board" in life["causes"].lower()
    assert "letters by hand" in life["quotes"]
    assert life["real_story"]
    assert life["hook"]
    assert "example.com/interview" in life["sources"]
    assert life["confidence"] == "high"

    empty = extract_life_story("Jane Okonkwo", [])
    assert empty["confidence"] == "low"
    assert empty["hometown"] == ""
    assert empty["hook"] == ""
    assert empty["real_story"] == ""


def test_life_story_ignores_firm_boilerplate_and_home_addresses():
    sources = [
        {
            "url": "https://firm.example/team",
            "title": "Team",
            "kind": "bio",
            "text": (
                "Our team includes Jane Okonkwo, Partner. "
                "We grew up as a firm in Chicago. "
                "Jane Okonkwo lives at 9 Oak Lane, Austin, TX 78701. "
                "She grew up in Dayton, Ohio."
            ),
        }
    ]
    life = extract_life_story("Jane Okonkwo", sources)
    assert "Dayton" in life["hometown"]
    assert "Chicago" not in life["hometown"]
    assert "Oak Lane" not in life["hometown"]
    assert "Oak Lane" not in life["real_story"]
    assert "78701" not in life["real_story"]


def test_apply_enrichment_keeps_cited_life_story(monkeypatch):
    monkeypatch.setattr(
        "mobydick.enrich.gather_company_pages",
        lambda *args, **kwargs: {
            "website": "https://northline.com",
            "pages": [],
            "mailing_address": "100 Congress Avenue, Suite 200, Austin, TX 78701",
        },
    )
    monkeypatch.setattr(
        "mobydick.enrich.gather_person_sources",
        lambda row: [
            {
                "url": "https://example.com/interview",
                "title": "Interview with Pat Partner",
                "kind": "interview",
                "text": BIO.replace("Jane Okonkwo", "Pat Partner"),
            }
        ],
    )
    row = apply_enrichment(
        {
            "full_name": "Pat Partner",
            "first_name": "Pat",
            "last_name": "Partner",
            "title": "Partner",
            "company_name": "Northline Capital",
            "company_domain": "northline.com",
            "company_website": "https://northline.com",
            "company_description": "private equity firm",
            "contact_country": "United States",
            "company_hq_country": "United States",
            "location": "Austin, Texas",
        },
        "pe_partners",
        fetch_pages=True,
    )
    assert row["dq"] == ""
    assert row["confidence"] == "high"
    assert "Dayton" in row["hometown_or_from"]
    assert row["family_background"]
    assert row["college"]
    assert row["military_service"]
    assert row["quotes"]
    assert "example.com/interview" in row["sources"]
    assert row["mailing_address"].startswith("100 Congress")
    assert "Oak Lane" not in row["mailing_address"]
    assert "home address" not in row["research_note"].lower() or "No home address" in row["research_note"]
