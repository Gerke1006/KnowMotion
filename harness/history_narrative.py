"""Mechanical narration/visual evidence reports; never a model or semantic score.

Exact quotes and a small numeric normalization establish text provenance. They
cannot prove that a visual is historically correct or that a quote entails it.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections import Counter


GENERIC_NOTICES = {
    "示意", "示意图", "人物示意", "人物符号示意", "路线示意", "交流示意", "代码示意",
    "现代近似定位", "地点为近似定位", "地图示意", "后世作品", "非生前真容",
}
_DIGITS = dict(zip("零〇一二三四五六七八九", [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
_DIGITS["两"] = 2
_UNITS = {"十": 10, "百": 100, "千": 1000}
_NUMERAL = r"[零〇一二两三四五六七八九十百千]+"


def _data(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else copy.deepcopy(value)


def _numeric_integer(text):
    if not any(char in _UNITS for char in text):
        return "".join(str(_DIGITS[char]) for char in text)
    total, digit, previous_unit, digit_count = 0, None, 10000, 0
    for char in text:
        if char in _DIGITS:
            digit = _DIGITS[char]
            digit_count += 1
            if digit_count > 1 and text != "零":
                return text  # Do not guess malformed mixed numerals.
        else:
            unit = _UNITS[char]
            if unit >= previous_unit:
                return text
            total += (digit if digit is not None else 1) * unit
            digit, digit_count, previous_unit = None, 0, unit
        if digit == 0:
            digit_count = 0
    return str(total + (digit or 0))


def _normalize(text, *, numeric=False):
    text = unicodedata.normalize("NFKC", str(text))
    if numeric:
        # Only written counts/dates followed by explicit units (or a wholly
        # numeric label) are normalized. Centuries are never converted to years.
        text = re.sub(_NUMERAL + r"(?=年|月|日|世纪|岁|次|人|个|条|里|公里)",
                      lambda match: _numeric_integer(match[0]), text)
        if re.fullmatch(_NUMERAL, text):
            text = _numeric_integer(text)
    return "".join(char for index, char in enumerate(text)
                   if unicodedata.category(char)[0] not in {"P", "Z", "C"}
                   or (numeric and 0 < index < len(text) - 1
                       and text[index - 1].isdigit() and text[index + 1].isdigit())
                   or (numeric and char in "-+" and index + 1 < len(text) and text[index + 1].isdigit()))


def _historical_label(text):
    # Parenthesized modern positioning is metadata rather than a new ancient name.
    return re.sub(r"[（(][^）)]*[）)]", "", str(text)).strip()


def _contains(context, text, *, numeric=False):
    visible = _normalize(text, numeric=numeric)
    if not visible:
        return False
    if not numeric:
        return visible in _normalize(context)
    before = r"(?<![\d.\-+−])" if visible[0].isdigit() else ""
    after = r"(?![\d.])" if visible[-1].isdigit() else ""
    return re.search(before + re.escape(visible) + after, _normalize(context, numeric=True)) is not None


def _notice(text):
    return _normalize(text) in {_normalize(notice) for notice in GENERIC_NOTICES}


def _occurrences(text, quote):
    if not isinstance(quote, str) or not quote:
        return []
    found, cursor = [], 0
    while (position := text.find(quote, cursor)) >= 0:
        found.append((position, position + len(quote)))
        cursor = position + 1
    return found


def _sentence_ranges(text):
    start, ranges = 0, []
    for index, char in enumerate(text):
        if index < start:
            continue
        boundary = char in "。！？；!?;\n" or (
            char == "." and not (0 < index < len(text) - 1 and text[index - 1].isdigit() and text[index + 1].isdigit()))
        if boundary:
            end = index + 1
            while end < len(text) and text[end] in '”’」』）)]》〉"':
                end += 1
            ranges.append((start, end))
            start = end
    if start < len(text):
        ranges.append((start, len(text)))
    return ranges


def _resource_terms(card, context):
    terms = card.get("narrative_terms", [])
    if isinstance(terms, dict):
        terms = [term for values in terms.values() if isinstance(values, list) for term in values]
    terms = [term for term in terms if isinstance(term, str)] if isinstance(terms, list) else []
    return terms, [term for term in terms if term in context]


def _visible_text(obj):
    """Only fields actually drawn by the trusted resources, with temporal scope."""
    asset, params = obj.get("asset_id", ""), obj.get("parameters", {})
    if obj.get("label"):
        identity = asset.startswith("actor.") or asset == "prop.gate" or (
            asset == "info.portrait" and _normalize(obj["label"]) == _normalize(params.get("name", "")))
        scope = "known_identity" if identity else "current_sentence"
        yield "label", obj["label"], scope, False
    if asset == "info.map":
        for index, point in enumerate(params.get("locations", [])):
            yield f"parameters.locations.{index}.name", _historical_label(point.get("name", "")), "known_identity", False
        for index, route in enumerate(params.get("routes", [])):
            if route.get("label"):
                yield f"parameters.routes.{index}.label", route["label"], "current_sentence", False
    elif asset == "info.timeline":
        for name in ("label", "date_label"):
            if params.get(name):
                yield "parameters." + name, params[name], "current_sentence", True
    elif asset == "info.portrait":
        for name in ("name", "role"):
            if params.get(name):
                scope = "known_identity" if name == "name" else "current_sentence"
                yield "parameters." + name, params[name], scope, False


def validate_narrative_bindings(scene, segment, resources, *, require_bindings=False,
                                prior_narration: str = "") -> dict:
    """Report exact current-sentence evidence and known identities for each beat.

    Missing quotes remain compatible with legacy v2 unless require_bindings is
    set. Explicit quotes are always checked. The caller may turn errors into its
    normal bounded technical repair; warnings never require adding decorations.
    prior_narration must contain only completed earlier script segments, separated
    by newlines. It establishes known identities and initial object provenance;
    it never supplies current beat/object evidence, events, dates or keywords.
    """
    scene, segment = _data(scene), _data(segment)
    narration = segment.get("narration", "")
    prior_contexts = prior_narration.splitlines()
    objects = {obj["id"]: obj for obj in scene.get("objects", [])}
    cards = {card["id"]: card for card in resources.get("visual_assets", [])}
    environments = {card["id"]: card for card in resources.get("environments", [])}
    sentences = _sentence_ranges(narration)
    errors, warnings, rows = [], [], []
    active = require_bindings or any(obj.get("evidence_quote") for obj in objects.values()) or any(
        beat.get("evidence_quote") or beat.get("evidence_by_object") for beat in scene.get("beats", []))

    def error(code, path, message):
        errors.append({"code": code, "path": path, "message": message})

    for beat in scene.get("beats", []):
        path = f"scenes.{scene.get('scene_id', '')}.beats.{beat.get('id', '')}"
        anchor = beat.get("anchor", {})
        spans = _occurrences(narration, anchor.get("quote"))
        occurrence = anchor.get("occurrence", 1)
        if not isinstance(occurrence, int) or not 1 <= occurrence <= len(spans):
            error("narrative_anchor_missing", path + ".anchor", "Anchor must identify an exact original narration occurrence")
            continue
        anchor_span = spans[occurrence - 1]
        sentence_span = next(((left, right) for left, right in sentences
                              if left <= anchor_span[0] < right and anchor_span[1] <= right), None)
        if sentence_span is None:
            error("narrative_anchor_crosses_sentence", path + ".anchor", "A beat anchor must stay inside one original sentence")
            continue
        left, right = sentence_span
        current, prefix = narration[left:right], narration[:right]
        known_contexts = [*prior_contexts, prefix]
        quote = beat.get("evidence_quote")
        quote_spans = [span for span in _occurrences(narration, quote)
                       if left <= span[0] <= anchor_span[0] and anchor_span[1] <= span[1] <= right]
        if quote and not quote_spans:
            error("beat_evidence_not_current", path + ".evidence_quote", "Beat evidence must be verbatim, contain its anchor and stay in the same sentence")
        elif require_bindings and not quote:
            error("missing_beat_evidence", path + ".evidence_quote", "New production requires a current original sentence quote")
        context = quote if quote_spans else current
        environment_terms, matched_environment_terms = _resource_terms(
            environments.get(scene.get("environment"), {}), context)
        if active and environment_terms and not matched_environment_terms:
            warnings.append({"code": "environment_terms_not_found", "path": path + ".environment",
                             "message": "The current sentence lacks this setting's lexical hints; verify that the background is appropriate"})
        overrides = beat.get("evidence_by_object", {})
        if set(overrides) - set(beat.get("visible_ids", [])):
            error("evidence_for_invisible_object", path + ".evidence_by_object", "Object evidence may only name this beat's visible IDs")
        object_rows = []
        for object_id in beat.get("visible_ids", []):
            obj = objects.get(object_id)
            if obj is None:
                error("unknown_visible_object", path + ".visible_ids", "Visible object must be declared in this scene")
                continue
            initial = obj.get("evidence_quote")
            evidence = overrides.get(object_id) or initial
            object_path = path + ".objects." + object_id
            if initial and not any(initial in earlier for earlier in known_contexts):
                error("future_object_evidence", object_path + ".evidence_quote", "Initial object evidence must already be narrated or belong to the current sentence")
            elif require_bindings and not initial:
                error("missing_object_evidence", object_path + ".evidence_quote", "New production requires an original object evidence quote")
            if evidence and evidence not in context:
                error("object_evidence_not_current", object_path, "Use this sentence's exact object quote; override evidence for a later pronoun when needed")
            elif require_bindings and not evidence:
                error("missing_current_object_evidence", object_path, "Every currently visible object requires current quote evidence")
            text_rows = []
            if active:
                for field, text, scope, numeric in _visible_text(obj):
                    exempt = _notice(text)
                    text_contexts = known_contexts if scope == "known_identity" else [current]
                    matched = exempt or any(_contains(earlier, text, numeric=numeric) for earlier in text_contexts)
                    text_rows.append({"field": field, "text": text, "scope": scope, "matched": matched,
                                      "generic_notice": exempt})
                    if not matched:
                        error("visible_text_not_narrated", object_path + "." + field,
                              "Visible identity must be known; event text and dates must occur in the current narrated sentence")
            terms, supported = _resource_terms(cards.get(obj.get("asset_id"), {}), context)
            if active and terms and not supported:
                warnings.append({"code": "resource_terms_not_found", "path": object_path,
                                 "message": "The resource's lexical hints are absent; this is a diagnostic, not a semantic rejection"})
            object_rows.append({"object_id": object_id, "asset_id": obj.get("asset_id"),
                                "initial_evidence_quote": initial, "current_evidence_quote": evidence,
                                "current_quote_matched": bool(evidence and evidence in context),
                                "visible_text": text_rows, "matched_resource_terms": supported})
        keyword_rows = []
        for index, text in enumerate(beat.get("keywords", [])):
            matched = _notice(text) or _contains(current, text, numeric=True)
            keyword_rows.append({"text": text, "matched": matched})
            if active and not matched:
                error("keyword_not_current", path + f".keywords.{index}", "A visible keyword must occur in this narrated sentence")
        rows.append({"beat_id": beat.get("id"), "anchor_span": list(anchor_span), "sentence_span": [left, right],
                     "environment": scene.get("environment"), "matched_environment_terms": matched_environment_terms,
                     "sentence": current, "evidence_quote": quote, "evidence_matched": bool(quote_spans),
                     "visible_objects": object_rows, "keywords": keyword_rows})
    return {"scene_id": scene.get("scene_id"), "segment_id": segment.get("id"), "passed": not errors,
            "required": require_bindings, "legacy_unbound": not active, "beats": rows,
            "prior_narration_char_count": len(prior_narration),
            "errors": errors, "warnings": warnings,
            "limitation": "Mechanical quote/text provenance only; not proof of semantic entailment or historical correctness."}


def narrative_caption_phrases(scene) -> list[str]:
    """Keep model-selected short names/labels intact when alignment is character-level."""
    scene = _data(scene)
    phrases = [text for obj in scene.get("objects", []) for _, text, _, _ in _visible_text(obj)]
    phrases += [text for beat in scene.get("beats", []) for text in beat.get("keywords", [])]
    return sorted({text for text in phrases if isinstance(text, str) and 1 < len(text) <= 24})


def validate_narrative_diversity(scenes, resources=None) -> dict:
    """Describe actual visible combinations; repetition is diagnostic, never a quota."""
    scenes = [_data(scene) for scene in scenes]
    rows, diagnostics, assets, actions, environments = [], [], Counter(), Counter(), Counter()
    previous, run, longest = None, 0, 0
    for scene in scenes:
        objects = {obj["id"]: obj for obj in scene.get("objects", [])}
        environment = scene.get("environment", "")
        environments[environment] += 1
        for beat in scene.get("beats", []):
            visible = [objects[obj_id] for obj_id in beat.get("visible_ids", []) if obj_id in objects]
            visible_assets = sorted(obj.get("asset_id", "") for obj in visible)
            active_actions = sorted(f"{objects[action['target_id']].get('asset_id', '')}:{action.get('kind', '')}"
                                    for action in beat.get("actions", []) if action.get("target_id") in objects)
            signature = json.dumps([environment, visible_assets, active_actions], ensure_ascii=False)
            run = run + 1 if signature == previous else 1
            longest = max(longest, run)
            if signature == previous:
                diagnostics.append({"code": "adjacent_repeated_composition", "scene_id": scene.get("scene_id"),
                                    "beat_id": beat.get("id"), "message": "Same visible resource/action/background combination; retain if the narrated action continues, otherwise simplify or choose a relevant alternative"})
            previous = signature
            identical = Counter(json.dumps([obj.get("asset_id"), obj.get("label", ""), obj.get("parameters", {})],
                                           ensure_ascii=False, sort_keys=True) for obj in visible)
            if any(count > 1 for count in identical.values()):
                diagnostics.append({"code": "duplicate_visible_groups", "scene_id": scene.get("scene_id"),
                                    "beat_id": beat.get("id"), "message": "Identical visible groups may be redundant; verify that the narration needs multiple instances"})
            assets.update(visible_assets)
            actions.update(action.get("kind", "") for action in beat.get("actions", []))
            rows.append({"scene_id": scene.get("scene_id"), "beat_id": beat.get("id"),
                         "environment": environment, "visible_assets": visible_assets,
                         "actions": active_actions, "signature": signature})
    background_run, last_environment = 0, None
    for scene in scenes:
        environment = scene.get("environment")
        background_run = background_run + 1 if environment == last_environment else 1
        if background_run == 3:
            diagnostics.append({"code": "repeated_scene_background", "scene_id": scene.get("scene_id"),
                                "message": "Three consecutive scenes share a background; change it only when the narrated setting changes"})
        last_environment = environment
    return {"passed": True, "enforced_quota": False, "scene_count": len(scenes), "beat_count": len(rows),
            "unique_combinations": len({row["signature"] for row in rows}), "longest_repeated_run": longest,
            "visible_asset_counts": dict(assets), "action_counts": dict(actions),
            "environment_scene_counts": dict(environments), "beats": rows, "diagnostics": diagnostics}
