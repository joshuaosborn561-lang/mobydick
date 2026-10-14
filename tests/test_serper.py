import requests

from mobydick.config import load_settings
from mobydick.research.trace import tracing


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _settings(monkeypatch, key: str):
    if key:
        monkeypatch.setenv("SERPER_API_KEY", key)
    else:
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
    cfg = load_settings()
    monkeypatch.setattr("mobydick.research.serper.default_settings", cfg)
    return cfg


def test_google_search_posts_to_serper_and_maps_organic(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Resp(
            {
                "organic": [
                    {
                        "title": "Jane Okonkwo | Anacapa",
                        "link": "https://anacapapartners.com/team/jane",
                        "snippet": "Jane grew up in Dayton.",
                    },
                    {
                        "title": "skip me",
                        "link": "/relative",
                        "snippet": "not a url",
                    },
                ]
            }
        )

    def fail_apify(*args, **kwargs):
        raise AssertionError("must not fall back to Apify")

    cfg = _settings(monkeypatch, "test-serper-key")
    assert cfg.serper_api_key == "test-serper-key"
    monkeypatch.setattr("mobydick.research.serper.requests.post", fake_post)
    monkeypatch.setattr("mobydick.research.apify.run_actor", fail_apify)

    from mobydick.research.serper import google_search

    with tracing() as trace:
        results = google_search("Jane Okonkwo Anacapa", limit=8)

    assert calls == [
        {
            "url": "https://google.serper.dev/search",
            "headers": {"X-API-KEY": "test-serper-key"},
            "json": {"q": "Jane Okonkwo Anacapa", "gl": "us", "hl": "en", "num": 8},
            "timeout": 20,
        }
    ]
    assert results == [
        {
            "url": "https://anacapapartners.com/team/jane",
            "title": "Jane Okonkwo | Anacapa",
            "description": "Jane grew up in Dayton.",
            "snippet": "Jane grew up in Dayton.",
        }
    ]
    assert trace.counts["searches_run"] == 1


def test_google_search_without_key_is_empty_and_does_not_call_serper(monkeypatch):
    cfg = _settings(monkeypatch, "")
    assert cfg.serper_api_key == ""

    def fail_post(*args, **kwargs):
        raise AssertionError("must not call Serper without a key")

    def fail_apify(*args, **kwargs):
        raise AssertionError("must not fall back to Apify")

    monkeypatch.setattr("mobydick.research.serper.requests.post", fail_post)
    monkeypatch.setattr("mobydick.research.apify.run_actor", fail_apify)

    from mobydick.research.serper import google_search

    assert google_search("anyone") == []


def test_google_search_request_error_is_empty(monkeypatch):
    _settings(monkeypatch, "test-serper-key")

    def boom(*args, **kwargs):
        raise requests.Timeout("serper timed out")

    monkeypatch.setattr("mobydick.research.serper.requests.post", boom)

    from mobydick.research.serper import google_search

    assert google_search("anyone") == []
