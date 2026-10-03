from mobydick.domains import domains_from_values, normalize_domain


def test_normalize_strips_scheme_www_and_path():
    assert normalize_domain("https://www.Acme.io/about?x=1") == "acme.io"
    assert normalize_domain("http://www.acme.io.") == "acme.io"
    assert normalize_domain("jane@acme.io") == "acme.io"
    assert normalize_domain("") == ""


def test_domains_from_values_dedupes():
    assert domains_from_values(["https://A.com", "a.com", "", "b.com"]) == ["a.com", "b.com"]
