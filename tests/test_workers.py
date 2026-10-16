import time

from mobydick.enrich import enrich_rows
from mobydick.pipeline import _score_footprints
from mobydick.workers import map_ordered, worker_count


def test_worker_count_defaults_to_eight_and_caps_at_sixteen(monkeypatch):
    monkeypatch.delenv("ENRICH_WORKERS", raising=False)
    monkeypatch.delenv("PIPELINE_WORKERS", raising=False)
    assert worker_count("ENRICH_WORKERS") == 8
    assert worker_count("PIPELINE_WORKERS") == 8
    monkeypatch.setenv("ENRICH_WORKERS", "99")
    monkeypatch.setenv("PIPELINE_WORKERS", "0")
    assert worker_count("ENRICH_WORKERS") == 16
    assert worker_count("PIPELINE_WORKERS") == 1
    monkeypatch.setenv("ENRICH_WORKERS", "not-a-number")
    assert worker_count("ENRICH_WORKERS") == 8
    assert worker_count("ENRICH_WORKERS", 3) == 3


def test_map_ordered_is_sequential_when_workers_is_one():
    events: list[tuple[str, int]] = []

    def work(item: int) -> int:
        events.append(("start", item))
        time.sleep(0.02)
        events.append(("end", item))
        return item * 10

    assert map_ordered(work, [1, 2, 3], workers=1) == [10, 20, 30]
    assert events == [
        ("start", 1),
        ("end", 1),
        ("start", 2),
        ("end", 2),
        ("start", 3),
        ("end", 3),
    ]


def test_map_ordered_keeps_input_order_when_parallel():
    def work(item: int) -> int:
        time.sleep(0.03 if item == 1 else 0.001)
        return item * 10

    assert map_ordered(work, [1, 2, 3, 4], workers=4) == [10, 20, 30, 40]


def test_enrich_rows_stays_sequential_when_workers_is_one(monkeypatch):
    monkeypatch.setenv("ENRICH_WORKERS", "1")
    events: list[tuple[str, str]] = []

    def fake_apply(raw, audience, *, fetch_pages=True):
        events.append(("start", raw["full_name"]))
        time.sleep(0.02)
        events.append(("end", raw["full_name"]))
        return {"full_name": raw["full_name"], "dq": ""}

    monkeypatch.setattr("mobydick.enrich.apply_enrichment", fake_apply)
    raws = [
        {"full_name": "First Person"},
        {"full_name": "Second Person"},
        {"full_name": "Third Person"},
    ]
    out = enrich_rows(raws, "series_ab", fetch_pages=True)
    assert [row["full_name"] for row in out] == [
        "First Person",
        "Second Person",
        "Third Person",
    ]
    assert events == [
        ("start", "First Person"),
        ("end", "First Person"),
        ("start", "Second Person"),
        ("end", "Second Person"),
        ("start", "Third Person"),
        ("end", "Third Person"),
    ]


def test_score_footprints_stays_sequential_when_workers_is_one(monkeypatch):
    monkeypatch.setenv("PIPELINE_WORKERS", "1")
    events: list[tuple[str, str]] = []

    def fake_apply(row: dict[str, str]) -> None:
        events.append(("start", row["id"]))
        time.sleep(0.02)
        events.append(("end", row["id"]))
        row["_footprint_score"] = 1
        row["_footprint_hits"] = []

    monkeypatch.setattr("mobydick.pipeline._apply_footprint", fake_apply)
    rows = [{"id": "one"}, {"id": "two"}]
    _score_footprints(rows, 10)
    assert events == [
        ("start", "one"),
        ("end", "one"),
        ("start", "two"),
        ("end", "two"),
    ]
    assert [row["_footprint_score"] for row in rows] == [1, 1]
