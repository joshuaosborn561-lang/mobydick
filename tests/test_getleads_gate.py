from mobydick.getleads_gate import claim_person, release_people, reserve_search_offset


def test_same_day_cursor_and_inflight_claims_do_not_overlap(tmp_path):
    filters = {"job_titles": ["Partner"], "countries": ["United States"]}
    assert reserve_search_offset(filters, 100, tmp_path) == 0
    assert reserve_search_offset(filters, 100, tmp_path) == 100
    other = {"job_titles": ["Partner"], "countries": ["United States"], "industries": ["Private Equity"]}
    assert reserve_search_offset(other, 50, tmp_path) == 0
    assert claim_person("nm:ann keeper|ann.com") is True
    assert claim_person("nm:ann keeper|ann.com") is False
    release_people({"nm:ann keeper|ann.com"})
    assert claim_person("nm:ann keeper|ann.com") is True
    release_people({"nm:ann keeper|ann.com"})
