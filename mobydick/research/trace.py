"""Per-job research counts. No page text and no secrets."""

from __future__ import annotations

import contextvars
import threading
from collections import Counter
from contextlib import contextmanager
from typing import Iterator


class ResearchTrace:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.reject_reasons: Counter[str] = Counter()
        self.drop_reasons: Counter[str] = Counter()
        self.person_reasons: Counter[str] = Counter()
        self.not_pe_counts: Counter[str] = Counter()
        self.not_pe_samples: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def add(self, key: str, n: int = 1) -> None:
        with self._lock:
            self.counts[key] += n

    def reject(self, reason: str) -> None:
        with self._lock:
            self.counts["facts_rejected"] += 1
            self.reject_reasons[reason] += 1

    def drop_page(self, reason: str) -> None:
        with self._lock:
            self.counts["pages_dropped"] += 1
            self.drop_reasons[reason] += 1

    def drop_person(self, reason: str) -> None:
        with self._lock:
            self.counts["people_dropped"] += 1
            self.person_reasons[reason or "unspecified"] += 1

    def note_not_pe(self, firm: str, phrase: str) -> None:
        label = " ".join((phrase or "unspecified").split())[:160]
        with self._lock:
            self.not_pe_counts[label] += 1
            if len(self.not_pe_samples) < 5:
                self.not_pe_samples.append({"firm": " ".join((firm or "").split())[:80], "phrase": label})

    def merge(self, other: ResearchTrace) -> None:
        """Add one worker's counts into the job total."""
        with self._lock:
            with other._lock:
                self.counts.update(other.counts)
                self.reject_reasons.update(other.reject_reasons)
                self.drop_reasons.update(other.drop_reasons)
                self.person_reasons.update(other.person_reasons)
                self.not_pe_counts.update(other.not_pe_counts)
                room = 5 - len(self.not_pe_samples)
                if room > 0:
                    self.not_pe_samples.extend(other.not_pe_samples[:room])

    def as_dict(self) -> dict[str, object]:
        with self._lock:
            return {
                "pages_fetched": self.counts["pages_fetched"],
                "pages_with_text": self.counts["pages_with_text"],
                "pages_kept": self.counts["pages_kept"],
                "pages_dropped": self.counts["pages_dropped"],
                "pages_rendered": self.counts["pages_rendered"],
                "drop_reasons": dict(sorted(self.drop_reasons.items())),
                "person_drops": dict(sorted(self.person_reasons.items())),
                "not_pe_phrases": dict(sorted(self.not_pe_counts.items())),
                "not_pe_samples": list(self.not_pe_samples),
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


def drop_person(reason: str) -> None:
    trace = _current.get()
    if trace is not None:
        trace.drop_person(reason)


def note_not_pe(firm: str, phrase: str) -> None:
    trace = _current.get()
    if trace is not None:
        trace.note_not_pe(firm, phrase)


def keep_fact() -> None:
    note("facts_extracted")


@contextmanager
def isolated() -> Iterator[ResearchTrace]:
    """Count this worker alone, then fold the totals into the job trace."""
    parent = _current.get()
    child = ResearchTrace()
    token = _current.set(child)
    try:
        yield child
    finally:
        if parent is not None:
            parent.merge(child)
        _current.reset(token)


@contextmanager
def tracing() -> Iterator[ResearchTrace]:
    trace = ResearchTrace()
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)
