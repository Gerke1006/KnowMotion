"""Independent history production: a topic and frozen resources, with no developer-authored lesson."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time

from pydantic import BaseModel

from harness.asset_retriever import AssetRetriever
from harness.history_director import (
    DirectorValidationError, HistoryScript, compile_scene, validate_director,
    validate_film_timeline, validation_errors,
)
from harness.model_gateway import ModelError
from harness.orchestrator import finish_thread
from harness.media_clock import composition_clock
from harness.production_audit import FrozenRun, save_json
from harness.schemas import JobStatus
from renderers.audio import MiniMaxTTS
from renderers.base import RendererError
from renderers.ffmpeg import FFmpeg
from renderers.history_sound import mix_history_audio
from renderers.media_checks import inspect_media
from renderers.remotion import RemotionRenderer
from workflows.history_director import generate_director, generate_script, repair_director
from workflows.research import research


def data(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def scene_payload(resolved):
    return {"scene_id": resolved["scene_id"], "title": resolved["title"],
            "narration": resolved["narration"], "duration": resolved["duration"], "components": [],
            "extensions": {"historical_sources": resolved["sources"]}, "director": resolved}


def final_sound_events(resolved, speed, transition, fps=30):
    """The same overlap and rate transform used by FFmpeg.compose, applied once."""
    events = []
    clock = composition_clock([scene["duration"] for scene in resolved], fps, transition, speed)
    for scene, base_start in zip(resolved, clock["scene_starts"]):
        for beat in scene["beats"]:
            if beat.get("sfx"):
                events.append({"cue_id": f'{scene["scene_id"]}:{beat["id"]}', **beat["sfx"],
                               "at": (base_start + beat["anchor_time"]) / speed})
    return events


class HistoryProduction:
    def __init__(self, settings, repository, record, request, gateway, audit: FrozenRun):
        self.settings, self.repository, self.record = settings, repository, record
        self.request, self.gateway, self.audit = request, gateway, audit
        self.work = audit.folder
        self.artifacts = dict(record.artifacts)
        self.attempts = []
        state = self.work / "production_state.json"
        if state.is_file() and "production_state.json" not in json.loads(
                audit.records_path.read_text(encoding="utf-8"))["artifacts"]:
            raise ValueError("Unrecorded production state cannot be reused")
        self.state = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {"director_repairs": 0}

    def update(self, stage, progress):
        self.repository.update(self.record.id, status=JobStatus.running, stage=stage, progress=progress,
                               error=None, artifacts=dict(self.artifacts))

    def remember(self, stage, paths, *, origin="deterministic", inputs=None):
        if inputs is None:
            dependencies = {
                "research": ["video_request.json"], "teaching": ["research.json"],
                "assets": ["narration_script.json"],
                "director": ["narration_script.json", "research.json", "candidate_resources.json"],
                "director_initial": ["narration_script.json", "research.json", "candidate_resources.json"],
                "director_repair": ["narration_script.json", "research.json", "candidate_resources.json",
                                    "director_validation_errors.json"],
                "minimax": ["narration_script.json"],
                "remotion": ["resolved_timeline.json", "speech_manifest.json"],
                "ffmpeg": ["resolved_timeline.json", "speech_manifest.json", "director_execution.json"],
            }
            inputs = [self.work / name for name in dependencies.get(stage, [])]
        call_ids = []
        if "model" in origin and (self.work / "model_calls.json").is_file():
            calls = json.loads((self.work / "model_calls.json").read_text(encoding="utf-8"))
            wanted = "director" if stage == "director_initial" else stage
            if stage == "director":
                candidates = [c for c in calls if c.get("stage") in {"director", "director_repair"}
                              and c.get("status") == "succeeded"]
                call_ids = [candidates[-1]["call_id"]] if candidates else []
            else:
                call_ids = [c["call_id"] for c in calls if c.get("stage") == wanted]
        self.audit.record(stage, paths, origin=origin, inputs=inputs, call_ids=call_ids)
        self.audit.record_model_calls()
        for path in paths:
            self.artifacts[Path(path).relative_to(self.work).as_posix()] = str(Path(path).resolve())

    async def checkpoint(self, stage, progress, filename, contract, action, *, origin="configured_model"):
        self.audit.verify()
        self.update(stage, progress)
        path = self.work / filename
        records = json.loads(self.audit.records_path.read_text(encoding="utf-8"))["artifacts"]
        if path.is_file():
            if filename not in records:
                raise ValueError(f"Unrecorded checkpoint cannot be reused: {filename}")
            raw = json.loads(path.read_text(encoding="utf-8"))
            return contract.model_validate(raw) if contract else raw
        self.gateway.stage = stage
        value = action()
        if hasattr(value, "__await__"):
            value = await value
        save_json(path, data(value))
        self.remember(stage, [path], origin=origin)
        return value

    async def repair(self, script, findings, resources, prior, error):
        if self.state["director_repairs"] >= 1:
            raise error
        self.state["director_repairs"] += 1
        state = self.work / "production_state.json"
        save_json(state, self.state)
        self.remember("director_repair_budget", [state])
        errors = validation_errors(error)
        if getattr(error, "checks", None):
            errors.append({"code": "timing_measurements", "path": "", "message": json.dumps(error.checks)})
        save_json(self.work / "director_validation_errors.json", {"errors": errors})
        self.remember("director_validation", [self.work / "director_validation_errors.json"])
        self.update("visual", .48)
        result = await repair_director(script, findings, resources, data(prior), errors, self.gateway)
        save_json(self.work / "director_plan.repaired.json", data(result))
        self.remember("director_repair", [self.work / "director_plan.repaired.json"], origin="configured_model")
        return result

    def retry_render(self, name, action):
        for attempt in range(1, 4):
            try:
                value = action()
                self.attempts.append({"operation": name, "attempt": attempt, "status": "succeeded"})
                return value
            except RendererError as error:
                self.attempts.append({"operation": name, "attempt": attempt, "status": "failed",
                                      "error_type": type(error).__name__})
                if attempt == 3:
                    raise
                time.sleep(attempt)

    async def run(self):
        cfg = self.settings
        if cfg.tts_speed != 1 or not cfg.tts_enabled:
            raise ValueError("History v2 requires TTS_SPEED=1 and enabled MiniMax; playback speed is applied only once")
        self.gateway.settings = self.gateway.settings.model_copy(update={"model_retries": min(2, cfg.model_retries)})
        ffmpeg, adapter = FFmpeg(cfg), RemotionRenderer(cfg)
        # Technical dependencies are checked before requesting new paid speech.
        await finish_thread(adapter.preflight, ensure_browser=True)
        findings = await self.checkpoint("research", .15, "research.json", None,
                                        lambda: research(self.request, self.gateway), origin="retrieved_and_configured_model")
        script = await self.checkpoint("teaching", .28, "narration_script.json", HistoryScript,
                                      lambda: generate_script(self.request, findings, self.gateway))
        resources = await self.checkpoint("assets", .35, "candidate_resources.json", None,
                                         lambda: AssetRetriever(cfg.asset_catalog_path).history_candidates(script.segments),
                                         origin="frozen_resources")
        director_path = self.work / "director_plan.json"
        if director_path.is_file():
            self.audit.verify()
            if "director_plan.json" not in json.loads(self.audit.records_path.read_text(encoding="utf-8"))["artifacts"]:
                raise ValueError("Unrecorded checkpoint cannot be reused: director_plan.json")
            plan = validate_director(json.loads(director_path.read_text(encoding="utf-8")), script, resources, findings)
        else:
            self.update("visual", .40)
            self.audit.verify()
            try:
                plan = await generate_director(script, findings, resources, self.gateway)
            except (DirectorValidationError, ModelError) as error:
                if isinstance(error, ModelError) and error.code != "format":
                    raise
                prior = getattr(error, "prior_plan", self.gateway.last_response)
                save_json(self.work / "director_plan.initial.json", data(prior))
                self.remember("director_initial", [self.work / "director_plan.initial.json"], origin="configured_model")
                plan = await self.repair(script, findings, resources, prior, error)
            save_json(director_path, data(plan))
            self.remember("director", [director_path], origin="configured_model")

        self.audit.verify()
        self.update("generation", .52)
        speech_path = self.work / "speech_manifest.json"
        if speech_path.is_file():
            if "speech_manifest.json" not in json.loads(self.audit.records_path.read_text(encoding="utf-8"))["artifacts"]:
                raise ValueError("Unrecorded checkpoint cannot be reused: speech_manifest.json")
            voices = json.loads(speech_path.read_text(encoding="utf-8"))
        else:
            semaphore = asyncio.Semaphore(min(2, cfg.render_concurrency))

            async def narrate(segment):
                async with semaphore:
                    folder = self.work / "speech" / segment.id
                    def produce():
                        registered = json.loads(self.audit.records_path.read_text(encoding="utf-8"))["artifacts"]
                        if any(p.relative_to(self.work).as_posix() not in registered
                               for p in folder.rglob("*") if p.is_file()):
                            raise ValueError("Unrecorded voice checkpoint cannot be reused")
                        aligned = MiniMaxTTS(cfg).synthesize_aligned(segment.narration, folder / "narration.mp3")
                        trimmed = folder / "narration.trimmed.wav"
                        speech = ffmpeg.trim_narration(Path(aligned["audio_path"]), trimmed)
                        return {"segment_id": segment.id, "words": aligned["words"], "speech": speech,
                                "voice_file": str(trimmed), "audio_path": str(aligned["audio_path"]),
                                "alignment_path": str(aligned["alignment_path"]), "provider": aligned["provider"]}
                    return await finish_thread(produce)
            outcomes = await asyncio.gather(*(narrate(segment) for segment in script.segments), return_exceptions=True)
            voice_files = [p for p in (self.work / "speech").rglob("*") if p.is_file()]
            self.remember("minimax", voice_files, origin="minimax")
            failed = next((item for item in outcomes if isinstance(item, BaseException)), None)
            if failed:
                raise failed
            voices = {item["segment_id"]: item for item in outcomes}
            save_json(speech_path, voices)
            self.remember("speech_alignment", [speech_path], inputs=voice_files)

        fps, speed = self.request.fps, cfg.playback_speed
        transition = int(cfg.transition_duration * fps + 1e-8) / fps
        metadata = self.request.model_dump(mode="json")
        metadata.update(style="gufeng", schema_version="2.0", title=script.title, playback_speed=speed)
        segments = {segment.id: segment for segment in script.segments}

        def compile_and_check(candidate):
            resolved, frame_reports, errors, frame_failures = [], [], [], []
            for scene in candidate.scenes:
                voice = voices[scene.segment_id]
                try:
                    result = compile_scene(scene, segments[scene.segment_id], voice["words"], voice["speech"],
                                           resources, findings["sources"], findings.get("geography"),
                                           fps=fps, transition=transition, narration_gap=cfg.narration_gap)
                except DirectorValidationError as error:
                    errors.extend(validation_errors(error))
                    continue
                result["title"] = script.title
                folder = self.work / "scenes" / scene.scene_id
                props = adapter.generate(scene_payload(result), metadata, folder)
                checked = adapter.check_director(props, folder / "frame_execution.json")
                if not checked.get("passed", checked.get("ok", False)):
                    unique = {}
                    for issue in checked.get("issues", checked.get("errors", [])):
                        key = (issue.get("kind", issue.get("code")), issue.get("object_id"))
                        if key not in unique:
                            unique[key] = {**issue, "affected_frames": 0}
                        unique[key]["affected_frames"] += 1
                    details = {"issues": list(unique.values()),
                               "scene_id": scene.scene_id,
                               "unconsumed_actions": checked.get("unconsumed_actions", []),
                               "maximum_unchanged_semantic_seconds": checked.get("maximum_unchanged_semantic_seconds")}
                    frame_failures.append(details)
                    errors.append({"code": "frame_contract", "path": scene.scene_id,
                                   "message": "See complete frame_failures in timing_measurements for this scene"})
                resolved.append(result)
                frame_reports.append(checked)
            checks = {}
            if len(resolved) == len(candidate.scenes):
                try:
                    checks = validate_film_timeline(resolved, speed, transition)
                except DirectorValidationError as error:
                    errors.extend(validation_errors(error))
                    checks = getattr(error, "checks", {})
            if errors:
                error = DirectorValidationError(errors)
                error.checks = {**checks, "observed_windows": [
                    {"scene_id": s["scene_id"], "beat_id": b["id"],
                     "start": b["start"], "end": b["end"], "anchor_time": b["anchor_time"],
                     "final_seconds": round((b["end"] - b["start"]) / speed, 4)}
                    for s in resolved for b in s["beats"]],
                    "frame_failures": frame_failures,
                    "playback_speed": speed, "narration_offset": transition / 2,
                    "word_timebase": "untrimmed provider seconds; subtract trim_start, add narration_offset",
                    "observed_words": {key: {"words": voice["words"], "trim_start": voice["speech"]["trim_start"]}
                                       for key, voice in voices.items()}}
                raise error
            return resolved, frame_reports, checks

        self.audit.verify()
        self.update("generation", .62)
        try:
            resolved, frame_reports, timeline_checks = await finish_thread(compile_and_check, plan)
        except DirectorValidationError as error:
            plan = await self.repair(script, findings, resources, plan, error)
            save_json(director_path, data(plan))
            self.remember("director_repair", [director_path], origin="configured_model")
            resolved, frame_reports, timeline_checks = await finish_thread(compile_and_check, plan)
        sound_events = final_sound_events(resolved, speed, transition, fps)
        save_json(self.work / "resolved_timeline.json", {"schema_version": "2.0", "scenes": resolved,
                                                        "playback_speed": speed, "sound_events": sound_events,
                                                        "checks": timeline_checks})
        save_json(self.work / "director_execution.json", {"scenes": frame_reports, "checks": timeline_checks})
        storyboard = {"schema_version": "2.0", "domain": "history", "metadata": metadata,
                      "script": data(script), "director": data(plan), "scenes": resolved, "sources": findings["sources"]}
        save_json(self.work / "storyboard.json", storyboard)
        save_json(self.work / "video_plan.json", storyboard)
        self.remember("timeline_compiler", [self.work / name for name in
                      ("resolved_timeline.json", "director_execution.json", "storyboard.json", "video_plan.json")],
                      inputs=[director_path, speech_path])

        self.audit.verify()
        self.update("rendering", .72)
        semaphore = asyncio.Semaphore(min(2, cfg.render_concurrency))
        async def render_scene(scene):
            async with semaphore:
                folder = self.work / "scenes" / scene["scene_id"]
                voice = voices[scene["segment_id"]]
                def produce():
                    video = self.retry_render(scene["scene_id"], lambda: adapter.render(scene_payload(scene), metadata, folder))
                    clip = folder / "normalized.mp4"
                    ffmpeg.normalize(video, clip, metadata, scene["duration"], Path(voice["voice_file"]),
                                     voice_offset=transition / 2)
                    return {"scene_id": scene["scene_id"], "renderer": "remotion", "duration": scene["duration"],
                            "speech": voice["speech"], "narration_offset": transition / 2, "narration": "minimax",
                            "voice_id": cfg.minimax_voice_id, "voice_file": voice["voice_file"], "clip": str(clip)}
                return await finish_thread(produce)
        outcomes = await asyncio.gather(*(render_scene(scene) for scene in resolved), return_exceptions=True)
        save_json(self.work / "execution_attempts.json", self.attempts)
        scene_files = [p for p in (self.work / "scenes").rglob("*") if p.is_file()]
        self.remember("remotion", scene_files + [self.work / "execution_attempts.json"])
        failed = next((item for item in outcomes if isinstance(item, BaseException)), None)
        if failed:
            raise failed
        reports = outcomes
        self.audit.verify()
        joined, final = self.work / "joined.mp4", self.work / "final.mp4"
        composition = await finish_thread(ffmpeg.compose, [Path(r["clip"]) for r in reports], joined,
                                              metadata, [r["duration"] for r in reports], transition, speed)
        sound_report = await finish_thread(mix_history_audio, ffmpeg, joined, final, sound_events,
                                               resources, cfg.bgm_path, cfg.bgm_volume, self.work)
        report = {"director_protocol": "2.0", "scenes": reports, "composition": composition,
                  "duration": ffmpeg.duration(final), "bgm": cfg.bgm_path, "bgm_volume": cfg.bgm_volume,
                  "output": str(final), "checks": timeline_checks}
        save_json(self.work / "render_report.json", report)
        save_json(self.work / "sound_execution.json", sound_report)
        await finish_thread(ffmpeg.run, ["-v", "error", "-i", str(final), "-f", "null", "-"])
        media = await finish_thread(inspect_media, self.work, report, cfg)
        self.remember("ffmpeg", [p for p in self.work.iterdir() if p.is_file() and p.suffix in {".mp4", ".wav"}] +
                      [self.work / name for name in ("render_report.json", "sound_execution.json", "media_verification.json")]
                      + ([self.work / "audio_mix_report.json"] if (self.work / "audio_mix_report.json").is_file() else []))
        provenance = self.audit.verify()
        calls = json.loads((self.work / "model_calls.json").read_text(encoding="utf-8"))
        successful_stages = {c.get("stage") for c in calls if c.get("status") == "succeeded"}
        checks = {"live_agent": True, "configured_model_used": bool(calls) and all(c["model"] == cfg.model_name for c in calls),
                  "agent_authored_script_and_director": "teaching" in successful_stages and bool(
                      {"director", "director_repair"} & successful_stages),
                  "all_scenes_voiced": all(r["narration"] == "minimax" for r in reports),
                  "history_uses_remotion": all(r["renderer"] == "remotion" for r in reports),
                  "director_actions_executed": all(r.get("passed", r.get("ok", False)) for r in frame_reports),
                  "word_timing_used": all(s["checks"]["observed_word_alignment"] for s in resolved),
                  "complete_narration_window": all(s["duration"] >= voices[s["segment_id"]]["speech"]["duration"]
                                                     + transition / 2 for s in resolved),
                  "sfx_density_within_limit": timeline_checks["sfx_density_within_limit"],
                  "semantic_gap_within_limit": timeline_checks["semantic_gap_within_limit"],
                  "duration_matches_timeline": abs(report["duration"] - composition["expected_duration"]) < .12,
                  "no_long_boundary_silence": media["max_boundary_silence"] < .35,
                  "no_black_intervals": media["black_intervals"] == 0,
                  "single_speed_transform": composition["playback_speed"] == cfg.playback_speed and cfg.tts_speed == 1
                      and not sound_report["playback_speed_applied_here"],
                  "configured_bgm_mixed": bool(cfg.bgm_path) and sound_report["bgm"]["enabled"]
                      and sound_report["bgm"]["configured_gain"] == cfg.bgm_volume,
                  "sound_cues_mixed": sound_report["event_count"] == len(sound_events) > 0,
                  "sfx_aligned_within_frame": all(abs(e["alignment_error_seconds"]) <= 1 / fps for e in sound_report["events"]),
                  "actions_on_observed_anchors": all(abs(a["start"] - b["anchor_time"]) / speed <= 1 / fps
                                                     for s in resolved for b in s["beats"] for a in b["actions"]),
                  "audio_not_clipped": sound_report["levels"]["final_mix"]["max_dbfs"] < 0,
                  **{k: v for k, v in provenance.items() if isinstance(v, bool)}}
        acceptance = {"job_id": self.record.id, "input": {"topic": self.record.topic}, "model": cfg.model_name,
                      "model_calls": len(calls), "director_repairs": self.state["director_repairs"],
                      "duration": report["duration"], "bgm_volume": cfg.bgm_volume, "checks": checks,
                      "output": str(final), "protocol": "history-director-v2"}
        save_json(self.work / "live_acceptance.json", acceptance)
        self.remember("acceptance", [self.work / "live_acceptance.json"])
        if not all(checks.values()):
            raise RuntimeError("History technical acceptance failed; see live_acceptance.json")
        for path in self.work.rglob("*"):
            if path.is_file():
                self.artifacts[path.relative_to(self.work).as_posix()] = str(path.resolve())
        return self.repository.update(self.record.id, status=JobStatus.succeeded, stage="complete", progress=1,
                                      output_path=str(final), artifacts=self.artifacts, error=None)
