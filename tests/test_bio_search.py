from mobydick.research.life import extract_life_story, gather_person_sources
from mobydick.research.trace import tracing
from mobydick.research.web import candidate_bio_urls

STEVENS = (
    "Jeff Stevens - Managing Director "
    "Prior to founding Anacapa Partners, Jeff was the CEO of Liberty Fitness. "
    "Jeff received his Bachelor of Arts and MBA from Stanford University. "
    "Jeff is a member of the Board of Directors of Constellant. "
    "Ashley Giesler - Operating Partner Ashley graduated from UCLA."
)

HOME = '<a href="/site/global/anacapa/team/index.gsp">Our Team</a><a href="/philosophy">Philosophy</a>'


def _silence_network(monkeypatch) -> None:
    monkeypatch.setattr("mobydick.research.life.google_search", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.talks_with_transcripts", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.search_episodes", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.linkedin_posts", lambda *args, **kwargs: [])


def test_homepage_link_points_at_the_real_team_page():
    urls = candidate_bio_urls(HOME, "https://anacapapartners.com", "Jeff", "Stevens")
    assert urls
    assert urls[0].endswith("/site/global/anacapa/team/index.gsp")
    assert all("philosophy" not in url for url in urls)


def test_team_page_bio_stays_on_the_named_person():
    life = extract_life_story(
        "Jeff Stevens",
        [{"url": "https://anacapapartners.com/site/global/anacapa/team/index.gsp", "title": "Team", "kind": "bio", "text": STEVENS}],
    )
    assert "Stanford" in life["college"]
    assert "UCLA" not in life["college"]
    assert "Ashley" not in life["college"]
    assert "Liberty" in life["early_jobs"]
    assert life["causes"] == ""
    assert "Constellant" not in life["early_jobs"]
    assert life["hook"] == ""
    assert life["real_story"] == ""
    assert "team/index.gsp" in life["sources"]
    assert life["confidence"] == "low"


def test_gather_follows_the_team_link_instead_of_stopping_at_guessed_paths(monkeypatch):
    _silence_network(monkeypatch)
    pages = {
        "https://anacapapartners.com": (HOME, "Our Team Philosophy"),
        "https://anacapapartners.com/site/global/anacapa/team/index.gsp": (STEVENS, STEVENS),
    }

    def fake_fetch(url: str, **kwargs: object) -> tuple[str, str]:
        return pages.get(url.rstrip("/"), ("", ""))

    monkeypatch.setattr("mobydick.research.life.fetch_document", fake_fetch)
    sources = gather_person_sources(
        {
            "full_name": "Jeff Stevens",
            "first_name": "Jeff",
            "last_name": "Stevens",
            "company_name": "Anacapa Partners",
            "company_domain": "anacapapartners.com",
            "company_website": "https://anacapapartners.com",
        }
    )
    urls = [source["url"] for source in sources]
    assert any(url.endswith("/team/index.gsp") for url in urls)
    assert not any(url.rstrip("/").endswith("/team") for url in urls)
    life = extract_life_story("Jeff Stevens", sources)
    assert "Stanford" in life["college"]
    assert "UCLA" not in life["college"]


def test_web_search_is_used_when_the_site_has_no_team_link(monkeypatch):
    monkeypatch.setattr("mobydick.research.life.talks_with_transcripts", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.search_episodes", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.linkedin_posts", lambda *args, **kwargs: [])
    bio_url = "https://anacapapartners.com/site/global/anacapa/team/index.gsp"
    queries: list[str] = []

    def fake_fetch(url: str, **kwargs: object) -> tuple[str, str]:
        if url.rstrip("/") == bio_url:
            return (STEVENS, STEVENS)
        return ("<html>Home</html>", "Home")

    def fake_search(query: str, **kwargs: object) -> list[dict[str, str]]:
        queries.append(query)
        if query.startswith("site:"):
            return [{"url": bio_url, "title": "Team", "description": ""}]
        return []

    monkeypatch.setattr("mobydick.research.life.fetch_document", fake_fetch)
    monkeypatch.setattr("mobydick.research.life.google_search", fake_search)
    sources = gather_person_sources(
        {
            "full_name": "Jeff Stevens",
            "first_name": "Jeff",
            "last_name": "Stevens",
            "company_name": "Anacapa Partners",
            "company_domain": "anacapapartners.com",
            "company_website": "https://anacapapartners.com",
        }
    )
    assert any(query.startswith("site:") for query in queries)
    assert any("podcast" in query for query in queries)
    assert any("grew up" in query or "hometown" in query for query in queries)
    assert any(source["url"] == bio_url for source in sources)
    life = extract_life_story("Jeff Stevens", sources)
    assert "Stanford" in life["college"]
    assert "Liberty" in life["early_jobs"]


def test_ungrounded_model_output_is_rejected_and_counted(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "mobydick.research.life.llm_extract",
        lambda *args, **kwargs: {"hometown": "Jeff grew up on the moon", "college": "He went to Yale."},
    )
    with tracing() as trace:
        life = extract_life_story(
            "Jeff Stevens",
            [{"url": "https://anacapapartners.com/team", "title": "Team", "kind": "bio", "text": STEVENS}],
        )
    summary = trace.as_dict()
    assert summary["llm_calls"] == 1
    assert summary["reject_reasons"].get("not_grounded", 0) >= 1
    assert summary["facts_extracted"] >= 2
    assert life["hometown"] == ""
    assert "Yale" not in life["college"]
    assert "Stanford" in life["college"]
    assert "moon" not in life["real_story"]


def test_middle_initial_bio_link_beats_a_weak_page_and_a_guessed_slug(monkeypatch):
    _silence_network(monkeypatch)
    index_html = (
        '<a href="/team/mark-h-deblois/">Mark H. DeBlois</a>'
        '<a href="/team/robert-clark/">Robert Clark</a>'
        '<a href="/team/brian-kinsman/">Brian Kinsman</a>'
        '<a href="/team/lisa-nguyen/">Lisa Nguyen</a>'
    )
    index_text = "Robert Clark Mark H. DeBlois Brian Kinsman Lisa Nguyen Team"
    bio = (
        "Mark H. DeBlois Co-Founder and Managing Partner "
        "Prior to founding Bunker Hill, Mark was a Managing Director at BancBoston Capital. "
        "He received a B.A. from Boston College."
    )
    pages = {
        "https://www.bunkerhillcapital.com": (
            '<a href="/about">Mark DeBlois</a><a href="/team">Team</a>',
            "Mark DeBlois Team",
        ),
        "https://www.bunkerhillcapital.com/about": (
            "<p>Mark DeBlois is a partner at the firm.</p>",
            "Mark DeBlois is a partner at the firm.",
        ),
        "https://www.bunkerhillcapital.com/team": (index_html, index_text),
        "https://www.bunkerhillcapital.com/team/mark-h-deblois": (bio, bio),
    }

    def fake_fetch(url: str, **kwargs: object) -> tuple[str, str]:
        return pages.get(url.rstrip("/"), ("", ""))

    monkeypatch.setattr("mobydick.research.life.fetch_document", fake_fetch)
    with tracing() as trace:
        sources = gather_person_sources(
            {
                "full_name": "Mark DeBlois",
                "first_name": "Mark",
                "last_name": "DeBlois",
                "company_name": "Bunker Hill Capital",
                "company_domain": "bunkerhillcapital.com",
                "company_website": "https://www.bunkerhillcapital.com",
            }
        )
    urls = [source["url"] for source in sources]
    assert any(url.rstrip("/").endswith("/team/mark-h-deblois") for url in urls)
    assert not any(url.rstrip("/").endswith("/team/mark-deblois") for url in urls)
    life = extract_life_story("Mark DeBlois", sources)
    assert "BancBoston" in life["early_jobs"]
    assert "Boston College" in life["college"]
    summary = trace.as_dict()
    assert summary["pages_dropped"] >= 1
    assert summary["drop_reasons"]


def test_team_php_bio_is_split_when_the_heading_has_no_title():
    text = (
        "Stuart McManus Prior to forming Crystal Lake, Stuart was President of Capstar Partners. "
        "David Ackert David spent three years at Beachside Capital before this role."
    )
    life = extract_life_story(
        "Stuart McManus",
        [{"url": "https://crystallakecapital.com/team.php", "title": "Team", "kind": "bio", "text": text}],
    )
    assert "Capstar" in life["early_jobs"]
    assert "Beachside" not in life["early_jobs"]


def test_mr_lastname_bio_keeps_the_prior_employer():
    text = (
        "Alex Szewczyk Managing Partner and Co-Founder of BP Energy Partners. "
        "Mr. Szewczyk spent more than a decade at BP Capital. "
        "He received an MBA from the Cox School of Business."
    )
    life = extract_life_story(
        "Alex Szewczyk",
        [{"url": "https://bpenergypartners.com/team/alex-szewczyk", "title": "Team", "kind": "bio", "text": text}],
    )
    assert "BP Capital" in life["early_jobs"]
    assert "Cox" in life["college"] or "MBA" in life["college"]


def test_alumni_search_runs_even_without_a_team_bio(monkeypatch):
    monkeypatch.setattr("mobydick.research.life.talks_with_transcripts", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.search_episodes", lambda *args, **kwargs: [])
    monkeypatch.setattr("mobydick.research.life.linkedin_posts", lambda *args, **kwargs: [])
    queries: list[str] = []
    article = (
        "Robert Knox was born in Boston and grew up there. "
        "He earned a BA from Boston University."
    )

    def fake_fetch(url: str, **kwargs: object) -> tuple[str, str]:
        if "bu.edu" in url:
            return (article, article)
        return ("<html>Home</html>", "Home")

    def fake_search(query: str, **kwargs: object) -> list[dict[str, str]]:
        queries.append(query)
        if "podcast" in query or "alumni" in query:
            return [
                {
                    "url": "https://www.bu.edu/articles/robert-knox",
                    "title": "Alumni feature: Robert Knox",
                    "description": "",
                }
            ]
        return []

    monkeypatch.setattr("mobydick.research.life.fetch_document", fake_fetch)
    monkeypatch.setattr("mobydick.research.life.google_search", fake_search)
    sources = gather_person_sources(
        {
            "full_name": "Robert Knox",
            "first_name": "Robert",
            "last_name": "Knox",
            "company_name": "Cornerstone Equity Investors",
            "company_domain": "cornerstoneequity.com",
            "company_website": "https://cornerstoneequity.com",
        }
    )
    assert any(query.startswith("site:") for query in queries)
    assert any("podcast" in query for query in queries)
    assert any("grew up" in query or "hometown" in query for query in queries)
    life = extract_life_story("Robert Knox", sources, firm="Cornerstone Equity Investors")
    assert "Boston" in life["hometown"]
    assert "grew up" in life["hometown"].lower() or "born" in life["hometown"].lower()
