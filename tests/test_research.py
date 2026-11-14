"""Isolated search regression tests; live acceptance remains a separate run."""
import json

import httpx
import pytest

from workflows.planning import route_topic
from workflows.research import _history_geography, research


async def test_live_research_sends_identifiable_contact_and_supported_extract_size(monkeypatch):
    """Exercise the real request path against an isolated provider transport."""
    requests = []

    def provider(request):
        requests.append(request)
        agent = request.headers.get("User-Agent", "")
        assert "KnowMotion/" in agent
        assert "https://github.com/Gerke1006/KnowMotion" in agent
        if request.url.params.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": [{"pageid": 42}]}})
        assert 1 <= int(request.url.params["exchars"]) <= 1200
        return httpx.Response(200, json={"query": {"pages": {"42": {
            "title": "Provider fixture", "fullurl": f"https://{request.url.host}/wiki/Fixture",
            "extract": "Isolated test evidence.",
        }}}})

    original_client = httpx.AsyncClient
    monkeypatch.setattr("workflows.research.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs))

    class Gateway:
        async def generate_json(self, system, prompt):
            assert len(json.loads(prompt)["sources"]) == 2
            return {"knowledge": ["Isolated test evidence."]}

    result = await research(route_topic("导数", mode="live"), Gateway())
    assert len(requests) == 4
    assert len(result["sources"]) == 2
    assert all(source["status"] == "retrieved" for source in result["sources"])


async def test_natural_language_prompt_retries_concept_queries_with_provider_sources(monkeypatch):
    calls = []
    source = {"url": "https://en.wikipedia.org/wiki/Derivative", "title": "Derivative",
              "excerpt": "The derivative is an instantaneous rate of change.", "status": "retrieved"}

    async def lookup(query, language, client):
        calls.append((query, language))
        return [source] if query == "derivative" and language == "en" else []

    class Gateway:
        def __init__(self):
            self.calls = 0

        async def generate_json(self, system, prompt):
            self.calls += 1
            if self.calls == 1:
                assert json.loads(prompt)["topic"] == "用动画解释导数为什么是瞬时变化率"
                return {"zh": "导数", "en": "derivative", "sources": [{"url": "https://fake.invalid"}]}
            assert json.loads(prompt)["sources"] == [source]
            return {"knowledge": ["An instantaneous rate of change."], "sources": [{"url": "https://fake.invalid"}]}

    monkeypatch.setattr("workflows.research._wiki_sources", lookup)
    gateway = Gateway()
    result = await research(route_topic("用动画解释导数为什么是瞬时变化率", mode="live"), gateway)
    assert result["sources"] == [source]
    assert gateway.calls == 2
    assert ("导数", "zh") in calls and ("derivative", "en") in calls
    assert result["search_queries"][-1] == {"language": "en", "query": "derivative"}


async def test_successful_direct_search_does_not_request_model_query(monkeypatch):
    source = {"url": "https://en.wikipedia.org/wiki/Derivative", "excerpt": "A rate of change."}

    async def lookup(query, language, client):
        return [source]

    class Gateway:
        async def generate_json(self, system, prompt):
            assert json.loads(prompt)["sources"] == [source]
            return {"knowledge": ["A rate of change."]}

    monkeypatch.setattr("workflows.research._wiki_sources", lookup)
    result = await research(route_topic("导数", mode="live"), Gateway())
    assert result["sources"] == [source]
    assert len(result["search_queries"]) == 2


@pytest.mark.parametrize("terms", [{"zh": "导数", "en": "derivative"}, {"zh": [], "en": "x" * 121}])
async def test_no_retrieved_sources_still_fails_explicitly(monkeypatch, terms):
    calls = []

    async def lookup(query, language, client):
        calls.append((query, language))
        return []

    class Gateway:
        async def generate_json(self, system, prompt):
            assert "sources" not in json.loads(prompt)
            return terms

    monkeypatch.setattr("workflows.research._wiki_sources", lookup)
    with pytest.raises(RuntimeError, match="可追溯"):
        await research(route_topic("解释导数", mode="live"), Gateway())
    assert len(calls) <= 4


def test_history_geography_keeps_silk_road_catalog_scoped_to_its_topics():
    catalog = _history_geography("张骞与丝绸之路", ["张骞出使西域。"])
    assert len(catalog["records"]) == 7
    assert "丝绸之路" in catalog["topics"]
    assert all(record["source"]["url"].startswith("https://www.wikidata.org/")
               for record in catalog["records"])


@pytest.mark.parametrize("topic,knowledge", [
    ("文艺复兴", ["佛罗伦萨的艺术与人文主义。"]),
    ("希腊化时期", ["亚历山大城是交流中心。"]),
    ("Renaissance", ["Alexandrian art and Balkhi scholarship."]),
])
def test_unrelated_or_insufficient_places_do_not_supply_silk_road_geography(topic, knowledge):
    assert _history_geography(topic, knowledge) is None


def test_history_geography_selects_only_explicitly_mentioned_places_and_preserves_provenance():
    catalog = _history_geography("跨地区文化交流", ["撒马尔罕与 Alexandria。"])
    assert [record["id"] for record in catalog["records"]] == ["samarkand", "alexandria"]
    complete = _history_geography("丝绸之路", [])
    assert catalog["records"] == [record for record in complete["records"]
                                  if record["id"] in {"samarkand", "alexandria"}]
    assert catalog["map_notice"] == complete["map_notice"]


async def test_history_research_does_not_attach_unrelated_geography(monkeypatch):
    source = {"url": "https://en.wikipedia.org/wiki/Renaissance", "excerpt": "Florence and humanism."}

    async def wiki_lookup(query, language, client):
        return [source]

    async def history_lookup(topic, client):
        return []

    class Gateway:
        async def generate_json(self, system, prompt):
            assert json.loads(prompt)["sources"][0]["id"] == "source_01"
            return {"knowledge": ["文艺复兴与佛罗伦萨的人文主义有关。"]}

    monkeypatch.setattr("workflows.research._wiki_sources", wiki_lookup)
    monkeypatch.setattr("workflows.research._history_sources", history_lookup)
    result = await research(route_topic("文艺复兴", mode="live"), Gateway())
    assert "geography" not in result
    assert result["sources"][0]["url"] == source["url"]
