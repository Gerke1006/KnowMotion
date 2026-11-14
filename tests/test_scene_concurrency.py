"""Isolated scheduler checks; fixture media are never live video acceptance."""
import json
from pathlib import Path
import threading

import pytest

from harness.settings import Settings
import renderers.service as service


@pytest.mark.parametrize("configuration,limit", [("settings_default", 4), ("fallback_default", 4),
                                                 ("explicit_two", 2)])
def test_scene_workers_overlap_within_limit_and_preserve_composition_order(
    tmp_path, monkeypatch, configuration, limit,
):
    monkeypatch.delenv("RENDER_CONCURRENCY", raising=False)
    settings = {"tts_enabled": False, "bgm_path": "", "video_validation_enabled": False}
    if configuration == "settings_default":
        settings = Settings(_env_file=None, **settings)
    elif configuration == "explicit_two":
        settings["render_concurrency"] = 2

    lock = threading.Lock()
    barrier = threading.Barrier(limit)
    second_finished = threading.Event()
    active = peak = 0
    completed = []
    composed = []
    scene_ids = [f"scene_{index}" for index in range(8)]

    class Adapter:
        def render(self, scene, metadata, folder):
            nonlocal active, peak
            index = int(scene["scene_id"].split("_")[-1])
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                # Each batch must actually overlap, rather than merely declaring
                # a pool size. Incorrect lower limits fail this bounded wait.
                barrier.wait(timeout=5)
                if index == 0:
                    assert second_finished.wait(5)
                path = folder / "raw.mp4"
                path.write_bytes(b"isolated non-video fixture" * 4)
                with lock:
                    completed.append(scene["scene_id"])
                if index == 1:
                    second_finished.set()
                return path
            finally:
                with lock:
                    active -= 1

    class Media:
        def __init__(self, settings):
            pass

        def normalize(self, video, clip, metadata, duration, voice, effects, **kwargs):
            clip.write_bytes(video.read_bytes())

        def compose(self, clips, output, metadata, durations, transition, speed):
            composed.extend(clip.parent.name for clip in clips)
            output.write_bytes(b"isolated non-video composition" * 4)
            return {"expected_duration": 8.0}

        def duration(self, path):
            return 8.0

    monkeypatch.setattr(service, "FFmpeg", Media)
    monkeypatch.setattr(service.VideoRenderer, "adapter", lambda self, name: Adapter())
    plan = {"metadata": {}, "scenes": [{"scene_id": name, "renderer": "canvas", "duration": 1}
                                       for name in scene_ids]}
    final = service.VideoRenderer(settings).render(plan, tmp_path / "isolated-render")

    assert final.is_file()
    assert active == 0 and peak == limit
    assert completed.index("scene_1") < completed.index("scene_0")
    assert composed == scene_ids
    report = json.loads((Path(final).parent / "render_report.json").read_text(encoding="utf-8"))
    assert [scene["scene_id"] for scene in report["scenes"]] == scene_ids
    assert report["validation_performed"] is False
