import pytest

from mobydick.audiences import default_filters, getleads_search_args, normalize_audience, overfetch_count


def test_normalize_audience():
    assert normalize_audience("Series A/B") == "series_ab"
    assert normalize_audience("saas_founders") == "series_ab"
    assert normalize_audience("pe") == "pe_partners"
    with pytest.raises(ValueError):
        normalize_audience("interns")


def test_overfetch_clamped():
    assert overfetch_count(100, 2.0) == 200
    assert overfetch_count(100, 9.0) == 300
    assert overfetch_count(100, 0.1) == 150


def test_series_ab_filters_drop_helper_keys():
    filters = default_filters("series_ab", funded_since="2024-06-01")
    assert "series a" in filters["funding_types"]
    assert filters["headquarters_countries"] == ["United States"]
    wire = getleads_search_args(filters)
    assert "funded_since" not in wire
    assert "funding_types" in wire


def test_pe_filters_drop_juniors():
    filters = default_filters("pe_partners")
    assert "Associate" in filters["exclude_job_titles"]
    assert "Partner" in filters["job_titles"]


def test_wire_filters_match_getleads_search_schema():
    """Names GetLeads SearchFilters still accepts. Classic column names are not filters."""
    allowed = {
        "industries",
        "job_titles",
        "exclude_job_titles",
        "headquarters_countries",
        "require_email",
        "company_description",
        "funding_types",
    }
    for audience in ("pe_partners", "series_ab"):
        wire = getleads_search_args(default_filters(audience))
        assert set(wire) <= allowed
        assert "funded_since" not in wire
