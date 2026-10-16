import pytest

from mobydick.getleads_gate import (
    RateLimiter,
    claim_person,
    getleads_concurrency,
    release_people,
    reserve_search_offset,
    reset_getleads_gate,
)


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


def test_getleads_concurrency_reads_env(monkeypatch):
    monkeypatch.delenv("GETLEADS_CONCURRENCY", raising=False)
    reset_getleads_gate()
    assert getleads_concurrency() == 2
    monkeypatch.setenv("GETLEADS_CONCURRENCY", "3")
    reset_getleads_gate()
    assert getleads_concurrency() == 3
    monkeypatch.setenv("GETLEADS_CONCURRENCY", "0")
    assert getleads_concurrency() == 1
    monkeypatch.setenv("GETLEADS_CONCURRENCY", "nope")
    assert getleads_concurrency() == 2


def test_rate_limiter_spaces_starts_at_four_per_second():
    sleeps: list[float] = []
    ticks = iter([100.0, 100.05])
    limiter = RateLimiter(rps=4)
    limiter.clock = lambda: next(ticks)
    limiter.sleep = sleeps.append
    limiter.wait()
    limiter.wait()
    assert sleeps == [pytest.approx(0.20)]
    assert limiter.interval == pytest.approx(0.25)
