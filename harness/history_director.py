"""Strict history director data and deterministic, speech-aligned compilation.

No content is authored here. Narration, scene objects and beats arrive from the
configured project model; this module validates references and resolves timing.
"""
from __future__ import annotations

import copy
import math
import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness.history import referenced_source_ids, validate_history_parameters
from harness.media_clock import composition_clock


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ResourceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")]
PositionX = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
PositionY = Annotated[float, Field(ge=0, le=.82, allow_inf_nan=False)]
Scale = Annotated[float, Field(ge=.3, le=1.5, allow_inf_nan=False)]
ActionKind = Literal["enter", "exit", "move", "walk", "ride", "open", "close", "unroll",
                     "handover", "stamp", "draw", "emphasize", "gesture"]
SUPPORTED_VISUALS = {"actor.person", "actor.envoy", "actor.horse", "actor.caravan", "prop.gate",
                     "prop.document", "prop.flag", "prop.scroll", "prop.seal", "info.map", "info.timeline",
                     "info.portrait"}
SUPPORTED_ENVIRONMENTS = {"mountains", "road", "desert", "city_gate", "interior", "map"}


class DirectorValidationError(ValueError):
    """Small machine-readable errors suitable for one bounded model repair."""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = [{"code": str(item["code"])[:80], "path": str(item["path"])[:180],
                        "message": str(item["message"])[:240]} for item in errors]
        super().__init__("; ".join(f"{e['code']} at {e['path']}: {e['message']}" for e in self.errors)[:1800])


def _fail(code: str, path: str, message: str):
    raise DirectorValidationError([{"code": code, "path": path, "message": message}])


def validation_errors(error: Exception) -> list[dict[str, str]]:
    if isinstance(error, DirectorValidationError):
        return copy.deepcopy(error.errors)
    if isinstance(error, ValidationError):
        return [{"code": item["type"], "path": ".".join(map(str, item["loc"])),
                 "message": item["msg"][:240]} for item in error.errors(include_input=False, include_url=False)[:24]]
    return [{"code": "invalid_contract", "path": "", "message": str(error)[:240]}]


class StrictData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NarrationSegment(StrictData):
    id: Identifier
    narration: str = Field(min_length=1, max_length=160)
    source_ids: list[Identifier] = Field(min_length=1, max_length=12)
    intent: str = Field(min_length=1, max_length=80)


class HistoryScript(StrictData):
    title: str = Field(min_length=1, max_length=40)
    segments: list[NarrationSegment] = Field(min_length=5, max_length=8)

    @model_validator(mode="after")
    def bounded_script(self):
        ids = [segment.id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("Narration segment IDs must be unique")
        if not 380 <= sum(len(segment.narration) for segment in self.segments) <= 480:
            raise ValueError("Total narration must contain 380 to 480 characters, including punctuation")
        return self


class StagePoint(StrictData):
    x: PositionX
    y: PositionY


class StageObject(StrictData):
    id: Identifier
    asset_id: ResourceId
    x: PositionX
    y: PositionY
    scale: Scale = 1.0
    facing: Literal[-1, 1] = 1
    label: str = Field(default="", max_length=10)
    parameters: dict[str, Any] = Field(default_factory=dict)
    evidence_quote: str | None = Field(default=None, min_length=1, max_length=160)


class SpeechAnchor(StrictData):
    quote: str = Field(min_length=1, max_length=80)
    occurrence: int = Field(default=1, ge=1, le=30)
    edge: Literal["start", "end"] = "start"


class Camera(StrictData):
    x: PositionX = .5
    y: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = .5
    zoom: float = Field(default=1.0, ge=1, le=1.25, allow_inf_nan=False)


class StageAction(StrictData):
    target_id: Identifier
    kind: ActionKind
    to_x: PositionX | None = None
    to_y: PositionY | None = None
    scale: Scale | None = None
    path: list[StagePoint] | None = Field(default=None, min_length=2, max_length=12)

    @model_validator(mode="after")
    def paired_destination(self):
        if (self.to_x is None) != (self.to_y is None):
            raise ValueError("to_x and to_y must be provided together")
        if self.path and self.to_x is not None and (
            not math.isclose(self.path[-1].x, self.to_x, abs_tol=1e-6)
            or not math.isclose(self.path[-1].y, self.to_y, abs_tol=1e-6)
        ):
            raise ValueError("Path endpoint must equal the explicit destination")
        return self


class SoundCue(StrictData):
    asset_id: ResourceId
    align: Literal["onset", "peak"] = "onset"
    gain_db: float = Field(default=0.0, ge=-18, le=6, allow_inf_nan=False)


class DirectorBeat(StrictData):
    id: Identifier
    anchor: SpeechAnchor
    visible_ids: list[Identifier] = Field(min_length=1, max_length=3)
    focus_id: Identifier
    keywords: list[Annotated[str, Field(min_length=1, max_length=10)]] = Field(default_factory=list, max_length=2)
    actions: list[StageAction] = Field(default_factory=list, max_length=3)
    camera: Camera = Field(default_factory=Camera)
    sfx: SoundCue | None = None
    evidence_quote: str | None = Field(default=None, min_length=1, max_length=160)
    evidence_by_object: dict[Identifier, Annotated[str, Field(min_length=1, max_length=160)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unambiguous_groups(self):
        if len(set(self.visible_ids)) != len(self.visible_ids) or self.focus_id not in self.visible_ids:
            raise ValueError("Visible IDs must be unique and include focus_id")
        targets = [action.target_id for action in self.actions]
        if len(targets) != len(set(targets)):
            raise ValueError("Only one action per target is allowed in each beat")
        if any(target not in self.visible_ids for target in targets):
            raise ValueError("Action targets must belong to the current visible_ids")
        return self


class DirectorScene(StrictData):
    scene_id: Identifier
    segment_id: Identifier
    environment: ResourceId
    objects: list[StageObject] = Field(min_length=1, max_length=10)
    beats: list[DirectorBeat] = Field(min_length=2, max_length=16)


class DirectorPlan(StrictData):
    schema_version: Literal["2.0"]
    style_id: Literal["gufeng"]
    scenes: list[DirectorScene] = Field(min_length=5, max_length=8)


class TimelinePoint(StrictData):
    year: float = Field(ge=-10000, le=10000, allow_inf_nan=False)
    date_label: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=56)
    source_ids: list[Identifier] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def civil_year(self):
        if self.year == 0:
            raise ValueError("Historical civil years have no year zero")
        return self


class PortraitSymbol(StrictData):
    name: str = Field(min_length=1, max_length=56)
    role: str = Field(min_length=1, max_length=56)
    source_ids: list[Identifier] = Field(min_length=1, max_length=12)


class AlignedWord(StrictData):
    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


def _model(contract, value):
    try:
        raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else copy.deepcopy(value)
        return contract.model_validate(raw)
    except ValidationError as error:
        raise DirectorValidationError(validation_errors(error)) from None


def _dict(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else copy.deepcopy(value)


def validate_script(script, sources: list[dict] | None = None) -> HistoryScript:
    result = _model(HistoryScript, script)
    if sources is not None:
        known = {source.get("id") for source in sources}
        for index, segment in enumerate(result.segments):
            if set(segment.source_ids) - known:
                _fail("unknown_source", f"segments.{index}.source_ids", "Use only retrieved evidence IDs")
    return result


def _catalog(resources, field):
    rows = resources.get(field, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") for row in rows):
        _fail("invalid_catalog", field, "Resource lists need stable IDs")
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        _fail("invalid_catalog", field, "Resource IDs must be unique")
    return result


def _quote_span(narration, anchor, path):
    position = -1
    for _ in range(anchor.occurrence):
        position = narration.find(anchor.quote, position + 1)
        if position < 0:
            _fail("anchor_not_found", path, "Quote and occurrence must match the original narration exactly")
    return position, position + len(anchor.quote)


def _validate_scene(scene, segment, resources, sources, geography, *, validation_enabled=True):
    environments = _catalog(resources, "environments")
    visuals = _catalog(resources, "visual_assets")
    sounds = _catalog(resources, "sfx_assets")
    base = f"scenes.{scene.scene_id}"
    if scene.environment not in environments or scene.environment not in SUPPORTED_ENVIRONMENTS:
        _fail("unknown_environment", base + ".environment", "Select a catalog environment ID")
    objects = {obj.id: obj for obj in scene.objects}
    if len(objects) != len(scene.objects):
        _fail("duplicate_object", base + ".objects", "Object IDs must be unique within the scene")
    known_sources = {source.get("id") for source in sources}
    if validation_enabled and set(segment.source_ids) - known_sources:
        _fail("unknown_source", base + ".segment_id", "Segment cites unknown evidence")
    anchors = {row["id"]: row for row in (geography or {}).get("records", [])}
    for obj in scene.objects:
        path = base + ".objects." + obj.id
        if obj.asset_id not in visuals:
            _fail("unknown_visual_asset", path + ".asset_id", "Select a catalog visual asset ID")
        if obj.asset_id not in SUPPORTED_VISUALS:
            _fail("unsupported_visual_asset", path + ".asset_id", "The trusted renderer does not implement this resource")
        try:
            if obj.asset_id == "info.map":
                params = validate_history_parameters("history.map", obj.parameters,
                                                     sources=sources if validation_enabled else None,
                                                     require_sources=validation_enabled)
                if len(params["locations"]) != 2:
                    _fail("map_endpoints", path, "A current map beat shows exactly two endpoint locations")
                if validation_enabled:
                    for point in params["locations"]:
                        known = anchors.get(point["id"])
                        if not known or any(not math.isclose(point[axis], known[axis], abs_tol=1e-5, rel_tol=0)
                                            for axis in ("lon", "lat")):
                            _fail("unverified_coordinate", path, "Map endpoints must match this run's geography IDs and coordinates")
                obj.parameters = params
            elif obj.asset_id == "info.timeline":
                obj.parameters = _model(TimelinePoint, obj.parameters).model_dump(mode="json")
            elif obj.asset_id == "info.portrait":
                obj.parameters = _model(PortraitSymbol, obj.parameters).model_dump(mode="json")
            elif obj.asset_id.startswith(("actor.", "prop.")):
                if obj.parameters:
                    _fail("unexpected_parameters", path + ".parameters", "Actor and prop resources accept an empty object")
            else:
                _fail("unsupported_visual_asset", path + ".asset_id", "The trusted director renderer does not implement this asset")
        except ValidationError as error:
            raise DirectorValidationError(validation_errors(error)) from None
        except DirectorValidationError:
            raise
        except ValueError as error:
            _fail("invalid_resource_parameters", path + ".parameters", str(error))
        referenced = referenced_source_ids(obj.parameters)
        if validation_enabled and (referenced - known_sources or referenced - set(segment.source_ids)):
            _fail("unbound_visual_evidence", path + ".parameters.source_ids", "Visible facts must cite this segment's evidence IDs")
    beat_ids = [beat.id for beat in scene.beats]
    if len(beat_ids) != len(set(beat_ids)):
        _fail("duplicate_beat", base + ".beats", "Beat IDs must be unique within the scene")
    used = set()
    previous = None
    previous_span = None
    exited = set()
    for beat in scene.beats:
        path = base + ".beats." + beat.id
        if set(beat.visible_ids) - set(objects):
            _fail("unknown_object", path + ".visible_ids", "All visible objects must be declared in this scene")
        used.update(beat.visible_ids)
        span = _quote_span(segment.narration, beat.anchor, path + ".anchor")
        position = span[0] if beat.anchor.edge == "start" else span[1]
        if previous_span is not None and position <= previous_span:
            _fail("anchor_order", path + ".anchor", "Beats must follow the original narration in order")
        previous_span = position
        enters = {action.target_id for action in beat.actions if action.kind == "enter"}
        if validation_enabled and exited.intersection(beat.visible_ids) - enters:
            _fail("exited_object_visible", path, "An exited object must enter explicitly before becoming visible again")
        for action in beat.actions:
            if action.kind not in visuals[objects[action.target_id].asset_id].get("actions", []):
                _fail("unsupported_action", path + ".actions", "The selected resource does not support this action")
        exited.difference_update(enters)
        exited.update(action.target_id for action in beat.actions if action.kind == "exit")
        if beat.sfx and beat.sfx.asset_id not in sounds:
            _fail("unknown_sfx", path + ".sfx.asset_id", "Select a catalog sound asset ID")
        if validation_enabled and previous and (
                beat.visible_ids == previous.visible_ids and beat.focus_id == previous.focus_id
                and beat.keywords == previous.keywords and not beat.actions):
            _fail("no_semantic_change", path, "A new beat needs a visible information or object action change")
        previous = beat
    if validation_enabled and used != set(objects):
        _fail("unused_object", base + ".objects", "Every declared object must appear in at least one beat")


def validate_director(plan, script, resources, research, *, require_narrative_bindings=False,
                      validation_enabled: bool = True) -> DirectorPlan:
    """Parse executable data, optionally applying narrative and quality validation."""
    script = validate_script(script, research.get("sources", []) if validation_enabled else None)
    result = _model(DirectorPlan, plan)
    if [scene.segment_id for scene in result.scenes] != [segment.id for segment in script.segments]:
        _fail("segment_scene_binding", "scenes", "Provide exactly one scene per segment, in original segment order")
    if len({scene.scene_id for scene in result.scenes}) != len(result.scenes):
        _fail("duplicate_scene", "scenes", "Scene IDs must be unique")
    narrative_errors = []
    previous_segments = []
    from harness.history_narrative import validate_narrative_bindings
    for scene, segment in zip(result.scenes, script.segments):
        try:
            _validate_scene(scene, segment, resources, research.get("sources", []), research.get("geography"),
                            validation_enabled=validation_enabled)
        except DirectorValidationError as error:
            if not require_narrative_bindings:
                raise
            narrative_errors.extend(error.errors)
        if validation_enabled:
            report = validate_narrative_bindings(scene, segment, resources, require_bindings=require_narrative_bindings,
                                                 prior_narration="\n".join(previous_segments))
            narrative_errors.extend(report["errors"])
        previous_segments.append(segment.narration)
    if narrative_errors:
        raise DirectorValidationError(narrative_errors)
    return result


def _aligned_words(words, narration):
    if not words:
        _fail("missing_alignment", "words", "Observed word timestamps are required; estimated timing is forbidden")
    parsed = [_model(AlignedWord, word) for word in words]
    previous_char, previous_end = 0, 0.0
    covered = set()
    for index, word in enumerate(parsed):
        if (word.char_start < previous_char or word.char_end > len(narration) or word.char_end <= word.char_start
                or narration[word.char_start:word.char_end] != word.text):
            _fail("invalid_character_alignment", f"words.{index}", "Words must match nonoverlapping original narration offsets")
        if word.start < previous_end - .03 or word.end <= word.start:
            _fail("invalid_word_timing", f"words.{index}", "Word times must increase without substantial overlap")
        covered.update(range(word.char_start, word.char_end))
        previous_char, previous_end = word.char_end, word.end
    missing = [index for index, character in enumerate(narration)
               if index not in covered and unicodedata.category(character)[0] not in {"P", "Z", "C"}]
    if missing:
        _fail("incomplete_alignment", "words", "All spoken characters require observed timestamps")
    return parsed


def _captions(narration, words, trim_start, offset, duration, protected_phrases=()):
    """Single-line natural pages, preserving words and original source spans."""
    hard = set("。！？；.!?;\n")
    soft = set("，、：,:…")

    def spoken(text):
        return any(unicodedata.category(char)[0] not in {"P", "Z", "C"} for char in text)

    def boundary(position, marks):
        char = narration[position]
        if char not in marks:
            return False
        return not (char in ".,:" and 0 < position < len(narration) - 1
                    and narration[position - 1].isdigit() and narration[position + 1].isdigit())

    lexical = [word for word in words if spoken(word.text)]
    if not lexical:
        _fail("missing_caption_words", "captions", "Caption pages require observed spoken words")
    units, cursor = [], 0
    for index, word in enumerate(lexical):
        for position in range(word.char_start, word.char_end):
            if boundary(position, hard) and spoken(narration[position + 1:word.char_end]):
                _fail("alignment_crosses_sentence", "words", "A timed token crosses a sentence boundary; finer observed alignment is required")
        next_start = lexical[index + 1].char_start if index + 1 < len(lexical) else len(narration)
        end = word.char_end
        while end < next_start:
            char = narration[end]
            opening = char in "“‘「『（([{《〈" or (char == '"' and narration[:end].count('"') % 2 == 0)
            if opening:
                break
            end += 1
        if end - cursor > 24:
            _fail("alignment_token_too_long", "words", "A word with its attached punctuation exceeds the 24-character caption limit")
        members = [item for item in words if item.char_start < end and item.char_end > cursor]
        units.append({"left": cursor, "right": end, "start": word.start,
                      "end": max(item.end for item in members),
                      "hard": any(boundary(position, hard) for position in range(cursor, end)),
                      "soft": any(boundary(position, soft) for position in range(word.char_end, end))
                              or (end > cursor and boundary(word.char_end - 1, soft))})
        cursor = end
    # A closing quote or punctuation has no independent page or estimated word time.
    if cursor < len(narration):
        if spoken(narration[cursor:]) or len(narration) - units[-1]["left"] > 24:
            _fail("unattached_caption_text", "captions", "Trailing text cannot fit its observed word without splitting it")
        units[-1]["right"] = len(narration)

    protected = []
    for phrase in protected_phrases:
        if not isinstance(phrase, str) or not 1 < len(phrase) <= 24:
            continue
        position = narration.find(phrase)
        while position >= 0:
            if not any(boundary(index, hard) for index in range(position, position + len(phrase))):
                protected.append((position, position + len(phrase)))
            position = narration.find(phrase, position + 1)
    joined = []
    for unit in units:
        if joined and any(left < unit["left"] < right for left, right in protected):
            previous = joined[-1]
            previous.update(right=unit["right"], end=unit["end"], hard=unit["hard"], soft=unit["soft"])
            if previous["right"] - previous["left"] > 24:
                _fail("caption_phrase_too_long", "captions", "An indivisible observed word/name plus punctuation exceeds 24 characters")
        else:
            joined.append(unit)
    units = joined

    sentences, current = [], []
    for unit in units:
        current.append(unit)
        if unit["hard"]:
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    pages = []
    for sentence in sentences:
        first = 0
        while first < len(sentence):
            stop = first
            while stop < len(sentence) and sentence[stop]["right"] - sentence[first]["left"] <= 24:
                stop += 1
            if stop < len(sentence):
                natural = [index + 1 for index in range(first, stop) if sentence[index]["soft"]]
                if natural:
                    stop = natural[-1]
            group = sentence[first:stop]
            left, right = group[0]["left"], group[-1]["right"]
            start = max(0.0, group[0]["start"] - trim_start + offset)
            end = min(duration, group[-1]["end"] - trim_start + offset)
            if end <= start:
                _fail("caption_outside_speech", "captions", "Caption timings fall outside trimmed speech")
            pages.append({"text": re.sub(r"\s+", " ", narration[left:right]), "start": start, "end": end,
                          "char_start": left, "char_end": right})
            first = stop
    for previous, following in zip(pages, pages[1:]):
        if following["start"] <= previous["start"]:
            _fail("overlapping_caption_timing", "captions", "Successive caption pages require increasing observed word starts")
        if following["start"] - previous["end"] <= .35:
            previous["end"] = following["start"]
    captions = [{**page, "start": round(page["start"], 6), "end": round(page["end"], 6)} for page in pages]
    return captions


def compile_scene(scene, segment, words, speech, resources, sources, geography=None,
                  fps=30, transition=.30, narration_gap=.08, require_narrative_bindings=False,
                  *, prior_narration: str = "", validation_enabled: bool = True) -> dict:
    """Resolve speech timing, with only completed earlier segments as identity context."""
    scene = _model(DirectorScene, scene)
    segment = _model(NarrationSegment, segment)
    if scene.segment_id != segment.id:
        _fail("segment_scene_binding", "segment_id", "The scene must reference the supplied segment")
    _validate_scene(scene, segment, resources, sources, geography, validation_enabled=validation_enabled)
    from harness.history_narrative import narrative_caption_phrases, validate_narrative_bindings
    if validation_enabled:
        narrative_report = validate_narrative_bindings(scene, segment, resources, require_bindings=require_narrative_bindings,
                                                       prior_narration=prior_narration)
        if narrative_report["errors"]:
            raise DirectorValidationError(narrative_report["errors"])
    else:
        narrative_report = {"scene_id": scene.scene_id, "segment_id": segment.id, "skipped": True,
                            "reason": "validation_disabled", "passed": None, "required": False,
                            "errors": [], "warnings": [], "beats": []}
    aligned = _aligned_words(words, segment.narration)
    if (not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value) and value >= 0 for value in (transition, narration_gap))):
        _fail("invalid_timebase", "fps", "FPS must be positive; transition and narration gap must be finite and nonnegative")
    trim_start, speech_duration = speech.get("trim_start", 0), speech.get("duration")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in (trim_start, speech_duration)) or trim_start < 0 or speech_duration <= 0:
        _fail("invalid_speech", "speech", "Measured trimmed speech duration and trim_start are required")
    offset = transition / 2
    duration = math.ceil((speech_duration + transition + narration_gap) * fps - 1e-8) / fps
    timings = []
    for beat in scene.beats:
        left, right = _quote_span(segment.narration, beat.anchor, f"beats.{beat.id}.anchor")
        selected = [word for word in aligned if word.char_start < right and word.char_end > left]
        if not selected:
            _fail("unresolved_anchor", f"beats.{beat.id}.anchor", "The quote has no observed spoken word")
        raw_time = selected[0].start if beat.anchor.edge == "start" else selected[-1].end
        anchor_time = raw_time - trim_start + offset
        if anchor_time < -.04 or anchor_time >= duration:
            _fail("anchor_outside_scene", f"beats.{beat.id}.anchor", "Observed anchor is outside trimmed scene time")
        timings.append(max(0.0, anchor_time))
    starts = [0.0, *timings[1:]]
    if any(end - start < 1 / fps for start, end in zip(starts, [*starts[1:], duration])):
        _fail("overlapping_beats", "beats", "Distinct beats need increasing observed speech times separated by at least one frame")
    state = {obj.id: {"x": obj.x, "y": obj.y, "scale": obj.scale} for obj in scene.objects}
    resolved = []
    for index, beat in enumerate(scene.beats):
        start, end = starts[index], starts[index + 1] if index + 1 < len(starts) else duration
        if not start - 1e-6 <= timings[index] <= end:
            _fail("anchor_outside_beat", f"beats.{beat.id}.anchor", "Observed anchor is outside its visual window; choose a distinct timed word")
        action_start = timings[index]
        if beat.actions and (end <= action_start or end - action_start + 1e-9 < 1 / fps):
            _fail("action_window_too_short", f"beats.{beat.id}.actions",
                  "An action needs at least one frame after its observed speech anchor; choose an earlier anchor or later next beat")
        actions = []
        for action in beat.actions:
            before = copy.deepcopy(state[action.target_id])
            after = copy.deepcopy(before)
            if action.path:
                after.update(x=action.path[-1].x, y=action.path[-1].y)
            elif action.to_x is not None:
                after.update(x=action.to_x, y=action.to_y)
            if action.scale is not None:
                after["scale"] = action.scale
            item = {"target_id": action.target_id, "kind": action.kind,
                    "start": round(action_start, 6), "end": round(end, 6), "from": before, "to": after}
            if action.path:
                points = [point.model_dump(mode="json") for point in action.path]
                origin = {"x": before["x"], "y": before["y"]}
                if points[0] != origin:
                    points.insert(0, origin)
                item["path"] = points
            actions.append(item)
            state[action.target_id] = after
        resolved.append({"id": beat.id, "start": round(start, 6), "end": round(end, 6),
                         "anchor_time": round(timings[index], 6), "visible_ids": beat.visible_ids,
                         "focus_id": beat.focus_id, "keywords": beat.keywords,
                         "evidence_quote": beat.evidence_quote, "evidence_by_object": beat.evidence_by_object,
                         "camera": beat.camera.model_dump(mode="json"), "actions": actions,
                         "sfx": beat.sfx.model_dump(mode="json") if beat.sfx else None})
    cited = set(segment.source_ids)
    return {"protocol": "history-director-v2", "scene_id": scene.scene_id, "segment_id": segment.id,
            "title": segment.intent, "narration": segment.narration, "duration": duration, "fps": fps,
            "environment": scene.environment, "objects": [obj.model_dump(mode="json") for obj in scene.objects],
            "narrative_report": narrative_report,
            "sources": [{key: value for key, value in source.items() if key in {"id", "title", "url", "provider"}}
                        for source in sources if source.get("id") in cited],
            "captions": _captions(segment.narration, aligned, trim_start, offset, duration,
                                  narrative_caption_phrases(scene)), "beats": resolved,
            "checks": {"observed_word_alignment": True, "all_anchors_resolved": True,
                       "max_visible_groups": max(len(beat.visible_ids) for beat in scene.beats),
                       "max_beat_seconds": max(beat["end"] - beat["start"] for beat in resolved),
                       "narration_offset": offset, "trim_start": trim_start}}


def validate_film_timeline(resolved_scenes, playback_speed, transition) -> dict:
    """Check actual, post-speed semantic pacing and sound cue density."""
    scenes = [_dict(scene) for scene in resolved_scenes]
    if (not scenes or not isinstance(playback_speed, (int, float)) or isinstance(playback_speed, bool)
            or not math.isfinite(playback_speed) or playback_speed <= 0):
        _fail("invalid_film_timing", "playback_speed", "A nonempty film and positive finite playback speed are required")
    if (not isinstance(transition, (int, float)) or isinstance(transition, bool)
            or not math.isfinite(transition) or transition < 0):
        _fail("invalid_film_timing", "transition", "Transition must be finite and nonnegative")
    if len({scene.get("scene_id") for scene in scenes}) != len(scenes):
        _fail("duplicate_scene", "resolved_scenes", "Resolved scene IDs must be unique")
    fps = scenes[0].get("fps", 30)
    if (not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0
            or any(scene.get("fps", 30) != fps for scene in scenes)):
        _fail("inconsistent_fps", "resolved_scenes.fps", "All scenes must use the same positive integer frame rate")
    cues, gaps = [], []
    durations = []
    for index, scene in enumerate(scenes):
        if scene.get("protocol") != "history-director-v2" or not scene.get("beats"):
            _fail("invalid_resolved_scene", "resolved_scenes", "All scenes must have compiled director beats")
        duration = scene.get("duration")
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            _fail("invalid_resolved_scene", scene.get("scene_id", ""), "Scene duration must be positive and finite")
        durations.append(duration)
        previous_end = 0.0
        for beat in scene["beats"]:
            start, end = beat.get("start"), beat.get("end")
            if (not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (start, end))
                    or not 0 <= start < end <= duration + 1e-5):
                _fail("invalid_beat_window", scene["scene_id"], "Compiled beat windows must lie inside scene duration")
            if not math.isclose(start, previous_end, abs_tol=1e-5):
                _fail("noncontiguous_beats", scene["scene_id"], "Compiled beats must cover the scene without gaps or overlap")
            previous_end = end
            gaps.append((end - start) / playback_speed)
            if beat.get("sfx"):
                anchor = beat.get("anchor_time")
                if (not isinstance(anchor, (int, float)) or not math.isfinite(anchor)
                        or not start - 1e-5 <= anchor <= end + 1e-5):
                    _fail("invalid_sfx_anchor", scene["scene_id"], "Sound cues require an observed anchor inside their beat")
                cues.append((index, anchor))
        if not math.isclose(previous_end, duration, abs_tol=1e-5):
            _fail("noncontiguous_beats", scene["scene_id"], "Compiled beats must cover the entire scene")
    try:
        clock = composition_clock(durations, fps, transition, playback_speed)
    except ValueError as error:
        _fail("invalid_film_timing", "timebase", str(error))
    duration = clock["expected_duration"]
    cue_times = [(clock["scene_starts"][index] + anchor) / playback_speed for index, anchor in cues]
    rate = len(cues) / duration * 60
    checks = {"all_anchors_resolved": True, "duration": round(duration, 6),
              "max_semantic_gap": round(max(gaps), 6), "sfx_count": len(cues),
              "source_duration": clock["source_duration"], "scene_starts": clock["scene_starts"],
              "overlaps": clock["overlaps"], "sfx_times": cue_times,
              "sfx_triggers_per_minute": round(rate, 6),
              "semantic_gap_within_limit": max(gaps) <= 4 + 1e-6,
              "sfx_density_within_limit": 12 <= rate <= 18}
    errors = []
    if not checks["semantic_gap_within_limit"]:
        errors.append({"code": "semantic_gap", "path": "beats", "message": f"Longest final semantic beat is {max(gaps):.2f}s; maximum is 4s"})
    if not checks["sfx_density_within_limit"]:
        errors.append({"code": "sfx_density", "path": "beats.sfx", "message": f"Actual sound cue density is {rate:.2f}/min; require 12 to 18/min"})
    if errors:
        error = DirectorValidationError(errors)
        error.checks = checks
        raise error
    return checks
