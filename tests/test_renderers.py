import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from renderers.audio import DEFAULT_VOICE, MiniMaxTTS
from renderers.base import RendererError, math_function
from renderers.ffmpeg import FFmpeg
from renderers.manim import ManimRenderer


def test_math_expression_is_data_not_python():
    assert math_function("x**2 + sin(x)")(0) == 0
    assert math_function("3*x + 2")(4) == 14
    for expression in ["__import__('os').system('whoami')", "x.__class__", "[x for x in range(3)]"]:
        with pytest.raises(RendererError):
            math_function(expression)
    with pytest.raises(RendererError):
        math_function("x**1000")(2)


def test_tts_uses_real_voice_and_caches(tmp_path):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(
            200, json={"base_resp": {"status_code": 0}, "data": {"audio": (b"a" * 100).hex()}}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tts = MiniMaxTTS(SimpleNamespace(minimax_api_key="test-secret"), client)
        output = tmp_path / "voice.mp3"
        tts.synthesize("解释导数", output)
        tts.synthesize("解释导数", output)
        assert len(calls) == 1
        assert calls[0]["voice_setting"]["voice_id"] == DEFAULT_VOICE
        assert output.read_bytes() == b"a" * 100
        tts.synthesize("新的旁白", output)
        assert len(calls) == 2


def test_tts_provider_error_is_not_silence(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"base_resp": {"status_code": 1008, "status_msg": "test-secret"}}
            )
        )
    ) as client:
        tts = MiniMaxTTS(SimpleNamespace(minimax_api_key="test-secret"), client)
        with pytest.raises(RendererError, match="1008") as exc:
            tts.synthesize("旁白", tmp_path / "voice.mp3")
        assert "test-secret" not in str(exc.value)


def test_generated_manim_does_not_interpolate_python(tmp_path):
    dangerous = "'); __import__('os').system('bad'); #"
    source = ManimRenderer().generate(
        {"scene_id": "s1", "title": dangerous, "components": [], "duration": 1}, {}, tmp_path
    )
    compiled = compile(source.read_text(encoding="utf-8"), str(source), "exec")
    assert compiled
    assert "json.loads" in source.read_text(encoding="utf-8")
    with pytest.raises(RendererError):
        ManimRenderer().generate({"scene_id": "../outside"}, {}, tmp_path)


def test_audio_normalization_and_effect_delay(tmp_path, monkeypatch):
    ff = object.__new__(FFmpeg)
    captured = []

    def run(args):
        captured.extend(args)
        Path(args[-1]).write_bytes(b"x" * 100)

    ff.run = run
    effect = tmp_path / "effect.wav"
    effect.write_bytes(b"x" * 100)
    ff.normalize(
        tmp_path / "source.mp4",
        tmp_path / "out.mp4",
        {"width": 640, "height": 360, "fps": 24},
        3.5,
        tmp_path / "voice.mp3",
        [{"path": str(effect), "at": 1.2}],
    )
    graph = captured[captured.index("-filter_complex") + 1]
    assert "adelay=1200|1200" in graph
    assert "trim=duration=3.5" in graph
    assert "tpad=stop_mode=clone" in graph
    assert "loudnorm=I=-16:TP=-1.5:LRA=11:dual_mono=true" in graph


def test_requested_missing_bgm_fails_before_tts(tmp_path):
    from renderers.service import VideoRenderer

    with pytest.raises(RendererError, match="BGM"):
        VideoRenderer({"tts_enabled": False, "bgm_path": str(tmp_path / "missing.m4a")}).render(
            {"metadata": {}, "scenes": [{"scene_id": "s1", "renderer": "canvas", "duration": 1}]}, tmp_path
        )


def test_component_bounds_rejected():
    from renderers.base import validate_component

    for kind, params in [
        ("math.derivative_secant", {"x_range": [1, 1]}),
        ("math.derivative_secant", {"dx_end": 0}),
        ("math.integral_riemann", {"bounds": [-1, 2]}),
        ("math.integral_riemann", {"n_start": 0}),
        ("math.pythagorean", {"a": -3}),
    ]:
        with pytest.raises(RendererError):
            validate_component(kind, params)


def test_model_effect_cannot_escape_asset_root(tmp_path):
    from renderers.service import VideoRenderer

    outside = tmp_path / "private.wav"
    outside.write_bytes(b"x" * 100)
    plan = {
        "metadata": {},
        "scenes": [
            {
                "scene_id": "s1",
                "renderer": "canvas",
                "duration": 1,
                "audio": {"effects": [{"path": str(outside)}]},
            }
        ],
    }
    with pytest.raises(RendererError, match="assets/audio"):
        VideoRenderer({"tts_enabled": False, "project_root": tmp_path}).render(plan, tmp_path / "out")


@pytest.mark.parametrize("planned_duration", [2, 20])
def test_narration_controls_duration_without_dead_air(tmp_path, monkeypatch, planned_duration):
    import renderers.service as service

    durations = []

    class FakeFFmpeg:
        def __init__(self, settings):
            pass

        def duration(self, path):
            return 5.0

        def trim_narration(self, source, target):
            target.write_bytes(b"voice" * 20)
            return {"duration": 5.0}

        def normalize(self, video, clip, metadata, duration, voice, effects, voice_offset=0):
            assert voice_offset == .15
            durations.append(duration)
            clip.write_bytes(b"video" * 20)

        def compose(self, clips, output, metadata, durations, transition, speed):
            output.write_bytes(b"joined" * 20)
            assert speed == 1.15
            return {"expected_duration": durations[0] / speed}

        def run(self, args):
            return ""

    class FakeTTS:
        def __init__(self, settings):
            pass

        def synthesize(self, text, output):
            output.write_bytes(b"voice" * 20)
            return output

    class Adapter:
        def render(self, scene, metadata, folder):
            path = folder / "raw.mp4"
            path.write_bytes(b"frame" * 20)
            return path

    monkeypatch.setattr(service, "FFmpeg", FakeFFmpeg)
    monkeypatch.setattr(service, "MiniMaxTTS", FakeTTS)
    monkeypatch.setattr(service.VideoRenderer, "adapter", lambda self, name: Adapter())
    plan = {
        "metadata": {},
        "scenes": [{"scene_id": "s1", "renderer": "canvas", "duration": planned_duration, "narration": "口播"}],
    }
    service.VideoRenderer({"tts_enabled": True, "minimax_api_key": "fake"}).render(plan, tmp_path)
    assert durations == [5.4]
    effective = json.loads((tmp_path / "effective_storyboard.json").read_text(encoding="utf-8"))
    assert effective["scenes"][0]["duration"] == 5.4
    assert effective["scenes"][0]["audio"]["narration_duration"] == 5.0
    assert plan["scenes"][0]["duration"] == planned_duration


@pytest.mark.parametrize("durations,transition", [([5.4, 8.4, 6.4], .3), ([5.4], .3), ([.2, .2], 1), ([3, 4], 0)])
def test_composition_preserves_speech_and_retimes_both_tracks(tmp_path, durations, transition):
    ff = object.__new__(FFmpeg)
    captured = []

    def run(args):
        captured.extend(args)
        Path(args[-1]).write_bytes(b"encoded" * 20)

    ff.run = run
    result = ff.compose([tmp_path / f"{i}.mp4" for i in range(len(durations))], tmp_path / "final.mp4",
                        {"fps": 30}, durations, transition, 1.15)
    graph = captured[captured.index("-filter_complex") + 1]
    assert "setpts=(PTS-STARTPTS)/1.15" in graph
    assert "atempo=1.15" in graph
    assert "acrossfade" not in graph, "Speech must not overlap or lose consonants to a fade"
    assert len(result["transitions"]) == len(durations) - 1
    overlap = sum(t["duration"] for t in result["transitions"]) * 1.15
    assert result["expected_duration"] == pytest.approx((sum(durations) - overlap) / 1.15)
    if durations == [5.4, 8.4, 6.4]:
        assert "[1:a]atrim=start=0.150000:end=8.250000" in graph
        assert result["transitions"][0]["start"] == pytest.approx(5.1 / 1.15)
