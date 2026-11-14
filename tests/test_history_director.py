"""Generic isolated fixtures; these are never live video acceptance content."""
import copy
import json
from pathlib import Path

import pytest

from harness.history_director import (
    DirectorValidationError, compile_scene, validate_director, validate_film_timeline,
    validate_script,
)
from workflows.history_director import generate_director, generate_script, repair_director


@pytest.fixture
def production_data():
    resources = json.loads((Path(__file__).resolve().parents[1] / "assets/history/animation_resources.json")
                           .read_text(encoding="utf-8"))
    source = {"id": "evidence_1", "title": "Generic isolated archive", "url": "https://example.org/archive",
              "status": "retrieved", "excerpt": "A test archive.", "evidence_text": "Excluded long evidence"}
    research = {"sources": [source], "knowledge": ["隔离测试资料"],
                "old_storyboard": {"narration": "This must never enter a generation prompt"}}
    script = {"title": "隔离测试", "segments": [
        {"id": f"segment_{index}", "narration": "甲乙丙丁戊己庚辛壬癸" * 8,
         "source_ids": [source["id"]], "intent": f"测试意图{index}"} for index in range(5)]}
    scenes = []
    for index, segment in enumerate(script["segments"]):
        beats = []
        for beat_index in range(4):
            beats.append({"id": f"beat_{beat_index}",
                          "anchor": {"quote": "甲乙", "occurrence": 1 + beat_index * 2, "edge": "start"},
                          "visible_ids": ["traveler"], "focus_id": "traveler", "keywords": [],
                          "actions": [{"target_id": "traveler", "kind": "walk",
                                       "to_x": .3 + .1 * beat_index, "to_y": .7}],
                          "camera": {"x": .5, "y": .5, "zoom": 1},
                          "sfx": {"asset_id": "sfx.footstep", "align": "onset", "gain_db": 0}
                          if beat_index < 3 else None})
        scenes.append({"scene_id": f"scene_{index}", "segment_id": segment["id"], "environment": "road",
                       "objects": [{"id": "traveler", "asset_id": "actor.person", "x": .2, "y": .7,
                                    "scale": 1, "facing": 1, "label": "", "parameters": {}}], "beats": beats})
    plan = {"schema_version": "2.0", "style_id": "gufeng", "scenes": scenes}
    words = [{"text": character, "char_start": index, "char_end": index + 1,
              "start": .4 + index * .16, "end": .4 + (index + 1) * .16}
             for index, character in enumerate(script["segments"][0]["narration"])]
    speech = {"trim_start": .4, "duration": 12.8}
    return script, plan, resources, research, words, speech


def compiled(data):
    script, plan, resources, research, words, speech = data
    return [compile_scene(scene, segment, words, speech, resources, research["sources"])
            for scene, segment in zip(plan["scenes"], script["segments"])]


def test_valid_script_and_director_are_independent_deep_copies(production_data):
    script, plan, resources, research, _, _ = production_data
    original = copy.deepcopy(plan)
    result = validate_director(plan, script, resources, research)
    result.scenes[0].objects[0].parameters["isolated"] = True
    assert plan == original
    assert validate_script(script, research["sources"]).title == script["title"]


@pytest.mark.parametrize("change", ["short", "segments", "duplicate", "source", "extra"])
def test_script_rejects_invalid_structure_or_evidence(production_data, change):
    script, _, _, research, _, _ = production_data
    if change == "short":
        script["segments"][0]["narration"] = "短"
    elif change == "segments":
        script["segments"] = script["segments"][:4]
    elif change == "duplicate":
        script["segments"][1]["id"] = script["segments"][0]["id"]
    elif change == "source":
        script["segments"][0]["source_ids"] = ["unknown"]
    else:
        script["segments"][0]["instructions"] = "execute something"
    with pytest.raises(DirectorValidationError) as failure:
        validate_script(script, research["sources"])
    json.dumps(failure.value.errors)
    assert len(str(failure.value)) <= 1800


@pytest.mark.parametrize("change,code", [
    ("object", "unknown_object"), ("action", "unsupported_action"),
    ("asset", "unknown_visual_asset"), ("parameters", "unexpected_parameters"),
    ("source", "unknown_source"), ("quote", "anchor_not_found"),
    ("order", "anchor_order"), ("unused", "unused_object"), ("sfx", "unknown_sfx"),
    ("scene_binding", "segment_scene_binding"), ("duplicate_scene", "duplicate_scene"),
    ("no_change", "no_semantic_change"), ("exit", "exited_object_visible"),
])
def test_director_rejects_invalid_runtime_references(production_data, change, code):
    script, plan, resources, research, _, _ = production_data
    scene = plan["scenes"][0]
    if change == "object":
        scene["beats"][0].update(visible_ids=["missing"], focus_id="missing", actions=[])
    elif change == "action":
        scene["beats"][0]["actions"][0]["kind"] = "ride"
    elif change == "asset":
        scene["objects"][0]["asset_id"] = "actor.missing"
    elif change == "parameters":
        scene["objects"][0]["parameters"] = {"svg": "<svg/>"}
    elif change == "source":
        script["segments"][0]["source_ids"] = ["invented"]
    elif change == "quote":
        scene["beats"][0]["anchor"]["quote"] = "原文没有的句子"
    elif change == "order":
        scene["beats"][1]["anchor"]["occurrence"] = 7
    elif change == "unused":
        scene["objects"].append({**scene["objects"][0], "id": "unused"})
    elif change == "sfx":
        scene["beats"][0]["sfx"]["asset_id"] = "sfx.missing"
    elif change == "scene_binding":
        scene["segment_id"] = "other"
    elif change == "duplicate_scene":
        plan["scenes"][1]["scene_id"] = scene["scene_id"]
    elif change == "no_change":
        scene["beats"][1]["actions"] = []
    else:
        scene["beats"][0]["actions"][0]["kind"] = "exit"
    with pytest.raises(DirectorValidationError) as failure:
        validate_director(plan, script, resources, research)
    assert failure.value.errors[0]["code"] == code


@pytest.mark.parametrize("change", ["offstage", "nan", "zoom", "many_groups", "keyword", "duplicate_target"])
def test_director_limits_are_strict_and_layout_bounded(production_data, change):
    script, plan, resources, research, _, _ = production_data
    scene = plan["scenes"][0]
    beat = scene["beats"][0]
    if change == "offstage":
        scene["objects"][0]["y"] = .95
    elif change == "nan":
        scene["objects"][0]["x"] = float("nan")
    elif change == "zoom":
        beat["camera"]["zoom"] = 2
    elif change == "many_groups":
        beat["visible_ids"] = ["traveler", "a", "b", "c"]
    elif change == "keyword":
        beat["keywords"] = ["长" * 11]
    else:
        beat["actions"].append(copy.deepcopy(beat["actions"][0]))
    with pytest.raises(DirectorValidationError):
        validate_director(plan, script, resources, research)


def test_compile_uses_observed_quote_times_and_persistent_motion_state(production_data):
    scenes = compiled(production_data)
    scene = scenes[0]
    assert scene["beats"][0]["start"] == 0
    assert scene["beats"][0]["anchor_time"] == pytest.approx(.15)
    assert scene["beats"][0]["actions"][0]["start"] == pytest.approx(.15)
    assert scene["beats"][1]["start"] == pytest.approx(3.35)
    assert scene["beats"][1]["actions"][0]["from"]["x"] == .3
    assert scene["beats"][1]["actions"][0]["to"]["x"] == .4
    assert scene["duration"] == pytest.approx(13.2)
    assert scene["captions"][0]["start"] == pytest.approx(.15)
    assert all(len(caption["text"].replace("\n", "")) <= 24 and len(caption["text"].splitlines()) <= 2
               for caption in scene["captions"])
    assert "evidence_text" not in scene["sources"][0]
    assert production_data[1]["scenes"][0]["objects"][0]["x"] == .2
    checks = validate_film_timeline(scenes, 1.15, .3)
    assert checks["semantic_gap_within_limit"] and checks["sfx_density_within_limit"]


def test_anchor_end_and_path_state_use_real_word_end(production_data):
    script, plan, resources, research, words, speech = production_data
    scene = plan["scenes"][0]
    scene["beats"][0]["anchor"]["edge"] = "end"
    scene["beats"][0]["actions"][0] = {"target_id": "traveler", "kind": "walk",
                                      "path": [{"x": .3, "y": .7}, {"x": .4, "y": .6}]}
    actual = compile_scene(scene, script["segments"][0], words, speech, resources, research["sources"])
    assert actual["beats"][0]["anchor_time"] == pytest.approx(.47)
    assert actual["beats"][0]["actions"][0]["start"] == pytest.approx(.47)
    assert actual["beats"][0]["actions"][0]["path"][0] == {"x": .2, "y": .7}
    assert actual["beats"][1]["actions"][0]["from"] == {"x": .4, "y": .6, "scale": 1}


@pytest.mark.parametrize("kind,asset_id", [
    ("walk", "actor.person"), ("open", "prop.gate"), ("enter", "actor.person"), ("stamp", "prop.seal"),
])
def test_late_first_speech_anchor_does_not_start_key_action_with_background(production_data, kind, asset_id):
    script, plan, resources, research, words, speech = production_data
    scene = plan["scenes"][0]
    scene["objects"][0]["asset_id"] = asset_id
    for beat in scene["beats"]:
        beat["actions"] = [{"target_id": "traveler", "kind": "emphasize"}]
    scene["beats"][0]["anchor"]["occurrence"] = 2
    scene["beats"][0]["actions"][0]["kind"] = kind
    actual = compile_scene(scene, script["segments"][0], words, speech, resources, research["sources"])
    first = actual["beats"][0]
    assert first["start"] == 0
    assert first["anchor_time"] == pytest.approx(1.75)
    assert first["actions"][0]["start"] == first["anchor_time"]
    assert first["actions"][0]["end"] == first["end"]
    assert first["actions"][0]["end"] - first["actions"][0]["start"] >= 1 / actual["fps"]


@pytest.mark.parametrize("window", [0, .01])
def test_late_action_with_less_than_one_frame_fails_explicitly(production_data, window):
    script, plan, resources, research, words, speech = production_data
    scene = plan["scenes"][0]
    scene["beats"][0]["anchor"] = {"quote": "癸", "occurrence": 2, "edge": "start"}
    words[19]["start"] = words[20]["start"] - window
    words[19]["end"] = words[19]["start"] + max(window, .01)
    with pytest.raises(DirectorValidationError) as failure:
        compile_scene(scene, script["segments"][0], words, speech, resources, research["sources"])
    assert failure.value.errors[0]["code"] == "action_window_too_short"


@pytest.mark.parametrize("change,code", [
    ("missing", "missing_alignment"), ("text", "invalid_character_alignment"),
    ("offset", "invalid_character_alignment"), ("timing", "invalid_word_timing"),
    ("hole", "incomplete_alignment"), ("same_time", "anchor_order"),
])
def test_no_estimated_timing_fallback(production_data, change, code):
    script, plan, resources, research, words, speech = production_data
    if change == "missing":
        words = []
    elif change == "text":
        words[0]["text"] = "不符"
    elif change == "offset":
        words[1]["char_start"] = 0
    elif change == "timing":
        words[1]["start"] = 0
    elif change == "hole":
        words = words[1:]
    else:
        plan["scenes"][0]["beats"][1]["anchor"] = copy.deepcopy(plan["scenes"][0]["beats"][0]["anchor"])
        # The first beat starts at zero, so make both later anchors resolve alike.
        plan["scenes"][0]["beats"][2]["anchor"] = copy.deepcopy(plan["scenes"][0]["beats"][0]["anchor"])
    with pytest.raises(DirectorValidationError) as failure:
        compile_scene(plan["scenes"][0], script["segments"][0], words, speech, resources, research["sources"])
    assert failure.value.errors[0]["code"] == code


def test_film_limits_use_measured_post_speed_time(production_data):
    scenes = compiled(production_data)
    for scene in scenes:
        for beat in scene["beats"]:
            beat["sfx"] = None
    with pytest.raises(DirectorValidationError) as failure:
        validate_film_timeline(scenes, 1.15, .3)
    assert failure.value.errors[0]["code"] == "sfx_density"
    assert failure.value.checks["sfx_count"] == 0
    scenes = compiled(production_data)
    scenes[0]["beats"][0]["end"] = 5
    scenes[0]["beats"][1]["start"] = 5
    scenes[0]["beats"][1]["anchor_time"] = 5
    with pytest.raises(DirectorValidationError) as failure:
        validate_film_timeline(scenes, 1.15, .3)
    assert any(error["code"] == "semantic_gap" for error in failure.value.errors)


@pytest.mark.parametrize("durations,fps,transition,overlap", [
    ([.6, 2.4], 24, .31, 4 / 24),
    ([3, 3], 30, .317, .3),
])
def test_film_clock_clamps_and_quantizes_overlap(durations, fps, transition, overlap):
    scenes = [{"protocol": "history-director-v2", "scene_id": f"s{index}", "duration": duration,
               "fps": fps, "beats": [{"id": "b", "start": 0, "end": duration, "sfx": None}]}
              for index, duration in enumerate(durations)]
    with pytest.raises(DirectorValidationError) as failure:
        validate_film_timeline(scenes, 1.15, transition)
    assert failure.value.errors[0]["code"] == "sfx_density"
    measured = failure.value.checks
    assert measured["overlaps"] == pytest.approx([overlap])
    assert measured["scene_starts"] == pytest.approx([0, durations[0] - overlap])
    assert measured["duration"] == pytest.approx((sum(durations) - overlap) / 1.15, abs=1e-6)


def test_map_requires_current_two_endpoints_with_evidence(production_data):
    script, plan, resources, research, _, _ = production_data
    scene = plan["scenes"][0]
    points = [{"id": "a", "name": "甲地", "lon": 60, "lat": 30},
              {"id": "b", "name": "乙地", "lon": 70, "lat": 35}]
    research["geography"] = {"records": copy.deepcopy(points)}
    scene["objects"][0].update(asset_id="info.map", parameters={"locations": points, "routes": [],
                                                              "source_ids": ["evidence_1"]})
    for beat in scene["beats"]:
        beat["actions"] = [{"target_id": "traveler", "kind": "draw"}]
    validate_director(plan, script, resources, research)
    scene["objects"][0]["parameters"]["locations"][0]["lon"] = 61
    with pytest.raises(DirectorValidationError, match="unverified_coordinate"):
        validate_director(plan, script, resources, research)


async def test_generation_uses_only_current_context_and_configured_gateway(production_data):
    script, plan, resources, research, _, _ = production_data
    resources["intent_candidates"] = [{"segment_id": "segment_0", "intent": "测试意图0",
                                        "environment_ids": ["road"], "visual_ids": ["actor.person"],
                                        "sfx_ids": ["sfx.footstep"]}]
    resources["visual_assets"][0].update(intents=["行进"], conditions=["有路线资料"],
                                         combination_example={"with": ["prop.flag"]})
    calls = []

    class Gateway:
        async def generate_json(self, system, prompt):
            payload = json.loads(prompt)
            calls.append((self.stage, payload))
            assert "evidence_text" not in payload["research"]["sources"][0]
            assert "old_storyboard" not in payload["research"]
            if self.stage != "teaching":
                assert payload["resources"]["intent_candidates"] == resources["intent_candidates"]
                assert payload["resources"]["visual_assets"][0]["conditions"] == ["有路线资料"]
            return copy.deepcopy(script if self.stage == "teaching" else plan)

    gateway = Gateway()
    generated = await generate_script({"topic": "通用历史现象"}, research, gateway)
    directed = await generate_director(generated, research, resources, gateway)
    repaired = await repair_director(generated, research, resources, directed,
                                     [{"code": "test", "path": "", "message": "isolated repair"}], gateway)
    assert [stage for stage, _ in calls] == ["teaching", "director", "director_repair"]
    assert calls[2][1]["script"] == generated.model_dump(mode="json")
    assert repaired == directed


async def test_failed_model_plan_is_preserved_for_bounded_caller_repair(production_data):
    script, plan, resources, research, _, _ = production_data
    plan["scenes"][0]["environment"] = "unknown"

    class Gateway:
        async def generate_json(self, *_):
            return plan

    with pytest.raises(DirectorValidationError) as failure:
        await generate_director(script, research, resources, Gateway())
    assert failure.value.prior_plan == plan
    assert failure.value.prior_plan is not plan
