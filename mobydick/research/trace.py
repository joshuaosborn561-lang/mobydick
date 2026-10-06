"""Per-job research counts. No page text and no secrets."""

from __future__ import annotations

import contextvars
from collections import Counter
from contextlib import contextmanager
from typing import Iterator


class ResearchTrace:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.reject_reasons: Counter[str] = Counter()
        self.drop_reasons: Counter[str] = Counter()

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] += n

    def reject(self, reason: str) -> None:
        self.counts["facts_rejected"] += 1
        self.reject_reasons[reason] += 1

    def drop_page(self, reason: str) -> None:
        self.counts["pages_dropped"] += 1
        self.drop_reasons[reason] += 1

    def as_dict(self) -> dict[str, object]:
        return {
            "pages_fetched": self.counts["pages_fetched"],
            "pages_with_text": self.counts["pages_with_text"],
            "pages_kept": self.counts["pages_kept"],
            "pages_dropped": self.counts["pages_dropped"],
            "pages_rendered": self.counts["pages_rendered"],
            "drop_reasons": dict(sorted(self.drop_reasons.items())),
            "searches_run": self.counts["searches_run"],
            "llm_calls": self.counts["llm_calls"],
            "facts_extracted": self.counts["facts_extracted"],
            "facts_rejected": self.counts["facts_rejected"],
            "reject_reasons": dict(sorted(self.reject_reasons.items())),
        }


_current: contextvars.ContextVar[ResearchTrace | None] = contextvars.ContextVar(
    "mobydick_research_trace",
    default=None,
)


def current() -> ResearchTrace | None:
    return _current.get()


def note(key: str, n: int = 1) -> None:
    trace = _current.get()
    if trace is not None:
        trace.add(key, n)


def reject(reason: str) -> None:
    trace = _current.get()
    if trace is not None:
        trace.reject(reason)


def drop_page(reason: str) -> None:
    trace = _current.get()
    if trace is not None:
        trace.drop_page(reason)


def keep_fact() -> None:
    note("facts_extracted")


@contextmanager
def tracing() -> Iterator[ResearchTrace]:
    trace = ResearchTrace()
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)
