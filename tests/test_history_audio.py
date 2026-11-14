"""Isolated audio contract regressions; no live model, TTS, or acceptance film."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import wave

import httpx
import pytest

from renderers.audio import DEFAULT_VOICE, MiniMaxTTS, normalize_minimax_words
from renderers.base import RendererError
from renderers.history_sound import mix_history_audio
from tools.build_history_resources import ROOT, SAMPLE_RATE, SPECS, synthesize, write_wave


TEXT = "出发，归来。"
SUBTITLES = [{"text": TEXT, "text_begin": 0, "text_end": len(TEXT),
              "time_begin": 100, "time_end": 1450,
              "timestamped_words": [
                  {"word": "出发", "word_begin": 0, "word_end": 2, "time_begin": 100, "time_end": 650},
                  {"word": "归来", "word_begin": 3, "word_end": 5, "time_begin": 900, "time_end": 1450},
              ]}]


def provider_response():
    return {"base_resp": {"status_code": 0}, "trace_id": "fixture-trace",
            "data": {"audio": (b"isolated-fixture-audio" * 5).hex(),
                     "subtitle_file": "https://filecdn.minimax.chat/fixture.json?temporary=fixture"}}


def test_word_timestamps_are_observed_and_not_character_interpolation():
    words = normalize_minimax_words(TEXT, SUBTITLES)
    assert words == [{"text": "出发", "char_start": 0, "char_end": 2, "start": .1, "end": .65},
                     {"text": "归来", "char_start": 3, "char_end": 5, "start": .9, "end": 1.45}]
    assert len(words) == 2  # No invented per-character boundaries inside a provider word.
    with pytest.raises(RendererError, match="sentence"):
        normalize_minimax_words(TEXT, [{"text": TEXT, "time_begin": 100, "time_end": 1450}])


def pronunciation_fixture():
    # Generic quantity only: this mirrors provider shape, never a historical script.
    return "约25分钟。", [{"timestamped_words": [
        {"word": "约", "word_begin": 0, "word_end": 1, "time_begin": 0, "time_end": 100,
         "pronounce_word": "约", "pronounce_word_begin": 0, "pronounce_word_end": 1},
        {"word": "25", "word_begin": 1, "word_end": 3, "time_begin": 100, "time_end": 200,
         "pronounce_word": "二", "pronounce_word_begin": 1, "pronounce_word_end": 2},
        {"word": "25", "word_begin": 1, "word_end": 3, "time_begin": 200, "time_end": 300,
         "pronounce_word": "十", "pronounce_word_begin": 2, "pronounce_word_end": 3},
        {"word": "25", "word_begin": 1, "word_end": 3, "time_begin": 300, "time_end": 450,
         "pronounce_word": "五", "pronounce_word_begin": 3, "pronounce_word_end": 4},
        {"word": "分钟", "word_begin": 3, "word_end": 5, "time_begin": 450, "time_end": 900,
         "pronounce_word": "分钟", "pronounce_word_begin": 4, "pronounce_word_end": 6},
        {"word": "。", "word_begin": 5, "word_end": 6, "time_begin": 900, "time_end": 950,
         "pronounce_word": "。", "pronounce_word_begin": 6, "pronounce_word_end": 7},
    ]}]


def test_consecutive_pronunciation_fragments_merge_without_inventing_boundaries():
    text, data = pronunciation_fixture()
    before = copy.deepcopy(data)
    result = normalize_minimax_words(text, data)
    assert result[1] == {"text": "25", "char_start": 1, "char_end": 3, "start": .1, "end": .45}
    assert len(result) == 4 and result[2]["char_start"] == 3
    assert result[2]["start"] == .45
    assert data == before, "Read-only diagnosis must not rewrite raw provider evidence"


@pytest.mark.parametrize("mutate", [
    lambda word: word.update(pronounce_word_begin=0, pronounce_word_end=1),
    lambda word: word.update(pronounce_word_end=4),
    lambda word: word.update(word="5", word_begin=2),
    lambda word: word.update(time_begin=150),
    lambda word: word.pop("pronounce_word_begin"),
    lambda word: word.update(word="unrelated"),
])
def test_ambiguous_repeated_offsets_still_fail(mutate):
    text, data = pronunciation_fixture()
    mutate(data[0]["timestamped_words"][2])
    with pytest.raises(RendererError):
        normalize_minimax_words(text, data)


@pytest.mark.parametrize("mutate", [
    lambda data: data[0]["timestamped_words"][1].update(time_begin=500),
    lambda data: data[0]["timestamped_words"][0].update(time_end=float("nan")),
    lambda data: data[0]["timestamped_words"][1].update(word_end=7),
    lambda data: data[0]["timestamped_words"][1].update(word="错词"),
    lambda data: data[0]["timestamped_words"].pop(),
])
def test_unreliable_word_timestamps_fail(mutate):
    data = copy.deepcopy(SUBTITLES)
    mutate(data)
    with pytest.raises(RendererError):
        normalize_minimax_words(TEXT, data)


def test_aligned_tts_preserves_voice_caches_raw_and_never_leaks_auth_on_download(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["subtitle_enable"] is True and body["subtitle_type"] == "word"
            assert body["voice_setting"] == {"voice_id": DEFAULT_VOICE, "speed": 1, "vol": 1, "pitch": 0}
            return httpx.Response(200, json=provider_response())
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=SUBTITLES)

    with httpx.Client(transport=httpx.MockTransport(respond), headers={"Authorization": "Bearer private"}) as client:
        tts = MiniMaxTTS({"minimax_api_key": "fixture-key"}, client)
        first = tts.synthesize_aligned(TEXT, tmp_path / "narration.mp3")
        second = tts.synthesize_aligned(TEXT, tmp_path / "narration.mp3")
    assert first == second and len(calls) == 2
    alignment = json.loads(first["alignment_path"].read_text(encoding="utf-8"))
    assert alignment["schema_version"] == "2.0"
    assert alignment["timebase"] == "untrimmed-provider-audio-seconds"
    assert alignment["words"][1]["start"] == .9
    assert alignment["audio_sha256"] == hashlib.sha256(first["audio_path"].read_bytes()).hexdigest()
    for path in tmp_path.glob("*.json"):
        assert "fixture-key" not in path.read_text(encoding="utf-8")
        assert "temporary=fixture" not in path.read_text(encoding="utf-8")


def test_subtitle_download_resume_does_not_charge_for_audio_twice(tmp_path, monkeypatch):
    monkeypatch.setattr("renderers.audio.time.sleep", lambda _: None)
    posts, downloads = [], []

    def respond(request):
        if request.method == "POST":
            posts.append(1)
            return httpx.Response(200, json=provider_response())
        downloads.append(1)
        return httpx.Response(503 if len(downloads) <= 3 else 200, json=SUBTITLES)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tts = MiniMaxTTS({"minimax_api_key": "fixture-key"}, client)
        with pytest.raises(RendererError, match="cached") as error:
            tts.synthesize_aligned(TEXT, tmp_path / "narration.mp3")
        assert "temporary=fixture" not in str(error.value)
        assert (tmp_path / "narration.mp3").is_file()
        tts.synthesize_aligned(TEXT, tmp_path / "narration.mp3")
    assert len(posts) == 1 and len(downloads) == 4


@pytest.mark.parametrize("method", ["POST", "GET"])
def test_transient_transport_retries_are_bounded_and_sanitized(tmp_path, monkeypatch, method):
    monkeypatch.setattr("renderers.audio.time.sleep", lambda _: None)
    calls = []

    def respond(request):
        calls.append(request.method)
        raise httpx.ReadTimeout("fixture-key must not leak", request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tts = MiniMaxTTS({"minimax_api_key": "fixture-key"}, client)
        with pytest.raises(RendererError) as error:
            if method == "POST":
                tts._post("/v1/t2a_v2", {})
            else:
                tts._subtitle_json("https://filecdn.minimax.chat/fixture.json")
    assert calls == [method] * 3
    assert "fixture-key" not in str(error.value)


@pytest.mark.parametrize("method", ["POST", "GET"])
def test_auth_errors_do_not_retry_or_echo_response(tmp_path, method):
    calls = []

    def respond(request):
        calls.append(request.method)
        return httpx.Response(401, text="fixture-key")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tts = MiniMaxTTS({"minimax_api_key": "fixture-key"}, client)
        with pytest.raises(RendererError) as error:
            if method == "POST":
                tts._post("/v1/t2a_v2", {})
            else:
                tts._subtitle_json("https://filecdn.minimax.chat/fixture.json")
    assert calls == [method]
    assert "fixture-key" not in str(error.value)


@pytest.mark.parametrize("first", [503, 429, 1001, 1002, 1039])
def test_tts_only_retries_transient_provider_statuses(monkeypatch, first):
    monkeypatch.setattr("renderers.audio.time.sleep", lambda _: None)
    calls = []

    def respond(request):
        calls.append(1)
        if len(calls) > 1:
            return httpx.Response(200, json=provider_response())
        return (httpx.Response(first) if first < 1000 else
                httpx.Response(200, json={"base_resp": {"status_code": first}}))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = MiniMaxTTS({"minimax_api_key": "fixture-key"}, client)._post("/v1/t2a_v2", {})
    assert result["base_resp"]["status_code"] == 0 and len(calls) == 2


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://127.0.0.1/a", "http://filecdn.minimax.chat/a",
                                "https://minimax.chat.attacker.invalid/a", "https://filecdn.minimax.chat:abc/a"])
def test_subtitle_download_rejects_untrusted_url_without_request(url):
    tts = MiniMaxTTS({})
    with pytest.raises(RendererError):
        tts._subtitle_json(url)


def test_original_sound_assets_rebuild_exactly_and_have_measured_anchors(tmp_path):
    catalog = json.loads((ROOT / "assets/history/animation_resources.json").read_text(encoding="utf-8"))
    cards = {item["id"]: item for item in catalog["sfx_assets"]}
    assert len(cards) == 10
    for kind, duration, seed, gain, description in SPECS:
        pcm = synthesize(kind, duration, seed)
        path = tmp_path / f"{kind}.wav"
        write_wave(path, pcm)
        card = cards[f"sfx.{kind}"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == card["sha256"]
        assert card["peak"] == max(range(len(pcm)), key=lambda i: abs(pcm[i])) / SAMPLE_RATE
        assert 0 <= card["onset"] <= card["peak"] < duration
        assert card["license"] == "project-original"
        with wave.open(str(path)) as sound:
            assert sound.getframerate() == SAMPLE_RATE and sound.getnchannels() == 1


def test_visual_resource_cards_point_to_implementation_and_expose_generic_selection_metadata():
    catalog = fixture_catalog()
    renderer = (ROOT / "renderers/remotion/project/src/directorData.ts").read_text(encoding="utf-8")
    sizes = {name: (int(width), int(height)) for name, width, height in
             re.findall(r"'([^']+)':\s*\[(\d+),\s*(\d+)\]", renderer)}
    known = {item["id"] for item in catalog["visual_assets"]}
    for item in catalog["visual_assets"]:
        assert (ROOT / item["source"]).is_file()
        assert item["intents"] and item["conditions"]
        geometry = item["geometry"]
        assert (geometry["width"], geometry["height"]) == sizes[item["id"]]
        assert geometry["anchor"] == "bottom_center" and geometry["label_bottom"] == 32
        example = item["combination_example"]
        assert set(example["resource_ids"]) <= known
        assert example["action"] in item["actions"]
        assert all(position["y"] <= .72 for position in example["layout"].values())
    for group in ("environments", "sfx_assets"):
        assert all(item["intents"] and item["conditions"] for item in catalog[group])
    assert catalog["generation"]["script_sha256"] == hashlib.sha256(
        (ROOT / "tools/build_history_resources.py").read_bytes()).hexdigest()


class FakeFFmpeg:
    def __init__(self):
        self.calls = []

    def duration(self, path):
        return 5.0

    def run(self, args):
        self.calls.append(args)
        if args[-1] != "-":
            Path(args[-1]).write_bytes(b"isolated-mixed-output" * 8)
        return "mean_volume: -20.0 dB\nmax_volume: -2.0 dB"


def fixture_catalog():
    return json.loads((ROOT / "assets/history/animation_resources.json").read_text(encoding="utf-8"))


def test_final_mix_preserves_bgm_gain_and_compensates_peak_without_second_speedup(tmp_path):
    ffmpeg = FakeFFmpeg()
    joined, music = tmp_path / "joined.mp4", tmp_path / "bgm.m4a"
    joined.write_bytes(b"narration" * 20)
    music.write_bytes(b"music" * 20)
    event = {"cue_id": "beat-1", "asset_id": "sfx.stamp", "at": .001, "align": "peak", "gain_db": -1}
    report = mix_history_audio(ffmpeg, joined, tmp_path / "final.mp4", [event], fixture_catalog(), music, .30,
                               tmp_path)
    graph = ffmpeg.calls[0][ffmpeg.calls[0].index("-filter_complex") + 1]
    assert "volume=0.300000000" in graph
    assert "atempo" not in graph and "sidechain" not in graph
    assert "latency=1" in graph and "level=0" in graph
    placed = report["events"][0]
    assert placed["trim_start"] > 0 and placed["playback_start"] == 0
    assert abs(placed["aligned_at"] - event["at"]) <= 1 / SAMPLE_RATE
    assert placed["peak_at"] == placed["aligned_at"]
    assert report["bgm"]["configured_gain"] == .3 and report["bgm"]["ducking"] is False
    assert report["playback_speed_applied_here"] is False
    assert report["levels"]["final_mix"]["max_dbfs"] == -2
    assert json.loads((tmp_path / "audio_mix_report.json").read_text(encoding="utf-8")) == report


def test_final_mix_allows_effect_to_cross_scene_boundary_and_trims_film_end(tmp_path):
    joined = tmp_path / "joined.mp4"
    joined.write_bytes(b"narration" * 20)
    event = {"cue_id": "last", "asset_id": "sfx.chime", "at": 4.9, "align": "onset", "gain_db": 0}
    report = mix_history_audio(FakeFFmpeg(), joined, tmp_path / "final.mp4", [event], fixture_catalog(), None,
                               .3, tmp_path)
    assert report["events"][0]["playback_end"] == 5.0
    assert report["events"][0]["playback_start"] < 4.9


def test_sound_tampering_and_unregistered_paths_fail_before_mixing(tmp_path):
    joined = tmp_path / "joined.mp4"
    joined.write_bytes(b"narration" * 20)
    cards = fixture_catalog()
    cards["sfx_assets"][0]["sha256"] = "wrong"
    event = {"cue_id": "one", "asset_id": "sfx.footstep", "at": 1, "align": "onset", "gain_db": 0}
    ffmpeg = FakeFFmpeg()
    with pytest.raises(RendererError, match="fingerprint"):
        mix_history_audio(ffmpeg, joined, tmp_path / "final.mp4", [event], cards, None, .3, tmp_path)
    assert ffmpeg.calls == []
    cards["sfx_assets"][0]["path"] = "../private.wav"
    with pytest.raises(RendererError, match="bundled"):
        mix_history_audio(ffmpeg, joined, tmp_path / "final.mp4", [event], cards, None, .3, tmp_path)


def test_actual_ffmpeg_accepts_final_mix_filter_graph(tmp_path):
    from renderers.ffmpeg import FFmpeg

    ffmpeg = FFmpeg()
    joined = tmp_path / "isolated-fixture.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "color=black:s=64x64:r=10:d=0.8", "-f", "lavfi", "-i",
                "sine=frequency=200:sample_rate=48000:duration=0.8", "-c:v", "libx264", "-c:a", "aac",
                "-shortest", str(joined)])
    event = {"cue_id": "fixture-cue", "asset_id": "sfx.stamp", "at": .05, "align": "peak", "gain_db": 0}
    report = mix_history_audio(ffmpeg, joined, tmp_path / "mixed.mp4", [event], fixture_catalog(),
                               ROOT / "assets/audio/history/wind.wav", .30, tmp_path)
    assert abs(ffmpeg.duration(tmp_path / "mixed.mp4") - .8) < .1
    assert report["levels"]["final_mix"]["max_dbfs"] is not None
