import pytest

from mobydick.audiences import default_filters, getleads_search_args, normalize_audience, overfetch_count, pe_scan_cap


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


def test_pe_scan_cap_is_wider_than_a_2x_pull():
    assert pe_scan_cap(10) == 80
    assert pe_scan_cap(1) == 40
    assert pe_scan_cap(500) == 2000
    assert pe_scan_cap(10, story_first=True) == 300
    assert pe_scan_cap(1, story_first=True) == 30
    assert pe_scan_cap(100, story_first=True) == 2000


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
    assert "Economist" in filters["exclude_job_titles"]
    assert "Partner" in filters["job_titles"]
    assert "Founder" in filters["job_titles"]
    assert filters["industries"] == ["Venture Capital and Private Equity Principals"]
    assert filters["countries"] == ["United States"]
    assert filters["headquarters_countries"] == ["United States"]
    assert "Capital Markets" not in filters["industries"]
    assert "Investment Management" not in filters["industries"]


def test_wire_filters_match_getleads_search_schema():
    """Names GetLeads SearchFilters still accepts. Classic column names are not filters."""
    allowed = {
        "industries",
        "job_titles",
        "exclude_job_titles",
        "headquarters_countries",
        "countries",
        "require_email",
        "company_description",
        "funding_types",
    }
    for audience in ("pe_partners", "series_ab"):
        wire = getleads_search_args(default_filters(audience))
        assert set(wire) <= allowed
        assert "funded_since" not in wire
