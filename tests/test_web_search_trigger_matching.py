"""Specialized search-engine trigger and currency routing must not false-fire.

Regression (2026-09-22): a "Steve Jobs pancreatic neuroendocrine tumor" query
matched the Exchange Rate engine because the trigger substring "eur" occurs
inside "neuroendocrine". The engine then returned a EUR/CNY exchange-rate
result as the first hit of every search (its currency regex also matched "EUR"
inside "NEUROENDOCRINE"), polluting the evidence and leading the final reply to
claim that online search returned no usable results.
"""

import importlib

import pytest


@pytest.fixture()
def web_search():
    return importlib.import_module("tool_factory.web_search")


def _engine(web_search, triggers):
    return web_search.SpecializedEngine("X", triggers, lambda q, m: [])


def test_specialized_triggers_require_a_word_boundary(web_search):
    engine = _engine(
        web_search, ["exchange rate", "usd", "eur", "dollar", "euro", "yen", "pound"]
    )
    assert not engine.matches(
        "Steve Jobs pancreatic neuroendocrine tumor Whipple procedure treatment"
    )
    assert not engine.matches("neuroendocrine tumor islet cell")
    paper = _engine(web_search, ["paper"])
    assert not paper.matches("newspaper")
    assert not paper.matches("wallpaper")
    assert engine.matches("eur to cny exchange rate")
    assert engine.matches("EUR/USD")
    assert engine.matches("dollar to yuan")
    assert paper.matches("paper about radiotherapy")


def test_search_exchange_rate_makes_no_call_without_currency_context(
    web_search, monkeypatch
):
    calls = []

    def fake_get(*_args, **_kwargs):
        calls.append(1)
        raise AssertionError("requests.get must not be called")

    monkeypatch.setattr(web_search.requests, "get", fake_get)
    out = web_search._search_exchange_rate(
        "Steve Jobs pancreatic neuroendocrine tumor Whipple procedure treatment", 5
    )
    assert out == []
    assert calls == []


def test_search_exchange_rate_returns_rate_for_real_currency_query(
    web_search, monkeypatch
):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"rates": {"CNY": 7.5}}

    monkeypatch.setattr(web_search.requests, "get", lambda *a, **k: Response())
    out = web_search._search_exchange_rate("EUR to CNY exchange rate", 5)
    assert out and out[0]["title"].startswith("EUR/CNY")
    assert "7.5" in out[0]["snippet"]


def test_empty_specialized_result_does_not_block_later_engines(web_search, monkeypatch):
    calls = []

    def first_fn(query, max_results):
        calls.append("first")
        return []

    def second_fn(query, max_results):
        calls.append("second")
        return [
            {
                "title": "alpha beta gamma",
                "snippet": "alpha beta gamma",
                "url": "https://ok.example/1",
                "source": "PubMed",
            }
        ]

    monkeypatch.setattr(
        web_search,
        "SPECIALIZED_ENGINES",
        [
            web_search.SpecializedEngine("First", ["alpha"], first_fn),
            web_search.SpecializedEngine("Second", ["beta"], second_fn),
        ],
    )

    class FakeBing:
        def search_with_retry(self, *a, **k):
            return []

    tool = web_search.WebSearchTool()
    tool.engines = {"bing": FakeBing(), "sogou": FakeBing(),
                    "pubmed": FakeBing(), "github": FakeBing()}
    results = tool._search_general("alpha beta gamma", 5)
    assert "second" in calls
    assert any(r.get("url") == "https://ok.example/1" for r in results)


def test_irrelevant_specialized_hits_are_not_merged(web_search, monkeypatch):
    def junk_fn(query, max_results):
        return [
            {
                "title": "Junk",
                "snippet": "",
                "url": "https://junk.example/1",
                "source": "X",
            }
        ]

    monkeypatch.setattr(
        web_search,
        "SPECIALIZED_ENGINES",
        [web_search.SpecializedEngine("Junk", ["alpha"], junk_fn)],
    )

    class FakeBing:
        def search_with_retry(self, *a, **k):
            return [
                {
                    "title": "alpha beta gamma guide",
                    "snippet": "alpha beta gamma",
                    "url": "https://good.example/1",
                    "source": "Bing",
                }
            ]

    tool = web_search.WebSearchTool()
    tool.engines = {"bing": FakeBing(), "sogou": FakeBing(),
                    "pubmed": FakeBing(), "github": FakeBing()}
    results = tool._search_general("alpha beta gamma", 5)
    assert any(r.get("url") == "https://good.example/1" for r in results)
    assert all("junk.example" not in (r.get("url") or "") for r in results)
