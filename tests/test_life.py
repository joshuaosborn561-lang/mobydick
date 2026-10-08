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


def test_people_search_sites_and_age_only_facts_are_rejected(monkeypatch):
    from mobydick.research.blocklist import is_people_search
    from mobydick.research.life import gather_person_sources, public_footprint

    blocked = [
        "https://www.truepeoplesearch.com/find/robert-trainer",
        "https://secure.information.com/robert-trainer",
        "https://www.information.com/robert-trainer",
        "https://www.idcrawl.com/robert-trainer",
        "https://www.whitepages.com/name/Robert-Trainer",
        "https://www.spokeo.com/Robert-Trainer",
        "https://www.beenverified.com/people/robert-trainer",
        "https://radaris.com/p/Robert/Trainer",
        "https://www.fastpeoplesearch.com/logan-burnett",
        "https://www.peoplefinders.com/people/tre-mischka",
        "https://www.mylife.com/ryan-shelton",
        "https://www.intelius.com/people/robert-trainer",
    ]
    assert all(is_people_search(url) for url in blocked)
    assert is_people_search("https://www.voyagerinterests.com/team/robert-trainer") is False

    broker = extract_life_story(
        "Robert B. Trainer",
        [
            {
                "url": "https://www.truepeoplesearch.com/find/robert-trainer",
                "title": "Robert Trainer",
                "kind": "bio",
                "text": "Robert Trainer was born in 1930, age 95.",
            }
        ],
    )
    assert broker["hometown"] == ""
    assert broker["life_events"] == ""
    assert broker["hook"] == ""
    assert broker["real_story"] == ""

    roster = extract_life_story(
        "Logan Burnett",
        [
            {
                "url": "https://www.fastpeoplesearch.com/logan-burnett",
                "title": "Logan Burnett",
                "kind": "bio",
                "text": "Logan Burnett, 2025 VMI football roster. Wide receiver.",
            }
        ],
    )
    assert roster["life_events"] == ""
    assert "VMI" not in roster["hook"]
    assert roster["real_story"] == ""

    trainer = extract_life_story(
        "Robert Trainer",
        [
            {
                "url": "https://voyagerinterests.com/team/robert-trainer",
                "title": "Robert Trainer",
                "kind": "bio",
                "text": "Robert Trainer Partner. Robert Trainer was born in 1930, age 95.",
            }
        ],
    )
    assert trainer["hometown"] == ""
    assert "1930" not in trainer["life_events"]
    assert "1930" not in trainer["hook"]
    assert "1930" not in trainer["real_story"]

    shelton_age = extract_life_story(
        "Ryan Shelton",
        [
            {
                "url": "https://rockhillcap.com/team/ryan-shelton",
                "title": "Ryan Shelton",
                "kind": "bio",
                "text": "Ryan Shelton Managing Director. Ryan Shelton is age 21 in State College, PA.",
            }
        ],
    )
    assert shelton_age["hometown"] == ""
    assert "State College" not in shelton_age["hook"]
    assert "State College" not in shelton_age["real_story"]

    mischka = extract_life_story(
        "Tre Mischka",
        [
            {
                "url": "https://supplychainequity.com/team/tre-mischka",
                "title": "Tre Mischka",
                "kind": "bio",
                "text": "Tre Mischka Principal. Tre Mischka is 65 years old.",
            }
        ],
    )
    assert mischka["life_events"] == ""
    assert mischka["hometown"] == ""
    assert "65" not in mischka["hook"]
    assert "65" not in mischka["real_story"]

    still_hometown = extract_life_story(
        "Jane Okonkwo",
        [
            {
                "url": "https://example.com/jane",
                "title": "Jane Okonkwo",
                "kind": "bio",
                "text": "Jane Okonkwo grew up in Dayton and is 40 years old.",
            }
        ],
    )
    assert "Dayton" in still_hometown["hometown"]
    assert "Dayton" in still_hometown["hook"]

    monkeypatch.setattr("mobydick.research.life.talks_with_transcripts", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.search_episodes", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.linkedin_posts", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.search_videos", lambda *args, **kwargs: [])

    def fake_fetch(url: str, **kwargs: object) -> tuple[str, str]:
        fake_fetch.last_status = 404
        return "", ""

    def fake_search(query: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "url": "https://www.truepeoplesearch.com/find/robert-trainer",
                "title": "Robert Trainer",
                "description": "Robert Trainer was born in 1930, age 95.",
            }
        ]

    monkeypatch.setattr("mobydick.research.life.fetch_document", fake_fetch)
    monkeypatch.setattr("mobydick.research.life.google_search", fake_search)
    row = {
        "full_name": "Robert Trainer",
        "first_name": "Robert",
        "last_name": "Trainer",
        "company_name": "Voyager Interests",
        "company_domain": "voyagerinterests.com",
        "company_website": "https://voyagerinterests.com",
    }
    sources = gather_person_sources(row)
    assert all("truepeoplesearch" not in source["url"] for source in sources)
    assert all("1930" not in (source.get("text") or "") for source in sources)
    footprint = public_footprint(row)
    assert footprint["hits"] == []
    assert footprint["score"] == 0


def test_a_quote_someone_else_said_is_not_theirs(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    heard = extract_life_story(
        "Shameek Konar",
        [
            {
                "url": "https://arapartners.com/team/shameek-konar",
                "title": "Shameek Konar",
                "kind": "interview",
                "text": (
                    "Shameek Konar is a partner at Ara Partners. "
                    "Shameek Konar grew up in Houston, Texas. "
                    'Jimmy Haslam told Shameek Konar "I built our family business, Pilot, from one gas station."'
                ),
            }
        ],
        firm="Ara Partners",
        domain="arapartners.com",
        website="https://arapartners.com",
    )
    assert "Houston" in heard["hometown"]
    assert "gas station" not in heard["quotes"]
    assert "Pilot" not in heard["family_background"]
    assert "Pilot" not in heard["real_story"]

    own = extract_life_story(
        "Shameek Konar",
        [
            {
                "url": "https://arapartners.com/team/shameek-konar",
                "title": "Shameek Konar",
                "kind": "interview",
                "text": 'Shameek Konar said "I built our family business, Pilot, from one gas station."',
            }
        ],
        firm="Ara Partners",
        domain="arapartners.com",
        website="https://arapartners.com",
    )
    assert "gas station" in own["quotes"]
    assert "Pilot" in own["family_background"]


def test_another_persons_blurb_and_a_charity_board_are_not_the_story():
    guhan = extract_life_story(
        "Guhan Swaminathan",
        [
            {
                "url": "https://virgocapital.com/team/guhan-swaminathan",
                "title": "Guhan Swaminathan",
                "kind": "interview",
                "text": (
                    "Guhan Swaminathan Managing Director. "
                    "Guhan Swaminathan grew up in Austin, Texas. "
                    'A reviewer wrote "I admire Anand\'s approach to building companies."'
                ),
            }
        ],
        firm="Virgo Capital",
    )
    assert "Austin" in guhan["hometown"]
    assert "Anand" not in guhan["quotes"]
    assert "Anand" not in guhan["hook"]
    assert "Anand" not in guhan["real_story"]
    assert "Austin" in guhan["hook"]

    shelton = extract_life_story(
        "Ryan Shelton",
        [
            {
                "url": "https://rockhillcap.com/team/ryan-shelton",
                "title": "Ryan Shelton",
                "kind": "bio",
                "text": (
                    "Ryan Shelton Managing Director. "
                    "Ryan Shelton grew up in Houston, Texas. "
                    "Ryan Shelton has served as a Director of several charitable organizations "
                    "and is a board member of many of Rock Hill's portfolio companies."
                ),
            }
        ],
        firm="Rock Hill Capital",
    )
    assert "Houston" in shelton["hometown"]
    assert shelton["causes"] == ""
    assert "charitable" not in shelton["hook"].lower()
    assert "portfolio" not in shelton["hook"].lower()
    assert "charitable" not in shelton["real_story"].lower()
    assert "portfolio" not in shelton["real_story"].lower()
    assert "Houston" in shelton["hook"]


def test_third_party_name_matches_need_firm_title_or_city():
    """Job 053ce268404a: Voyage Austin and a Newmarket obituary were different people."""
    dj = extract_life_story(
        "Jason Frank",
        [
            {
                "url": "https://voyageaustin.com/interview/jason-frank-of-all-over-on-life-lessons-legacy-highlight/",
                "title": "Jason Frank of All Over",
                "kind": "interview",
                "text": "I'm partnered up with my wife who also Djs house and techno.",
            }
        ],
        firm="Ardan Equity",
        domain="ardanequity.com",
        website="https://ardanequity.com",
        title="Partner",
        location="Chicago, Illinois",
    )
    assert dj["family_background"] == ""
    assert dj["real_story"] == ""
    assert dj["hook"] == ""

    obituary = extract_life_story(
        "Mark Benham",
        [
            {
                "url": "https://www.legacy.com/us/obituaries/name/mark-benham-obituary?id=62061987",
                "title": "Mark Benham Obituary",
                "kind": "bio",
                "text": (
                    "Mark Arthur Benham of Newmarket, NH. "
                    "Born October 1, 1949 in Pittsfield, MA, he was the son of Paul and Ann (Hollenbeck) Benham."
                ),
            }
        ],
        firm="Celerity Partners",
        domain="celeritypartners.com",
        website="https://celeritypartners.com",
        title="Partner",
        location="Redwood City, California",
    )
    assert "Pittsfield" not in obituary["hometown"]
    assert "Paul" not in obituary["family_background"]
    assert obituary["hook"] == ""
    assert obituary["real_story"] == ""

    local = extract_life_story(
        "Jason Frank",
        [
            {
                "url": "https://www.chicagotribune.com/jason-frank",
                "title": "Jason Frank",
                "kind": "interview",
                "text": "Jason Frank, a partner at Ardan Equity in Chicago, grew up in Naperville.",
            }
        ],
        firm="Ardan Equity",
        domain="ardanequity.com",
        website="https://ardanequity.com",
        title="Partner",
        location="Chicago, Illinois",
    )
    assert "Naperville" in local["hometown"]


def test_field_mapping_keeps_origin_degrees_and_hobbies():
    pangraze = extract_life_story(
        "Alex Pangraze",
        [
            {
                "url": "https://legacypinescapital.com/team/alex-pangraze",
                "title": "Alex Pangraze",
                "kind": "bio",
                "text": (
                    "Alex Pangraze Partner. "
                    "Originally from Greenville, South Carolina, Alex currently lives in Richmond, Virginia "
                    "with his wife, Morghan, and their two children, Jack and Grace. "
                    "Alex's passion for small business goes back to his first job as a sorter on the tomato "
                    "line of a local family-owned produce business, where he observed the value of loyal "
                    "employees and a low ego, high impact, roll-up your sleeves leadership style that he "
                    "strives to embody today."
                ),
            }
        ],
        firm="Legacy Pines",
    )
    assert "Greenville" in pangraze["hometown"]
    assert pangraze["family_background"] == ""
    assert "tomato" in pangraze["why"] or "passion" in pangraze["why"].lower()
    assert "tomato" in pangraze["early_jobs"] or "first job" in pangraze["early_jobs"].lower()
    assert "passion" in pangraze["real_story"].lower() or "tomato" in pangraze["real_story"].lower()

    stepka = extract_life_story(
        "Justen Stepka",
        [
            {
                "url": "https://enterprise.fund/team/justen-stepka",
                "title": "Justen Stepka",
                "kind": "bio",
                "text": (
                    "Justen Stepka Partner. "
                    "He went on to work there for eight years, Docker for another four, and then launch "
                    "a private equity firm, Enterprise Fund, along with another Atlassian veteran."
                ),
            }
        ],
        firm="Enterprise Fund",
    )
    assert stepka["military_service"] == ""

    iglehart = extract_life_story(
        "Joel Iglehart",
        [
            {
                "url": "https://thirdcentury.com/team/joel-iglehart",
                "title": "Joel Iglehart",
                "kind": "bio",
                "text": (
                    "Mr. Iglehart is originally from Memphis, Tennessee, where he attended Memphis University School. "
                    "He received a B.A. from the University of Virginia and an M.B.A. from Harvard Business School."
                ),
            }
        ],
        firm="Third Century",
    )
    assert "Memphis" in iglehart["hometown"]
    assert "Memphis University School" not in iglehart["college"]
    assert "Virginia" in iglehart["college"] or "Harvard" in iglehart["college"]

    hobbies = extract_life_story(
        "Will Tucker",
        [
            {
                "url": "https://seratacapital.com/team/will-tucker",
                "title": "Will Tucker",
                "kind": "bio",
                "text": "Will Tucker Partner. Will enjoys golf, basketball, and mentoring local students.",
            }
        ],
        firm="Serata Capital",
    )
    assert "golf" in hobbies["life_events"].lower() or "mentor" in hobbies["life_events"].lower()
    assert "golf" in hobbies["real_story"].lower() or "mentor" in hobbies["real_story"].lower()


def test_named_boards_and_founder_exits_are_personal():
    diaz = extract_life_story(
        "Jorge Diaz",
        [
            {
                "url": "https://platformllc.com/team/jorge-diaz",
                "title": "Jorge Diaz",
                "kind": "bio",
                "text": (
                    "Jorge Diaz Partner. "
                    "Jorge serves on the board of WorkFaith Connection. "
                    "Jorge founded a payment card business and sold it to Fiserv in 1994. "
                    "In addition, Jorge enjoys spending time with his wife (Anna), staying physically fit and traveling."
                ),
            }
        ],
        firm="Platform",
    )
    assert "WorkFaith" in diaz["causes"]
    assert "Fiserv" in diaz["life_events"]
    assert "WorkFaith" in diaz["real_story"] or "Fiserv" in diaz["real_story"]
    assert "wife" in diaz["family_background"].lower() or "Anna" in diaz["family_background"]
