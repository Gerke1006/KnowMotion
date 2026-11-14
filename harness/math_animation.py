"""Trusted, narration-anchored mathematical animation data and pure evaluation.

Model output is data. This module never executes expressions, invents speech
timing, or modifies the narration to make an anchor fit.
"""
from __future__ import annotations

import copy
import math
import re
import unicodedata


VERSION = "1.0"
ACTION_KINDS = {"draw", "reveal", "transform"}
EMPHASIS_KINDS = {"pulse", "outline", "focus"}
SFX_IDS = {"sfx.tap", "sfx.drum", "sfx.chime"}
PARTS = {
    "math.derivative_secant": ["axes", "curve", "point_a", "point_b", "secant", "tangent", "delta", "formula"],
    "math.integral_riemann": ["axes", "curve", "bounds", "rectangles", "formula"],
    "math.pythagorean": ["triangle", "square_a", "square_b", "square_c", "label_a", "label_b", "label_c",
                          "equation_a", "equation_b", "result"],
}


class MathAnimationError(ValueError):
    pass


def _data(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else copy.deepcopy(value)


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MathAnimationError(f"{name} must be a finite number")
    return float(value)


def is_math_animation(scene):
    return _data(scene).get("extensions", {}).get("math_animation_version") == VERSION


def tangent_slope(expression, x):
    functions = {"x**2": lambda value: 2*value, "sin(x)": math.cos,
                 "cos(x)": lambda value: -math.sin(value), "x": lambda value: 1.0, "exp(x)": math.exp}
    normalized = re.sub(r"\s+", "", str(expression))
    if normalized not in functions:
        raise MathAnimationError("Exact tangent requires one of the supported five function expressions")
    return functions[normalized](float(x))


def available_parts(kind, parameters=None):
    params = parameters or {}
    if kind in PARTS:
        return list(PARTS[kind])
    if kind == "math.formula":
        return ["formula", *[f"step_{i+1}" for i in range(len(params.get("steps", [])))],
                *[f"label_{i+1}" for i in range(len(params.get("labels", [])))]]
    raise MathAnimationError(f"Unsupported mathematical animation component: {kind}")


def plain_narration(text):
    """Reject notation in spoken captions; never delete operators or alter meaning."""
    if not isinstance(text, str) or not text.strip():
        raise MathAnimationError("Mathematics narration must be nonempty ordinary prose")
    punctuation = set("，。！？；：、,.!?;:'\"“”‘’（）()—…- ")
    for char in text:
        category = unicodedata.category(char)
        if '\u0370' <= char <= '\u03ff':
            raise MathAnimationError("Spell mathematical Greek symbols as ordinary spoken words in narration")
        if (char in punctuation or char.isspace() or category.startswith("L")
                or category == "Nd"):
            continue
        raise MathAnimationError("Narration/subtitles must use spoken prose, not LaTeX, Markdown or mathematical symbols")
    if re.search(r"[A-Za-z\d]\s*[=+*/^_<>-]\s*[A-Za-z\d]", text):
        raise MathAnimationError("Write mathematical operations as spoken words in narration")
    return text


def _quote_span(text, anchor):
    if not isinstance(anchor, dict) or set(anchor) - {"quote", "occurrence", "edge"}:
        raise MathAnimationError("Anchor needs quote, occurrence and start/end edge only")
    quote, occurrence, edge = anchor.get("quote"), anchor.get("occurrence", 1), anchor.get("edge", "start")
    if not isinstance(quote, str) or not quote or type(occurrence) is not int or occurrence < 1 or edge not in {"start", "end"}:
        raise MathAnimationError("Anchor must identify an exact original narration occurrence")
    start = -1
    for _ in range(occurrence):
        start = text.find(quote, start + 1)
        if start < 0:
            raise MathAnimationError("Animation anchor was not found in original narration")
    return start, start + len(quote), edge


def validate_math_scene(scene):
    scene = _data(scene)
    if not is_math_animation(scene):
        return scene
    text = plain_narration(scene.get("narration"))
    components = scene.get("components", [])
    if len(components) != 1:
        raise MathAnimationError("A mathematical animation scene needs exactly one main component")
    component = components[0]
    params = component.get("parameters", {})
    if component.get("id") == "math.derivative_secant":
        tangent_slope(params.get("function", "x**2"),params.get("x0",1))
    for field in ("steps", "labels"):
        items = params.get(field, [])
        if not isinstance(items, list) or len(items) > 8 or any(not isinstance(x, str) or not x.strip() for x in items):
            raise MathAnimationError(f"{field} must contain at most eight nonempty strings")
    parts = set(available_parts(component.get("id"), params))
    nodes = scene.get("animation_sequence", [])
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 48:
        raise MathAnimationError("Mathematical animation needs 1 to 48 narration nodes")
    ids, previous = set(), -1
    for node in nodes:
        if not isinstance(node, dict) or set(node) - {"id", "anchor", "visible_parts", "actions", "motion", "emphasis"}:
            raise MathAnimationError("Unsupported mathematical animation node field")
        identity = node.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity) or identity in ids:
            raise MathAnimationError("Animation node IDs must be unique safe identifiers")
        ids.add(identity)
        left, right, edge = _quote_span(text, node.get("anchor"))
        position = left if edge == "start" else right
        if position <= previous:
            raise MathAnimationError("Animation anchors must advance through narration")
        previous = position
        visible = node.get("visible_parts")
        if not isinstance(visible, list) or any(not isinstance(x, str) for x in visible) or len(set(visible)) != len(visible) or set(visible) - parts:
            raise MathAnimationError("visible_parts must contain unique supported part IDs")
        if component["id"] == "math.formula" and (sum(x.startswith("step_") for x in visible) > 1 or sum(x.startswith("label_") for x in visible) > 1):
            raise MathAnimationError("Show at most one formula step and one explanation label in each node")
        if "tangent" in visible:
            tangent_slope(params.get("function", "x**2"), params.get("x0", 1))
        actions, targets = node.get("actions", []), set()
        if not isinstance(actions, list) or len(actions) > len(parts):
            raise MathAnimationError("actions must be a bounded list")
        for action in actions:
            if not isinstance(action, dict) or set(action) != {"target", "kind"}:
                raise MathAnimationError("Actions contain only target and kind")
            if (not isinstance(action["target"],str) or not isinstance(action["kind"],str)
                    or action["target"] not in visible or action["target"] in targets or action["kind"] not in ACTION_KINDS):
                raise MathAnimationError("Action requires one visible supported target and draw/reveal/transform")
            targets.add(action["target"])
        motion = node.get("motion")
        if motion is not None:
            if not isinstance(motion, dict) or set(motion) != {"parameter", "to"}:
                raise MathAnimationError("motion contains parameter and to")
            value = _number(motion["to"], "motion.to")
            if component["id"] == "math.derivative_secant":
                if motion["parameter"] != "dx" or not 0 < value <= float(params.get("dx_start", 1.5)):
                    raise MathAnimationError("Derivative motion controls positive dx within dx_start")
            elif component["id"] == "math.integral_riemann":
                if motion["parameter"] != "n" or not value.is_integer() or not 1 <= value <= 120:
                    raise MathAnimationError("Integral motion controls an integer n from 1 to 120")
            else:
                raise MathAnimationError("This mathematical component has no numeric motion parameter")
        emphasis = node.get("emphasis")
        if emphasis is not None:
            if (not isinstance(emphasis, dict) or set(emphasis) != {"target", "kind", "sfx_id"}
                    or any(not isinstance(emphasis.get(key),str) for key in ("target","kind","sfx_id"))
                    or emphasis.get("target") not in visible or emphasis.get("kind") not in EMPHASIS_KINDS
                    or emphasis.get("sfx_id") not in SFX_IDS):
                raise MathAnimationError("Emphasis needs a visible target, pulse/outline/focus and approved sound ID")
    return scene


def _words(words, text):
    result, end_char, end_time, covered = [], 0, 0.0, set()
    for word in words:
        start, end = word.get("char_start"), word.get("char_end")
        begin, finish = _number(word.get("start"), "word.start"), _number(word.get("end"), "word.end")
        if (type(start) is not int or type(end) is not int or not end_char <= start < end <= len(text)
                or word.get("text") != text[start:end] or begin < end_time - .03 or finish <= begin):
            raise MathAnimationError("Mathematical captions require observed original-text word spans")
        result.append({**word, "start": begin, "end": finish})
        covered.update(range(start, end))
        end_char, end_time = end, finish
    if not result or any(i not in covered and char.isalnum() for i, char in enumerate(text)):
        raise MathAnimationError("Observed word timestamps must cover the complete narration")
    return result


def _captions(text, words, shift, duration):
    spans, left = [], 0
    while left < len(text):
        stop = min(len(text), left + 24)
        if stop < len(text):
            breaks = [i + 1 for i in range(left + 6, stop) if text[i] in "，。！？；、,! ?;" and not text[i].isspace()]
            if breaks:
                stop = breaks[-1]
            else:
                observed = [word["char_end"] for word in words if left < word["char_end"] <= stop]
                if observed:
                    stop = max(observed)
                else:
                    following = next((word for word in words if word["char_start"] < stop < word["char_end"]),None)
                    if following:
                        # Keep a long Latin word whole; renderer fits its width.
                        stop = following["char_end"]
        crossing = next((word for word in words if word["char_start"] < stop < word["char_end"]),None)
        if crossing:
            stop = crossing["char_start"] if crossing["char_start"] > left else crossing["char_end"]
        # Punctuation belongs to the current spoken phrase rather than its own page.
        while stop < len(text) and text[stop] in "，。！？；：、,.!?;:”" and stop - left < 24:
            stop += 1
        selected = [word for word in words if word["char_start"] < stop and word["char_end"] > left]
        phrase = text[left:stop].strip()
        if selected and phrase:
            start_time = max(0.0, selected[0]["start"] + shift)
            end_time = min(duration, selected[-1]["end"] + shift)
            if end_time > start_time:
                spans.append({"text": phrase, "char_start": left, "char_end": stop,
                              "start": start_time, "end": end_time})
        left = stop
    return spans


def compile_math_scene(scene, words, speech, *, fps=30, narration_offset=.15):
    result = validate_math_scene(scene)
    if not is_math_animation(result):
        return result
    text = result["narration"]
    aligned = _words(words, text)
    duration = _number(result.get("duration"), "scene.duration")
    shift = _number(narration_offset, "narration_offset") - _number(speech.get("trim_start", 0), "trim_start")
    nodes, times = result["animation_sequence"], []
    for node in nodes:
        left, right, edge = _quote_span(text, node["anchor"])
        selected = [word for word in aligned if word["char_start"] < right and word["char_end"] > left]
        if not selected:
            raise MathAnimationError("Animation anchor lacks observed word timing")
        at = (selected[0]["start"] if edge == "start" else selected[-1]["end"]) + shift
        if not -.04 <= at < duration:
            raise MathAnimationError("Animation anchor falls outside the actual voice scene")
        times.append(max(0.0, at))
    if any(b - a < 1 / fps - 1e-8 for a, b in zip(times, [*times[1:], duration])):
        raise MathAnimationError("Distinct mathematical nodes need at least one observed video frame")
    params = result["components"][0]["parameters"]
    values = {"dx": float(params.get("dx_start", 1.5)), "n": float(params.get("n_start", 4))}
    compiled, sounds = [], []
    for index, node in enumerate(nodes):
        at, end = times[index], times[index + 1] if index + 1 < len(times) else duration
        item = {**node, "start": at, "end": end, "values_from": dict(values)}
        if node.get("motion"):
            values[node["motion"]["parameter"]] = float(node["motion"]["to"])
        item["values_to"] = dict(values)
        if node.get("emphasis"):
            if end-at < 2/fps-1e-8:
                raise MathAnimationError("An emphasis node needs at least two observed frames")
            target_action = next((action["kind"] for action in node.get("actions",[]) if action["target"] == node["emphasis"]["target"]),None)
            reveal = .85 if target_action == "draw" else .3 if target_action in {"reveal","transform"} else 0
            peak = min(end-1/fps,at+reveal)
            item["emphasis_time"] = max(at,peak)
            sounds.append({"cue_id": f"{result.get('scene_id', 'scene')}:{node['id']}", "at": item["emphasis_time"],
                           "asset_id": node["emphasis"]["sfx_id"], "align": "peak", "gain_db": 0})
        compiled.append(item)
    result.setdefault("extensions", {})["math_timeline"] = {
        "version": VERSION, "duration": duration, "fps": fps,
        "component_id": result["components"][0]["id"],
        "parts": available_parts(result["components"][0]["id"], params),
        "nodes": compiled, "captions": _captions(text, aligned, shift, duration), "sfx": sounds,
        "timebase": "scene-seconds-before-single-playback-speed-transform",
        "layout": {"content": [0.08, 0.18, 0.92, 0.72], "captions": [0.06, 0.82, 0.94, 0.96]},
        "word_alignment": "observed-minimax-words", "trim_start": speech.get("trim_start", 0),
        "narration_offset": narration_offset,
    }
    return result


def evaluate_math_timeline(timeline, seconds):
    """Pure, seekable state: old visibility never leaks into a later node."""
    node = next((item for item in reversed(timeline["nodes"]) if item["start"] <= seconds < item["end"]), None)
    caption = next((item["text"] for item in timeline.get("captions", []) if item["start"] <= seconds < item["end"]), "")
    state = {"node_id": node["id"] if node else None, "parts": {}, "values": {}, "caption": caption, "emphasis": None}
    if node is None:
        return state
    elapsed, span = seconds - node["start"], max(.001, node["end"] - node["start"])
    progress = min(1.0, max(0.0, elapsed / span))
    smooth = progress * progress * (3 - 2 * progress)
    state["values"] = {key: value + (node["values_to"][key] - value) * smooth for key, value in node["values_from"].items()}
    actions = {action["target"]: action["kind"] for action in node.get("actions", [])}
    for part in node["visible_parts"]:
        kind = actions.get(part)
        animation_span = min(max(1/timeline.get("fps",30),span-1/timeline.get("fps",30)),.85 if kind=="draw" else .3)
        amount = min(1.0, max(0.0, elapsed / animation_span)) if kind in ACTION_KINDS else 1.0
        state["parts"][part] = {"opacity": amount if kind in {"reveal","transform"} else 1.0, "draw": amount if kind == "draw" else 1.0}
    emphasis = node.get("emphasis")
    emphasis_elapsed = seconds-node.get("emphasis_time",node["start"])
    emphasis_span = min(.9,node["end"]-node.get("emphasis_time",node["start"]))
    if emphasis and 0 <= emphasis_elapsed < emphasis_span:
        pulse = max(0.0, 1 - emphasis_elapsed / emphasis_span)
        # Peak coincides with the compiled sound cue, then settles smoothly.
        state["emphasis"] = {**emphasis, "strength": pulse, "scale": 1 + .14 * pulse}
    return state
