from mobydick.schemas import PE_COLUMNS, SERIES_AB_COLUMNS, compact_sample, empty_row


def test_empty_row_matches_contract():
    assert list(empty_row("series_ab")) == SERIES_AB_COLUMNS
    assert list(empty_row("pe_partners")) == PE_COLUMNS


def test_compact_sample_strips_sensitive_fields():
    sample = compact_sample(
        {
            "full_name": "Ada",
            "email": "hidden@x.com",
            "best_emotional_hook": "secret",
            "company_name": "Acme",
            "title": "CEO",
        }
    )
    assert sample == {"full_name": "Ada", "title": "CEO", "company_name": "Acme"}
    leaked = compact_sample(
        {
            "full_name": "Pat",
            "family_background": "parents ran a diner",
            "quotes": "I still write letters",
            "real_story": "long story",
            "email": "pat@firm.com",
        }
    )
    assert leaked == {"full_name": "Pat"}
