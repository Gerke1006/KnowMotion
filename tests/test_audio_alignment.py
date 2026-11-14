"""Real provider-record regressions; no model calls or video acceptance runs."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from harness.history_director import _aligned_words
from harness.math_animation import _words
from renderers.audio import DEFAULT_VOICE, MiniMaxTTS, normalize_minimax_words
from renderers.base import RendererError


CASES = json.loads((Path(__file__).parent / "fixtures/minimax_observed_whitespace.json")
                   .read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["scene_id"])
def test_observed_whitespace_keeps_exact_offsets_and_timestamps(case):
    raw = copy.deepcopy(case["subtitles"])
    words = normalize_minimax_words(case["text"], raw)
    spaces = [word for segment in raw for word in segment["timestamped_words"] if word["word"].isspace()]
    assert len(spaces) == (1 if case["scene_id"] == "scene_01" else 2)
    for space in spaces:
        assert {"text": space["word"], "char_start": space["word_begin"], "char_end": space["word_end"],
                "start": space["time_begin"] / 1000, "end": space["time_end"] / 1000} in words
    assert raw == case["subtitles"], "The provider's raw evidence must never be rewritten"
    # Both timeline families accept the exact same normalized word evidence.
    assert _words(words, case["text"]) == words
    assert [word.model_dump() for word in _aligned_words(words, case["text"])] == words


@pytest.mark.parametrize("mutation, message", [
    ({"word": ""}, "word text or character offsets"),
    ({"word_begin": 7}, "word text or character offsets"),
    ({"time_end": 853.3333333333333}, "timestamps"),
    ({"time_begin": 100}, "timestamps"),
    ({"time_end": float("nan")}, "timestamps"),
    ({"pronounce_word_end": 9}, "pronunciation offsets"),
])
def test_whitespace_still_requires_valid_measured_timing_and_matching_text(mutation, message):
    case = CASES[0]
    raw = copy.deepcopy(case["subtitles"])
    space = next(word for segment in raw for word in segment["timestamped_words"] if word["word"].isspace())
    space.update(mutation)
    with pytest.raises(RendererError, match=message):
        normalize_minimax_words(case["text"], raw)


def test_failed_cached_alignment_can_be_reparsed_without_another_paid_request(tmp_path, monkeypatch):
    """Reproduce the persisted state left by the old parser, in an isolated dir."""
    case = CASES[0]
    tts = MiniMaxTTS({"minimax_api_key": "fixture", "minimax_voice_id": DEFAULT_VOICE})
    output = tmp_path / "narration.mp3"
    output.write_bytes(b"isolated cached audio fixture" * 4)
    raw_path = output.with_suffix(".alignment.raw.json")
    raw_path.write_text(json.dumps(case["subtitles"], ensure_ascii=False), encoding="utf-8")
    fingerprint = hashlib.sha256(json.dumps(
        ["minimax-word-v2", tts.base_url, case["text"], tts.model, DEFAULT_VOICE, tts.speed],
        ensure_ascii=False).encode()).hexdigest()
    output.with_suffix(".alignment-state.json").write_text(json.dumps({
        "fingerprint": fingerprint, "audio_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(), "trace_id": "fixture-trace",
    }), encoding="utf-8")
    before_audio, before_raw = output.read_bytes(), raw_path.read_bytes()

    def no_network(*args, **kwargs):
        raise AssertionError("Valid cached audio and raw subtitles must not cause a new paid request")

    monkeypatch.setattr(tts, "_post", no_network)
    monkeypatch.setattr(tts, "_subtitle_json", no_network)
    result = tts.synthesize_aligned(case["text"], output)
    assert result["words"] == normalize_minimax_words(case["text"], case["subtitles"])
    assert output.read_bytes() == before_audio and raw_path.read_bytes() == before_raw
