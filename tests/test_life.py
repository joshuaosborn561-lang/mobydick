from mobydick.enrich import apply_enrichment
from mobydick.research.life import _sentences, extract_life_story
from mobydick.research.web import html_to_text


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
    assert "church" in life["causes"].lower() or "nonprofit" in life["causes"].lower()
    assert "letters by hand" in life["quotes"]
    assert "Dayton" in life["real_story"]
    assert "dishes" not in life["real_story"]
    assert "Dayton" in life["hook"]
    assert "dishes" not in life["hook"]
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
    assert row["firm_mailing_address"].startswith("100 Congress")
    assert "Oak Lane" not in row["firm_mailing_address"]
    assert "mailing_address" not in row
    assert "home address" not in row["research_note"].lower() or "No home address" in row["research_note"]


PERL = (
    "Doni Perl Principal "
    "Doni joined Charter Oak Equity in 2017. "
    "He currently serves on the Board of Directors of CGA Holdings and previously served in a similar capacity for ChemRes. "
    "Prior to Charter Oak Equity, Doni spent four years at Quadrangle Group, where he focused on investments "
    "in the communications and media sectors, and two years with Sanabe &amp; Associates, an investment banking boutique. "
    "He has served on the board of directors of Hargray Holdings and TowerVision Group. "
    "Doni received a B.S. from the Stern School of Business at New York University, and an MBA from the Yale School of Management. "
    "He grew up in O&rsquo;Fallon."
)


def test_one_fact_lands_in_one_field_and_entities_are_decoded():
    assert html_to_text("<p>Sanabe &amp; Associates</p>") == "Sanabe & Associates"
    assert "rsquo" not in html_to_text("O&rsquo;Fallon")
    life = extract_life_story(
        "Doni Perl",
        [
            {
                "url": "https://www.charteroak-equity.com/team/doni-perl",
                "title": "Team",
                "kind": "bio",
                "text": PERL,
            },
            {
                "url": "https://www.youtube.com/watch?v=perl",
                "title": "Doni Perl interview",
                "kind": "interview",
                "text": '"Doni Perl serves on the board of CGA Holdings in this overview of Charter Oak Equity."',
            },
        ],
    )
    assert "Quadrangle" in life["early_jobs"]
    assert "Sanabe & Associates" in life["early_jobs"]
    assert "CGA" not in life["early_jobs"]
    assert "Hargray" not in life["early_jobs"]
    assert life["causes"] == ""
    assert life["quotes"] == ""
    assert "CGA" not in life["hook"]
    assert life["hook"]
    assert "O" in life["hometown"] and "Fallon" in life["hometown"]
    assert "amp;" not in life["early_jobs"]
    assert "rsquo" not in life["hometown"]
    assert "Yale" in life["college"] or "New York" in life["college"]
    assert life["confidence"] != "high"


def test_resume_facts_alone_do_not_make_a_high_confidence_story():
    life = extract_life_story(
        "Doni Perl",
        [
            {
                "url": "https://www.charteroak-equity.com/team/doni-perl",
                "title": "Team",
                "kind": "bio",
                "text": PERL.replace(" He grew up in O&rsquo;Fallon.", ""),
            }
        ],
    )
    assert "Quadrangle" in life["early_jobs"]
    assert life["hook"] == ""
    assert life["real_story"] == ""
    assert life["confidence"] == "low"


def test_sentences_keep_abbreviations_and_drop_cutoffs():
    text = (
        "He studied at Washington University in St. Louis. "
        "Prior to joining Invision, Jon was a principal at BancBoston Capital."
    )
    sentences = _sentences(text)
    assert any("St. Louis" in sentence for sentence in sentences)
    assert not any(sentence.endswith("St.") for sentence in sentences)
    assert _sentences("Prior to joining Invision, Jon was a") == []
    assert _sentences("Washington University in St.") == []


def test_athletics_count_even_when_the_sentence_names_a_college():
    life = extract_life_story(
        "Cody Shirk",
        [
            {
                "url": "https://example.com/cody",
                "title": "Team",
                "kind": "bio",
                "text": (
                    "Cody Shirk Partner Cody was a four-year NCAA water polo player "
                    "at the University of California."
                ),
            }
        ],
    )
    assert "water polo" in life["life_events"]
    assert "water polo" in life["real_story"]
    assert "water polo" in life["hook"]


def test_the_current_firm_is_not_an_early_job():
    life = extract_life_story(
        "Jon Hale",
        [
            {
                "url": "https://invision.example/team",
                "title": "Team",
                "kind": "bio",
                "text": (
                    "Jon Hale Managing Director Jon was a Managing Director at Invision Capital. "
                    "Prior to joining Invision, Jon was a principal at BancBoston Capital."
                ),
            }
        ],
        firm="Invision Capital",
    )
    assert "BancBoston" in life["early_jobs"]
    assert "Managing Director at Invision" not in life["early_jobs"]


def test_polaris_bio_keeps_hockey_and_family_when_the_site_says_dan():
    """Job 32511fe76ab9 fetched polarisgrowthfund.com/team_member/dan-lombard and kept nothing."""
    text = (
        "Contact Us Privacy Policy "
        "Dan Lombard Managing Partner "
        "Dan serves as a managing partner at PGF, where he leads investments in B2B software. "
        "Prior to joining the firm in 2015, Dan was a vice president with H.I.G. Growth Partners. "
        "Prior to entering the real world, Dan played 3 seasons of professional hockey in the US and Europe. "
        "He and his wife Chandra have three young children."
    )
    life = extract_life_story(
        "Daniel Lombard",
        [
            {
                "url": "https://www.polarisgrowthfund.com/team_member/dan-lombard/",
                "title": "Dan Lombard",
                "kind": "bio",
                "text": text,
            }
        ],
        firm="Polaris Growth Fund",
    )
    assert "hockey" in life["life_events"].lower()
    assert "wife" in life["family_background"].lower() or "children" in life["family_background"].lower()
    assert "hockey" in life["real_story"].lower() or "children" in life["real_story"].lower()
    assert life["hook"]
