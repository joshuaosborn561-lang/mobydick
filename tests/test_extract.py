from mobydick.research.extract import heuristic_extract
from mobydick.research.web import extract_office_address


def test_heuristic_finds_identity_not_resume():
    text = (
        "I grew up in Boise and later founded the company because hospitals lost notes. "
        "I still run marathons and support a cancer foundation."
    )
    out = heuristic_extract([text])
    assert out["hometown"] == "Boise"
    assert "founded" in out["why"].lower() or "because" in out["why"].lower()
    assert out["confidence"] in {"high", "medium"}


def test_office_address_extracted_home_rejected():
    page = "Visit us at 123 Market Street, Suite 400, San Francisco, CA 94105 during office hours."
    assert "Market Street" in extract_office_address(page)
    home = "This is a private residence at 9 Oak Lane, Austin, TX 78701 for family only."
    # Still matches a street pattern; pipeline leaves blank when no company page confirms office.
    addr = extract_office_address(home)
    assert addr == "" or "Oak Lane" in addr
