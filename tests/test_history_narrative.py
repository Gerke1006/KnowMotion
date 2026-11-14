"""Mechanical evidence and subtitle behavior, using only generic isolated prose."""
import copy

import pytest

from harness.history_director import AlignedWord, DirectorValidationError, _captions, validate_director
from harness.history_narrative import _contains, validate_narrative_bindings, validate_narrative_diversity


def caption_words(text, chunks=None, *, step=.12):
    chunks = chunks or list(text)
    cursor, result = 0, []
    for chunk in chunks:
        result.append(AlignedWord(text=chunk, char_start=cursor, char_end=cursor + len(chunk),
                                  start=cursor * step, end=(cursor + len(chunk)) * step))
        cursor += len(chunk)
    assert cursor == len(text)
    return result


def pages(text, chunks=None):
    return _captions(text, caption_words(text, chunks), 0, .15, len(text) * .12 + .4)


def test_short_complete_sentences_remain_single_line_and_never_merge():
    text = "工匠整理文书，随后交给使者。使者继续前往城门。"
    result = pages(text)
    assert [page["text"] for page in result] == ["工匠整理文书，随后交给使者。", "使者继续前往城门。"]
    assert all("\n" not in page["text"] for page in result)
    assert result[0]["end"] == result[1]["start"]
    assert "".join(page["text"] for page in result) == text


def test_long_sentence_prefers_clause_boundaries_without_splitting_observed_words():
    chunks = ["工匠", "先把", "散落的", "文书", "重新", "整理", "清楚", "，", "然后", "交给", "准备出发的", "使者", "，",
              "使者", "把", "文书", "收好", "。"]
    text = "".join(chunks)
    result = pages(text, chunks)
    boundaries = {word.char_end for word in caption_words(text, chunks)}
    assert len(result) > 1
    assert result[0]["text"].endswith("，")
    assert "".join(page["text"] for page in result) == text
    assert all(page["char_end"] in boundaries and len(page["text"]) <= 24 for page in result)
    assert all(page["text"] not in "，。！？" for page in result)


def test_punctuation_only_alignment_tokens_stay_with_their_sentence():
    text = "“使者来了！”工匠收起文书。"
    result = pages(text, ["“", "使者", "来了", "！", "”", "工匠", "收起", "文书", "。"])
    assert [page["text"] for page in result] == ["“使者来了！”", "工匠收起文书。"]
    assert all(result[index]["end"] <= result[index + 1]["start"] for index in range(len(result) - 1))


def test_decimal_and_clock_punctuation_do_not_create_fake_sentence_boundaries():
    text = "记录写着3.5里，另记12:30。后来继续。"
    result = pages(text)
    assert [page["text"] for page in result] == ["记录写着3.5里，另记12:30。", "后来继续。"]


def test_caption_overlap_is_clipped_at_observed_next_word_and_long_pause_remains():
    text = "使者到达。工匠等候。"
    words = caption_words(text, ["使者", "到达", "。", "工匠", "等候", "。"])
    words[2].end = words[3].start + .02
    result = _captions(text, words, 0, 0, 3)
    assert result[0]["end"] == result[1]["start"]
    for word in words[3:]:
        word.start += 1
        word.end += 1
    delayed = _captions(text, words, 0, 0, 4)
    assert delayed[0]["end"] < delayed[1]["start"] - .35


def test_coarse_token_cannot_be_split_with_invented_timing():
    with pytest.raises(DirectorValidationError, match="alignment_token_too_long"):
        pages("工" * 25, ["工" * 25])
    with pytest.raises(DirectorValidationError, match="alignment_crosses_sentence"):
        pages("使者到达。工匠等候。", ["使者到达。工匠等候。"])


def test_character_alignment_preserves_model_selected_names_without_estimated_time():
    text = "甲" * 23 + "欧阳明继续前行。"
    result = _captions(text, caption_words(text), 0, .15, len(text) * .12 + .4, ["欧阳明"])
    assert result[0]["text"] == "甲" * 23
    assert result[1]["text"].startswith("欧阳明")
    assert result[1]["start"] == pytest.approx(.15 + 23 * .12)
    assert "".join(page["text"] for page in result) == text


@pytest.fixture
def narrative():
    text = "使者甲来到甲城，准备交接文书。他随后递出文书。公元前一百三十八年，使者启程。后来前往乙城。"
    segment = {"id": "segment", "narration": text, "source_ids": ["source"], "intent": "隔离测试"}
    objects = [{"id": "envoy", "asset_id": "actor.envoy", "label": "使者甲", "parameters": {},
                "evidence_quote": "使者甲"},
               {"id": "document", "asset_id": "prop.document", "label": "文书", "parameters": {},
                "evidence_quote": "文书"}]
    scene = {"scene_id": "scene", "segment_id": "segment", "environment": "interior", "objects": objects,
             "beats": [
                 {"id": "a", "anchor": {"quote": "准备", "occurrence": 1}, "visible_ids": ["envoy", "document"],
                  "keywords": ["交接文书"], "actions": [{"target_id": "document", "kind": "handover"}],
                  "evidence_quote": "使者甲来到甲城，准备交接文书。"},
                 {"id": "b", "anchor": {"quote": "随后", "occurrence": 1}, "visible_ids": ["envoy", "document"],
                  "keywords": ["递出文书"], "actions": [{"target_id": "document", "kind": "handover"}],
                  "evidence_quote": "他随后递出文书。", "evidence_by_object": {"envoy": "他"}},
             ]}
    resources = {"visual_assets": [{"id": "actor.envoy", "narrative_terms": ["使者", "他"]},
                                   {"id": "prop.document", "narrative_terms": ["文书"]}]}
    return scene, segment, resources


def test_known_person_identity_survives_explicit_current_pronoun(narrative):
    scene, segment, resources = narrative
    original = copy.deepcopy(scene)
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True)
    assert report["passed"] and not report["errors"]
    assert report["beats"][1]["visible_objects"][0]["current_evidence_quote"] == "他"
    assert report["beats"][1]["visible_objects"][0]["visible_text"][0]["scope"] == "known_identity"
    assert "not proof" in report["limitation"]
    assert scene == original


@pytest.fixture
def continued_narrative():
    segment = {"id": "continued", "narration": "他继续前行，沿原路走出城门。"}
    scene = {"scene_id": "continued_scene", "segment_id": "continued", "environment": "road",
             "objects": [
                 {"id": "envoy", "asset_id": "actor.envoy", "label": "使者甲", "parameters": {},
                  "evidence_quote": "使者甲"},
                 {"id": "route", "asset_id": "info.map", "label": "", "evidence_quote": "甲城",
                  "parameters": {"locations": [{"id": "city", "name": "甲城"}], "routes": []}},
             ],
             "beats": [{"id": "continued_beat", "anchor": {"quote": "继续", "occurrence": 1},
                        "visible_ids": ["envoy", "route"], "keywords": ["前行"], "actions": [],
                        "evidence_quote": segment["narration"],
                        "evidence_by_object": {"envoy": "他", "route": "原路"}}]}
    return scene, segment, {"visual_assets": []}, "使者甲抵达甲城。"


def test_known_person_and_map_identity_survive_prior_segments(continued_narrative):
    scene, segment, resources, prior = continued_narrative
    original = copy.deepcopy((scene, segment))
    without_prior = validate_narrative_bindings(scene, segment, resources, require_bindings=True)
    assert not without_prior["passed"]
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True, prior_narration=prior)
    assert report["passed"], report["errors"]
    assert report["prior_narration_char_count"] == len(prior)
    assert all(row["current_quote_matched"] for row in report["beats"][0]["visible_objects"])
    assert (scene, segment) == original


@pytest.mark.parametrize("change,code", [
    ("unmentioned_person", "visible_text_not_narrated"),
    ("unmentioned_place", "visible_text_not_narrated"),
    ("future_initial_quote", "future_object_evidence"),
    ("old_object_quote", "object_evidence_not_current"),
    ("old_beat_quote", "beat_evidence_not_current"),
    ("old_keyword", "keyword_not_current"),
])
def test_prior_segments_do_not_supply_current_or_future_information(continued_narrative, change, code):
    scene, segment, resources, prior = continued_narrative
    if change == "unmentioned_person":
        scene["objects"][0]["label"] = "人物乙"
    elif change == "unmentioned_place":
        scene["objects"][1]["parameters"]["locations"][0]["name"] = "乙城"
    elif change == "future_initial_quote":
        scene["objects"][0]["evidence_quote"] = "稍后才出现的人物乙"
    elif change == "old_object_quote":
        scene["beats"][0]["evidence_by_object"].pop("envoy")
    elif change == "old_beat_quote":
        scene["beats"][0]["evidence_quote"] = prior
    else:
        scene["beats"][0]["keywords"] = ["甲城"]
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True, prior_narration=prior)
    assert code in {error["code"] for error in report["errors"]}


def test_prior_event_and_date_still_require_current_sentence(continued_narrative):
    scene, segment, resources, prior = continued_narrative
    scene["objects"].append({"id": "date", "asset_id": "info.timeline", "label": "使者启程",
                             "evidence_quote": "使者启程", "parameters": {
                                 "label": "使者启程", "date_label": "公元前138年", "year": -138}})
    scene["beats"][0]["visible_ids"].append("date")
    scene["beats"][0]["evidence_by_object"]["date"] = "前行"
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True,
                                         prior_narration=prior + "公元前一百三十八年，使者启程。")
    assert {error["path"].split(".objects.date.")[-1] for error in report["errors"]} == {
        "label", "parameters.label", "parameters.date_label"}


@pytest.mark.parametrize("label,role,expected_fields", [
    ("人物甲", "旧官职", {"parameters.role"}),
    ("人物甲曾任旧官职", "旧官职", {"label", "parameters.role"}),
    ("人物甲", "新官职", set()),
])
def test_portrait_identity_does_not_carry_prior_office_or_event_labels(label, role, expected_fields):
    segment = {"id": "continued", "narration": "他此时担任新官职。"}
    scene = {"scene_id": "continued_scene", "segment_id": "continued", "environment": "interior",
             "objects": [{"id": "portrait", "asset_id": "info.portrait", "label": label,
                          "parameters": {"name": "人物甲", "role": role}, "evidence_quote": "人物甲"}],
             "beats": [{"id": "b", "anchor": {"quote": "此时", "occurrence": 1},
                        "visible_ids": ["portrait"], "keywords": [], "actions": [],
                        "evidence_quote": segment["narration"], "evidence_by_object": {"portrait": "他"}}]}
    report = validate_narrative_bindings(scene, segment, {}, require_bindings=True,
                                         prior_narration="人物甲曾任旧官职。")
    assert {error["path"].split(".objects.portrait.")[-1] for error in report["errors"]} == expected_fields


@pytest.mark.parametrize("prior", ["使者\n甲", "使者"])
def test_known_identity_is_not_fabricated_by_joining_segment_boundaries(continued_narrative, prior):
    scene, segment, resources, _ = continued_narrative
    segment["narration"] = "甲，他继续前行，沿原路走出城门。"
    scene["beats"][0]["evidence_quote"] = segment["narration"]
    scene["objects"][0]["evidence_quote"] = "他"
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True, prior_narration=prior)
    assert any(error["code"] == "visible_text_not_narrated" and error["path"].endswith("envoy.label")
               for error in report["errors"])


@pytest.mark.parametrize("change,code", [
    ("future_name", "visible_text_not_narrated"), ("future_object", "future_object_evidence"),
    ("future_keyword", "keyword_not_current"), ("cross_sentence", "beat_evidence_not_current"),
    ("wrong_quote", "object_evidence_not_current"), ("missing_quote", "missing_beat_evidence"),
    ("hidden_override", "evidence_for_invisible_object"),
])
def test_future_or_unsupported_visible_information_is_reported(narrative, change, code):
    scene, segment, resources = narrative
    if change == "future_name":
        scene["objects"][0]["label"] = "乙城"
    elif change == "future_object":
        scene["objects"][0]["evidence_quote"] = "乙城"
    elif change == "future_keyword":
        scene["beats"][0]["keywords"] = ["乙城"]
    elif change == "cross_sentence":
        scene["beats"][0]["evidence_quote"] = segment["narration"]
    elif change == "wrong_quote":
        scene["beats"][1]["evidence_by_object"]["envoy"] = "使者甲"
    elif change == "missing_quote":
        del scene["beats"][0]["evidence_quote"]
    else:
        scene["beats"][0]["evidence_by_object"] = {"hidden": "文书"}
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True)
    assert not report["passed"]
    assert code in {error["code"] for error in report["errors"]}


def test_numeric_spelling_normalization_never_estimates_dates(narrative):
    scene, segment, resources = narrative
    scene["objects"] = [{"id": "date", "asset_id": "info.timeline", "label": "", "evidence_quote": "公元前一百三十八年",
                         "parameters": {"year": -138, "date_label": "公元前138年", "label": "使者启程"}}]
    scene["beats"] = [{"id": "date_beat", "anchor": {"quote": "一百三十八", "occurrence": 1},
                       "visible_ids": ["date"], "keywords": ["138年"], "actions": [],
                       "evidence_quote": "公元前一百三十八年，使者启程。"}]
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True)
    assert report["passed"], report["errors"]
    scene["beats"][0]["keywords"] = ["38年"]
    assert not validate_narrative_bindings(scene, segment, resources, require_bindings=True)["passed"]
    scene["beats"][0]["keywords"] = []
    scene["objects"][0]["parameters"]["date_label"] = "约公元前2世纪"
    assert not validate_narrative_bindings(scene, segment, resources, require_bindings=True)["passed"]


def test_resource_lexical_hints_are_diagnostics_not_semantic_judgments(narrative):
    scene, segment, resources = narrative
    resources["visual_assets"][0]["narrative_terms"] = ["远行"]
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True)
    assert report["passed"]
    assert report["warnings"][0]["code"] == "resource_terms_not_found"


@pytest.mark.parametrize("source,label", [("13.8年", "138年"), ("-138年", "138年"), ("138年", "38年")])
def test_numeric_normalization_preserves_sign_decimal_and_whole_numbers(source, label):
    assert not _contains(source, label, numeric=True)


def test_quoted_sentence_evidence_includes_its_closing_quote(narrative):
    scene, segment, resources = narrative
    segment["narration"] = "工匠说：“使者来了。”他随后离开。"
    scene["objects"] = [{"id": "envoy", "asset_id": "actor.envoy", "label": "使者", "parameters": {},
                         "evidence_quote": "使者"}]
    scene["beats"] = [{"id": "quoted", "anchor": {"quote": "来了", "occurrence": 1}, "visible_ids": ["envoy"],
                       "keywords": [], "actions": [], "evidence_quote": "使者来了。”"}]
    report = validate_narrative_bindings(scene, segment, resources, require_bindings=True)
    assert report["passed"], report["errors"]
    assert report["beats"][0]["sentence"].endswith("。”")


def test_legacy_quotes_are_optional_and_repetition_has_no_forced_quota(narrative):
    scene, segment, resources = narrative
    for obj in scene["objects"]:
        obj.pop("evidence_quote", None)
    for beat in scene["beats"]:
        beat.pop("evidence_quote", None)
        beat.pop("evidence_by_object", None)
    report = validate_narrative_bindings(scene, segment, resources)
    assert report["passed"] and report["legacy_unbound"]
    copies = [copy.deepcopy(scene) for _ in range(3)]
    for index, item in enumerate(copies):
        item["scene_id"] = f"scene_{index}"
    diversity = validate_narrative_diversity(copies, resources)
    assert diversity["passed"] and not diversity["enforced_quota"]
    assert diversity["unique_combinations"] == 1
    assert {item["code"] for item in diversity["diagnostics"]} >= {
        "adjacent_repeated_composition", "repeated_scene_background"}


def test_strict_binding_collects_errors_from_every_scene():
    narration = "甲乙丙丁戊己庚辛壬癸" * 8
    script = {"title": "隔离测试", "segments": [{"id": f"seg{i}", "narration": narration,
               "source_ids": ["source"], "intent": "测试"} for i in range(5)]}
    scenes = [{"scene_id": f"s{i}", "segment_id": f"seg{i}", "environment": "road",
               "objects": [{"id": "p", "asset_id": "actor.person", "x": .5, "y": .7, "parameters": {}}],
               "beats": [{"id": "b1", "anchor": {"quote": "甲", "occurrence": 1}, "visible_ids": ["p"],
                          "focus_id": "p", "actions": [{"target_id": "p", "kind": "gesture"}]},
                         {"id": "b2", "anchor": {"quote": "甲", "occurrence": 2}, "visible_ids": ["p"],
                          "focus_id": "p", "actions": [{"target_id": "p", "kind": "gesture"}]}]} for i in range(5)]
    plan = {"schema_version": "2.0", "style_id": "gufeng", "scenes": scenes}
    resources = {"environments": [{"id": "road"}], "visual_assets": [{"id": "actor.person", "actions": ["gesture"]}],
                 "sfx_assets": []}
    with pytest.raises(DirectorValidationError) as failure:
        validate_director(plan, script, resources, {"sources": [{"id": "source"}]}, require_narrative_bindings=True)
    assert {error["path"].split(".")[1] for error in failure.value.errors} == {"s0", "s1", "s2", "s3", "s4"}
