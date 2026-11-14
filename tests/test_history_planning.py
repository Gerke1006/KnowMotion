"""Isolated History Pack contracts; live acceptance remains scripts/verify_live.py."""
import copy
import json

import pytest

from harness.asset_retriever import AssetRetriever
from harness.history import normalize_history_component, referenced_source_ids, validate_history_parameters
from harness.schemas import Domain
from workflows.planning import load_pack, plan, route_topic, visual_plan


SOURCES = [{"id": "source_01", "title": "Retrieved archive", "url": "https://example.org/archive", "status": "retrieved"}]
MAP = {"title": "交流示意", "locations": [
    {"id": "a", "name": "甲地", "lon": 80, "lat": 35},
    {"id": "b", "name": "乙地", "lon": 100, "lat": 40}],
    "routes": [{"from": "a", "to": "b", "label": "往来示意"}], "source_ids": ["source_01"]}
TIMELINE = {"events": [{"year": 100, "label": "后期事件"},
                       {"year": -200, "date_label": "约公元前2世纪", "label": "早期背景"}],
            "source_ids": ["source_01"]}
PERSON = {"name": "示例人物", "role": "使者", "years": "活动于示例时期", "facts": ["此为隔离测试资料"],
          "source_ids": ["source_01"]}


def test_history_pack_prefers_remotion_and_source_aware_components():
    pack = load_pack(Domain.history)
    assert pack["version"] == "2.0"
    assert pack["preferred_renderer"] == "remotion"
    assert set(pack["components"]) == {"history.map", "history.timeline", "history.person"}


def test_map_normalization_is_a_copy_with_safe_schematic_routes():
    original = {"id": "history.map", "parameters": copy.deepcopy(MAP)}
    normalized = normalize_history_component(original, sources=SOURCES, require_sources=True)
    assert normalized["parameters"]["routes"][0]["kind"] == "schematic"
    assert "示意" in normalized["parameters"]["note"]
    assert "kind" not in original["parameters"]["routes"][0]
    assert normalized["parameters"]["routes"][0]["from"] == "a"


@pytest.mark.parametrize("change", ["nan", "latitude", "duplicate", "endpoint", "viewport", "route_kind"])
def test_invalid_geography_is_rejected_before_rendering(change):
    data = copy.deepcopy(MAP)
    if change == "nan":
        data["locations"][0]["lon"] = float("nan")
    elif change == "latitude":
        data["locations"][0]["lat"] = 100
    elif change == "duplicate":
        data["locations"][1]["id"] = "a"
    elif change == "endpoint":
        data["routes"][0]["to"] = "missing"
    elif change == "viewport":
        data["viewport"] = {"west": 20, "east": 60, "south": 0, "north": 50}
    else:
        data["routes"][0]["kind"] = "exact_historical_itinerary"
    with pytest.raises(ValueError):
        validate_history_parameters("history.map", data)


def test_civil_timeline_sorted_and_approximate_display_preserved():
    data = copy.deepcopy(TIMELINE)
    actual = validate_history_parameters("history.timeline", data)
    assert [event["year"] for event in actual["events"]] == [-200, 100]
    assert actual["events"][0]["date_label"] == "约公元前2世纪"
    assert data["events"][0]["year"] == 100


@pytest.mark.parametrize("change", ["year_zero", "nonfinite", "backwards_range", "outside_range"])
def test_invalid_timeline_dates(change):
    data = copy.deepcopy(TIMELINE)
    if change == "year_zero":
        data["events"][0]["year"] = 0
    elif change == "nonfinite":
        data["events"][0]["year"] = float("inf")
    elif change == "backwards_range":
        data["range"] = [100, -200]
    else:
        data["range"] = [1, 200]
    with pytest.raises(ValueError):
        validate_history_parameters("history.timeline", data)


@pytest.mark.parametrize("path", ["https://example.org/portrait.jpg", "../portrait.png", "portraits/../../secret.png",
                                   "C:/private.jpg", "/etc/private.svg", "portraits\\other.png", "portraits/a.html"])
def test_portrait_references_cannot_escape_approved_assets(path):
    with pytest.raises(ValueError):
        validate_history_parameters("history.person", {**PERSON, "portrait_asset": path})


def test_person_card_requires_evidence_and_readable_facts():
    with pytest.raises(ValueError, match="source_ids"):
        validate_history_parameters("history.person", {**PERSON, "source_ids": []}, sources=SOURCES, require_sources=True)
    with pytest.raises(ValueError, match="source_ids"):
        validate_history_parameters("history.person", {**PERSON, "source_ids": ["fabricated"]}, sources=SOURCES)
    with pytest.raises(ValueError):
        validate_history_parameters("history.person", {**PERSON, "facts": []})
    with pytest.raises(ValueError):
        validate_history_parameters("history.person", {**PERSON, "facts": ["长" * 101]})


def test_nested_citations_are_included_in_the_source_legend():
    data = copy.deepcopy(MAP)
    data["locations"][0]["source_ids"] = ["source_02"]
    assert referenced_source_ids({"parameters": data}) == {"source_01", "source_02"}


async def test_history_agent_contract_citations_and_all_three_asset_tiers():
    class Gateway:
        async def generate_json(self, system, prompt):
            request = json.loads(prompt)
            assert request["request"]["narration_char_budget"] == 440
            assert request["research"]["geography"]["records"]
            assert "date_label" in system and "不是数组" in system
            scenes = []
            for index, (kind, data) in enumerate([("history.map", MAP), ("history.timeline", TIMELINE),
                                                  ("history.person", PERSON), ("history.map", MAP)]):
                scenes.append({"scene_id": f"s{index}", "title": "测试", "domain": "history", "learning_goal": "测试",
                               "narration": "隔离单元测试。", "visual_concept": "测试", "duration": 20,
                               "renderer": "canvas", "components": [{"id": kind, "parameters": copy.deepcopy(data)}]})
            return {"learning_objectives": ["时空关系"], "teaching_structure": ["地图", "事件", "人物", "总结"], "scenes": scenes}

    request = route_topic("丝绸之路", mode="live", duration=80, narration_char_budget=440)
    evidence = {"sources": SOURCES, "knowledge": ["隔离测试资料"], "geography": {"records": MAP["locations"]}}
    teaching = await plan(request, evidence, Gateway())
    assert all(scene.renderer == "remotion" for scene in teaching.scenes)
    assert all(scene.extensions["historical_sources"][0]["id"] == "source_01" for scene in teaching.scenes)
    visual = visual_plan(teaching)
    assert visual.style["id"] == "archival_motion"
    assert visual.style["font"] == "SimSun" and visual.style["english_font"] == "Times New Roman"
    manifest = AssetRetriever().retrieve(visual)
    assert all(item.tier == "complete" for item in manifest.assets)
    assert teaching.sources == SOURCES


async def test_live_history_rejects_hallucinated_citation():
    class Gateway:
        async def generate_json(self, *_):
            return {"learning_objectives": ["x"], "teaching_structure": ["x"], "scenes": [{
                "scene_id": "s1", "domain": "history", "learning_goal": "x", "narration": "x", "visual_concept": "x",
                "duration": 10, "components": [{"id": "history.person", "parameters": {**PERSON, "source_ids": ["unknown"]}}]}]}
    with pytest.raises(ValueError, match="source_ids"):
        await plan(route_topic("张骞", mode="live"), {"sources": SOURCES}, Gateway())


@pytest.mark.parametrize("geography", [{}, {"records": [{**point, "lon": point["lon"] + 1}
                                                       for point in MAP["locations"]]}])
async def test_live_history_rejects_missing_or_changed_coordinate_evidence(geography):
    class Gateway:
        async def generate_json(self, *_):
            return {"learning_objectives": ["x"], "teaching_structure": ["x"], "scenes": [{
                "scene_id": "s1", "domain": "history", "learning_goal": "x", "narration": "x", "visual_concept": "x",
                "duration": 10, "components": [{"id": "history.map", "parameters": copy.deepcopy(MAP)}]}]}
    with pytest.raises(ValueError, match="可追溯的坐标"):
        await plan(route_topic("历史主题", domain="history", mode="live"),
                   {"sources": SOURCES, "geography": geography}, Gateway())
