"""Isolated production integration; fake providers/media are never live acceptance.

Every file is confined to pytest's temporary directory. HTTP uses MockTransport;
the actual project gateway, director compiler, orchestration and audit are exercised.
"""
import copy
import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from harness.history_director import DirectorValidationError
from harness.model_gateway import ModelGateway
from harness.orchestrator import Orchestrator
from harness.production_audit import FrozenRun, save_json
from harness.schemas import Domain, JobCreate, VideoRequest
from harness.settings import Settings
from storage.repository import JobRepository
import workflows.history_production as production


@pytest.fixture
def isolated_production(tmp_path, monkeypatch):
    root = tmp_path / "isolated_project"
    root.mkdir()
    resources = {
        "schema_version": "2.0", "environments": [{"id": "road", "description": "Isolated fixture"}],
        "visual_assets": [{"id": "actor.person", "actions": ["walk", "enter", "emphasize"],
                           "parameters": {"type": "object", "additionalProperties": False}}],
        "sfx_assets": [{"id": "sfx.footstep", "description": "Isolated fixture sound"}],
    }
    save_json(root / "assets/catalog.json", {"assets": []})
    save_json(root / "assets/history/animation_resources.json", resources)
    music = root / "assets/audio/fixture.m4a"
    music.parent.mkdir(parents=True)
    music.write_bytes(b"isolated fake music, never playable or delivered" * 4)
    cfg = Settings(_env_file=None, project_root=root, output_dir=tmp_path / "runs",
                   database_url="sqlite:///:memory:", model_name="isolated-test-model",
                   model_base_url="https://isolated.invalid/v1", model_api_key="isolated-test-key",
                   minimax_api_key="isolated-tts-key", bgm_path=str(music), render_concurrency=1,
                   playback_speed=1.15, transition_duration=.3, narration_gap=.08, model_retries=0)
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="隔离测试：古代工匠交流", domain=Domain.history, mode="live"))
    request = VideoRequest(topic=job.topic, domain=Domain.history, mode="live")
    work = cfg.output_dir / job.id
    audit = FrozenRun(cfg, work, job.topic)
    source = {"id": "source_01", "title": "Isolated archive fixture", "url": "https://example.org/archive",
              "excerpt": "An isolated invented test record.", "status": "retrieved"}
    findings = {"mode": "live", "topic": job.topic, "sources": [source], "knowledge": ["隔离测试记录"]}
    script = {"title": "隔离测试标题", "segments": [
        {"id": f"segment_{index}", "narration": "甲乙丙丁戊己庚辛壬癸" * 8,
         "source_ids": ["source_01"], "intent": f"隔离测试意图{index}"} for index in range(5)]}
    scenes = []
    for index, segment in enumerate(script["segments"]):
        scenes.append({"scene_id": f"scene_{index}", "segment_id": segment["id"], "environment": "road",
                       "objects": [{"id": "figure", "asset_id": "actor.person", "x": .2, "y": .7,
                                    "scale": 1, "facing": 1, "label": "", "parameters": {}}],
                       "beats": [{"id": f"beat_{beat}",
                                  "anchor": {"quote": "甲乙", "occurrence": 1 + beat * 2, "edge": "start"},
                                  "visible_ids": ["figure"], "focus_id": "figure", "keywords": [],
                                  "actions": [{"target_id": "figure", "kind": "walk",
                                               "to_x": .3 + beat * .1, "to_y": .7}],
                                  "camera": {"x": .5, "y": .5, "zoom": 1},
                                  "sfx": {"asset_id": "sfx.footstep", "align": "onset", "gain_db": 0}
                                  if beat < 3 else None} for beat in range(4)]})
    plan = {"schema_version": "2.0", "style_id": "gufeng", "scenes": scenes}
    observed = SimpleNamespace(stages=[], narrated=[], rendered=[], events=[], duration=0.0,
                               invalid_initial=False, malformed_initial=False, invalid_repair=False,
                               frame_failure=False)

    def model_response(http_request):
        assert http_request.url.host == "isolated.invalid"
        stage = gateway.stage
        observed.stages.append(stage)
        content = {"research": findings, "teaching": script, "director": plan, "director_repair": plan}[stage]
        content = copy.deepcopy(content)
        if stage == "director" and observed.malformed_initial:
            text = "{not a valid JSON response"
        else:
            if (stage == "director" and observed.invalid_initial) or (stage == "director_repair" and observed.invalid_repair):
                content["scenes"][0]["environment"] = "not_in_catalog"
            text = json.dumps(content, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 1}})

    gateway = ModelGateway(cfg, transport=httpx.MockTransport(model_response), audit_path=work / "model_calls.json")

    async def fake_research(current_request, current_gateway):
        assert current_request.topic == job.topic
        return await current_gateway.generate_json("Isolated research fixture only", "{}")

    class Audio:
        def __init__(self, settings):
            assert settings.model_name == "isolated-test-model"

        def synthesize_aligned(self, text, output):
            observed.narrated.append(text)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"isolated fake audio" * 8)
            words = [{"text": character, "char_start": index, "char_end": index + 1,
                      "start": .4 + .16 * index, "end": .4 + .16 * (index + 1)}
                     for index, character in enumerate(text)]
            alignment = output.with_suffix(".alignment.json")
            save_json(alignment, {"words": words})
            return {"audio_path": str(output), "alignment_path": str(alignment), "words": words,
                    "provider": "isolated-fixture", "trace_id": "fixture"}

    class Media:
        def __init__(self, _settings):
            pass

        def trim_narration(self, audio, output):
            output.write_bytes(audio.read_bytes())
            return {"trim_start": .4, "duration": 12.8}

        def normalize(self, video, output, metadata, duration, voice, **kwargs):
            assert kwargs["voice_offset"] == .15 and voice.is_file()
            output.write_bytes(video.read_bytes())

        def compose(self, clips, output, metadata, durations, transition, speed):
            assert all(path.is_file() for path in clips)
            observed.duration = (sum(durations) - transition * (len(durations) - 1)) / speed
            output.write_bytes(b"isolated fake joined video" * 8)
            return {"expected_duration": observed.duration, "playback_speed": speed,
                    "transitions": [{"start": 1, "end": 1.3}] * (len(durations) - 1)}

        def duration(self, _path):
            return observed.duration

        def run(self, _args):
            return ""

    class Adapter:
        def __init__(self, _settings):
            pass

        def preflight(self, **_kwargs):
            pass

        def generate(self, scene, metadata, folder):
            target = folder / "props.json"
            save_json(target, {"scene": scene, "metadata": metadata})
            return target

        def check_director(self, props, report):
            assert json.loads(props.read_text(encoding="utf-8"))["scene"]["director"]["protocol"] == "history-director-v2"
            checked = {"passed": not observed.frame_failure}
            if observed.frame_failure:
                checked["errors"] = [{"code": "isolated_frame_failure"}]
            save_json(report, checked)
            return checked

        def render(self, scene, metadata, folder):
            observed.rendered.append(copy.deepcopy(scene))
            output = folder / "raw.mp4"
            output.write_bytes(b"isolated fake rendered video" * 8)
            return output

    def fake_mix(ffmpeg, joined, final, events, assets, bgm, gain, folder):
        assert all(assets[key] == value for key, value in resources.items())
        assert gain == .3 and bgm == str(music)
        observed.events = copy.deepcopy(events)
        final.write_bytes(joined.read_bytes())
        return {"fixture_only": True, "events": [{**event, "alignment_error_seconds": 0} for event in events],
                "event_count": len(events), "playback_speed_applied_here": False,
                "bgm": {"enabled": True, "configured_gain": gain},
                "levels": {"final_mix": {"max_dbfs": -1.5}}}

    def fake_inspection(folder, report, settings):
        result = {"max_boundary_silence": 0, "black_intervals": 0}
        save_json(folder / "media_verification.json", result)
        return result

    monkeypatch.setattr(production, "research", fake_research)
    monkeypatch.setattr(production, "MiniMaxTTS", Audio)
    monkeypatch.setattr(production, "FFmpeg", Media)
    monkeypatch.setattr(production, "RemotionRenderer", Adapter)
    monkeypatch.setattr(production, "mix_history_audio", fake_mix)
    monkeypatch.setattr(production, "inspect_media", fake_inspection)

    def runner():
        return production.HistoryProduction(cfg, repository, repository.get(job.id), request, gateway, audit)

    yield SimpleNamespace(settings=cfg, repository=repository, job=job, request=request, work=work,
                          audit=audit, gateway=gateway, script=script, plan=plan, findings=findings,
                          observed=observed, runner=runner)
    repository.close()


async def test_complete_isolated_production_preserves_gateway_authored_content(isolated_production):
    setup = isolated_production
    result = await setup.runner().run()
    assert result.status == "succeeded"
    assert setup.observed.stages == ["research", "teaching", "director"]
    assert setup.observed.narrated == [segment["narration"] for segment in setup.script["segments"]]
    written = json.loads((setup.work / "narration_script.json").read_text(encoding="utf-8"))
    assert written == setup.script
    rendered = [scene["narration"] for scene in setup.observed.rendered]
    assert rendered == setup.observed.narrated
    assert setup.audit.verify()["artifact_hashes_valid"]
    calls = json.loads((setup.work / "model_calls.json").read_text(encoding="utf-8"))
    assert all(call["status"] == "succeeded" for call in calls)
    assert all((setup.work / call["response_artifact"]).is_file() for call in calls)
    acceptance = json.loads((setup.work / "live_acceptance.json").read_text(encoding="utf-8"))
    assert acceptance["input"] == {"topic": setup.job.topic}
    assert all(acceptance["checks"].values())
    assert len(setup.observed.events) == 15
    assert setup.observed.events[3]["at"] == pytest.approx((13.2 - .3 + .15) / 1.15)


@pytest.mark.parametrize("scene_limit", [1, 4])
async def test_history_scene_parallelism_honors_configured_limit(isolated_production, monkeypatch, scene_limit):
    """Exercise real scheduling with blocked fixture renderers, not a video acceptance run."""
    setup = isolated_production
    cfg = setup.settings.model_copy(update={"render_concurrency": scene_limit})
    job = setup.repository.create(JobCreate(topic=setup.job.topic, domain=Domain.history, mode="live"))
    folder = cfg.output_dir / job.id
    audit = FrozenRun(cfg, folder, job.topic)
    setup.gateway.settings = cfg
    setup.gateway.audit_path = folder / "model_calls.json"
    original_render = production.RemotionRenderer.render
    lock, full, release = threading.Lock(), threading.Event(), threading.Event()
    entered = []
    active = peak = 0

    def blocked_render(self, scene, metadata, work):
        nonlocal active, peak
        with lock:
            entered.append(scene["scene_id"])
            active += 1
            peak = max(peak, active)
            if active == scene_limit:
                full.set()
        try:
            assert release.wait(20), "Fixture render workers were not released"
            return original_render(self, scene, metadata, work)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(production.RemotionRenderer, "render", blocked_render)
    runner = production.HistoryProduction(cfg, setup.repository, job, setup.request, setup.gateway, audit)
    task = asyncio.create_task(runner.run())
    try:
        assert await asyncio.to_thread(full.wait, 10), "Configured scene parallelism was not reached"
        await asyncio.sleep(.03)
        assert len(entered) == scene_limit, "A scene escaped the configured bound"
    finally:
        release.set()
        result = await task
    assert result.status == "succeeded"
    assert peak == scene_limit
    assert len(entered) == len(setup.plan["scenes"])
    report = json.loads((folder / "render_report.json").read_text(encoding="utf-8"))
    assert [scene["scene_id"] for scene in report["scenes"]] == [scene["scene_id"] for scene in setup.plan["scenes"]]


async def test_new_history_production_enforces_and_records_narration_bindings(isolated_production):
    setup = isolated_production
    cfg = setup.settings.model_copy(update={"history_narrative_bindings": True})
    job = setup.repository.create(JobCreate(topic=setup.job.topic, domain=Domain.history, mode="live"))
    folder = cfg.output_dir / job.id
    audit = FrozenRun(cfg, folder, job.topic)
    setup.gateway.settings = cfg
    setup.gateway.audit_path = folder / "model_calls.json"
    # A name introduced in the first segment must stay known during later
    # narration, in both director validation and the production compiler.
    first = setup.script["segments"][0]
    first["narration"] = "工匠阿明" + first["narration"][4:]
    setup.plan["scenes"][0]["beats"][0]["anchor"]["quote"] = "工匠阿明"
    for beat in setup.plan["scenes"][0]["beats"][1:]:
        beat["anchor"]["occurrence"] -= 1
    for scene, segment in zip(setup.plan["scenes"], setup.script["segments"]):
        scene["objects"][0]["label"] = "阿明"
        scene["objects"][0]["evidence_quote"] = "工匠阿明"
        for beat in scene["beats"]:
            beat["evidence_quote"] = segment["narration"]
            beat["evidence_by_object"] = {"figure": "甲乙"}
    runner = production.HistoryProduction(cfg, setup.repository, job, setup.request, setup.gateway, audit)
    result = await runner.run()
    assert result.status == "succeeded"
    report = json.loads((folder / "narrative_execution.json").read_text(encoding="utf-8"))
    assert report["required"] and all(scene["passed"] for scene in report["scenes"])
    assert all(not scene["legacy_unbound"] for scene in report["scenes"])
    assert report["diversity"]["enforced_quota"] is False
    acceptance = json.loads((folder / "live_acceptance.json").read_text(encoding="utf-8"))
    assert acceptance["checks"]["narration_visual_bindings"]
    assert setup.observed.stages == ["research", "teaching", "director"]


async def test_model_json_format_failure_has_one_runtime_repair(isolated_production):
    setup = isolated_production
    setup.observed.malformed_initial = True
    result = await setup.runner().run()
    assert result.status == "succeeded"
    assert setup.observed.stages.count("director_repair") == 1
    state = json.loads((setup.work / "production_state.json").read_text(encoding="utf-8"))
    assert state["director_repairs"] == 1
    initial = json.loads((setup.work / "director_plan.initial.json").read_text(encoding="utf-8"))
    assert initial == "{not a valid JSON response"
    assert json.loads((setup.work / "narration_script.json").read_text(encoding="utf-8")) == setup.script
    calls = json.loads((setup.work / "model_calls.json").read_text(encoding="utf-8"))
    repaired_call = next(call["call_id"] for call in calls if call["stage"] == "director_repair")
    records = json.loads((setup.work / "artifact_records.json").read_text(encoding="utf-8"))["artifacts"]
    assert repaired_call in records["director_plan.json"]["producer_call_ids"]


async def test_second_invalid_director_does_not_trigger_another_repair(isolated_production):
    setup = isolated_production
    setup.observed.invalid_initial = setup.observed.invalid_repair = True
    with pytest.raises(DirectorValidationError):
        await setup.runner().run()
    assert setup.observed.stages.count("director_repair") == 1
    resumed = setup.runner()
    with pytest.raises(DirectorValidationError):
        await resumed.repair(setup.script, setup.findings, {}, setup.plan,
                             DirectorValidationError([{"code": "test", "path": "", "message": "isolated"}]))
    assert setup.observed.stages.count("director_repair") == 1
    assert not setup.observed.narrated


async def test_contract_and_frame_failures_share_one_repair_budget(isolated_production):
    setup = isolated_production
    setup.observed.malformed_initial = setup.observed.frame_failure = True
    with pytest.raises(DirectorValidationError, match="frame_contract"):
        await setup.runner().run()
    assert setup.observed.stages.count("director_repair") == 1
    assert len(setup.observed.narrated) == 5
    assert not setup.observed.rendered


async def test_edited_checkpoint_is_rejected_before_any_new_model_call(isolated_production):
    setup = isolated_production
    await setup.runner().run()
    path = setup.work / "narration_script.json"
    forged = copy.deepcopy(setup.script)
    forged["segments"][0]["narration"] = "庚" * 80
    save_json(path, forged)
    stages = setup.observed.stages.copy()
    with pytest.raises(ValueError, match="changed outside"):
        await setup.runner().run()
    assert setup.observed.stages == stages


async def test_valid_checkpoint_resume_preserves_script_and_paid_call_count(isolated_production):
    setup = isolated_production
    await setup.runner().run()
    calls, narration = setup.observed.stages.copy(), setup.observed.narrated.copy()
    result = await setup.runner().run()
    assert result.status == "succeeded"
    assert setup.observed.stages == calls
    assert setup.observed.narrated == narration
    assert json.loads((setup.work / "narration_script.json").read_text(encoding="utf-8")) == setup.script


async def test_generated_checkpoints_link_to_their_producer_calls(isolated_production):
    setup = isolated_production
    await setup.runner().run()
    calls = json.loads((setup.work / "model_calls.json").read_text(encoding="utf-8"))
    by_stage = {call["stage"]: call["call_id"] for call in calls if call["status"] == "succeeded"}
    records = json.loads((setup.work / "artifact_records.json").read_text(encoding="utf-8"))["artifacts"]
    assert by_stage["teaching"] in records["narration_script.json"]["producer_call_ids"]
    assert by_stage["director"] in records["director_plan.json"]["producer_call_ids"]


@pytest.mark.parametrize("filename", ["director_plan.json", "speech_manifest.json"])
async def test_unrecorded_checkpoints_are_never_accepted(isolated_production, filename):
    setup = isolated_production
    save_json(setup.work / filename, setup.plan if filename == "director_plan.json" else {})
    with pytest.raises(ValueError, match="[Uu]nrecorded"):
        await setup.runner().run()


def test_final_sfx_clock_applies_overlap_then_speed_once():
    cue = {"asset_id": "sfx.tap", "align": "peak", "gain_db": -1}
    scenes = [{"scene_id": "first", "duration": 10, "beats": [{"id": "a", "anchor_time": .2, "sfx": cue}]},
              {"scene_id": "second", "duration": 8, "beats": [{"id": "b", "anchor_time": 1.5, "sfx": cue}]}]
    events = production.final_sound_events(scenes, 1.15, .3)
    assert events[0]["at"] == pytest.approx(.2 / 1.15)
    assert events[1]["at"] == pytest.approx((10 - .3 + 1.5) / 1.15)
    assert events[1]["align"] == "peak" and events[1]["gain_db"] == -1
    assert scenes[1]["beats"][0]["anchor_time"] == 1.5


async def test_orchestrator_routes_history_through_frozen_director_pipeline(isolated_production):
    setup = isolated_production
    result = await Orchestrator(setup.settings, setup.repository, gateway=setup.gateway).run(setup.job.id)
    assert result.status == "succeeded", result.error
    assert setup.observed.stages == ["research", "teaching", "director"]
    manifest = json.loads((setup.work / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["input"] == {"topic": setup.job.topic}
    assert manifest["profile"] == "history-animation-v2"
    assert (setup.work / "video_request.json").is_file()
    assert not (setup.work / "teaching_plan.json").exists()


async def test_orchestrator_closes_failed_frozen_runs_instead_of_restarting_model(isolated_production):
    setup = isolated_production
    setup.observed.invalid_initial = setup.observed.invalid_repair = True
    runner = Orchestrator(setup.settings, setup.repository, gateway=setup.gateway)
    first = await runner.run(setup.job.id)
    assert first.status == "failed"
    stages = setup.observed.stages.copy()
    second = await runner.run(setup.job.id)
    assert second.status == "failed" and "closed" in second.error
    assert setup.observed.stages == stages


def test_formal_history_entry_rejects_per_run_generation_overrides():
    from scripts.verify_history import main
    with pytest.raises(SystemExit) as error:
        main(["--topic", "隔离测试", "--duration", "80"])
    assert error.value.code == 2


def test_history_api_and_cli_share_frozen_transport_capacity(isolated_production):
    from harness.history_profile import history_settings
    settings = isolated_production.settings
    save_json(settings.project_root / "assets/history/production_profile.json",
              {"model_max_tokens": 16000, "model_timeout": 600.0})
    configured = history_settings(settings)
    assert configured.model_max_tokens == 16000 and configured.model_timeout == 600
    assert configured.model_name == settings.model_name
    assert settings.model_max_tokens == 8000 and settings.model_timeout == 180


async def test_formal_history_entry_uses_profile_and_always_creates_new_job(isolated_production, monkeypatch):
    from scripts import verify_history
    setup = isolated_production
    profile = {"id": "history-animation-v2", "version": "2.0", "duration_budget": 90,
               "target_final_duration": [75, 90], "narration_char_budget": 440,
               "width": 1280, "height": 720, "fps": 30, "playback_speed": 1.15,
               "style_id": "gufeng", "sfx_per_minute": [12, 18], "director_repairs": 1,
               "transport_attempts": 3, "runtime_ai_review": False}
    save_json(setup.settings.project_root / "assets/history/production_profile.json", profile)
    monkeypatch.setattr(verify_history, "Settings", lambda: setup.settings)
    observed = []

    class IsolatedEntryOrchestrator:
        def __init__(self, settings, repository):
            self.settings, self.repository = settings, repository

        async def run(self, job_id):
            record = self.repository.get(job_id)
            observed.append(record.request)
            assert self.settings.model_max_tokens >= 16000
            assert self.settings.model_timeout >= 600
            assert self.settings.model_name == setup.settings.model_name
            assert self.settings.tts_speed == 1 and self.settings.model_retries == 2
            folder = self.settings.output_dir / job_id
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / "final.mp4"
            output.write_bytes(b"isolated entry fixture only" * 4)
            save_json(folder / "live_acceptance.json", {
                "job_id": job_id, "protocol": "history-director-v2", "input": {"topic": record.topic},
                "model": self.settings.model_name, "duration": 80, "checks": {"isolated_fixture": True},
                "model_calls": 3, "director_repairs": 0,
            })
            return self.repository.update(job_id, status="succeeded", output_path=str(output), stage="complete")

    monkeypatch.setattr(verify_history, "Orchestrator", IsolatedEntryOrchestrator)
    first = await verify_history.verify("隔离测试主题")
    second = await verify_history.verify("隔离测试主题")
    assert first["job_id"] != second["job_id"]
    assert len(observed) == 2
    assert all(request.mode == "live" and request.domain == Domain.history and request.duration == 90
               and request.narration_char_budget == 440 and request.fps == 30 for request in observed)


def test_formal_entry_output_redacts_configured_credentials(isolated_production):
    from scripts.verify_history import public_text
    settings = isolated_production.settings
    output = public_text({"unexpected_echo": settings.model_api_key.get_secret_value()}, settings)
    assert settings.model_api_key.get_secret_value() not in output
    assert "[REDACTED]" in output


async def test_history_cancellation_holds_lock_until_background_work_exits(isolated_production, monkeypatch):
    from filelock import FileLock, Timeout
    setup = isolated_production
    started, release = threading.Event(), threading.Event()
    def blocked_preflight(self, **kwargs):
        started.set()
        assert release.wait(5)
    monkeypatch.setattr(production.RemotionRenderer, "preflight", blocked_preflight)
    task = asyncio.create_task(Orchestrator(setup.settings, setup.repository, gateway=setup.gateway).run(setup.job.id))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(.01)
        assert started.is_set()
        task.cancel()
        await asyncio.sleep(.03)
        assert not task.done()
        with pytest.raises(Timeout):
            FileLock(setup.work / ".production.lock").acquire(timeout=0)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    with FileLock(setup.work / ".production.lock", timeout=0):
        pass
