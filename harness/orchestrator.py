"""Six durable stages; reuse valid checkpoints and retry technical failures only."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel
from filelock import FileLock, Timeout

from harness.asset_retriever import AssetRetriever
from harness.model_gateway import ModelGateway
from harness.schemas import AssetManifest, JobStatus, TeachingPlan, VideoPlan, VideoRequest, VisualPlan
from harness.settings import Settings, secret_value
from workflows.planning import plan, route_topic, visual_plan
from workflows.research import research
from workflows.storyboard import build_storyboard


def write_json(path: Path, value: Any) -> None:
    """Atomic replacement prevents a worker interruption leaving a valid-looking checkpoint."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


async def finish_thread(function, *args):
    """Keep the job lock until synchronous filesystem/process work actually exits."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


class Orchestrator:
    def __init__(self, settings: Settings, repository, *, gateway=None, renderer_factory=None):
        self.settings = settings
        self.repository = repository
        self.gateway = gateway
        self.renderer_factory = renderer_factory

    async def run(self, job_id: str):
        root = self.settings.output_dir.resolve()
        work = (root / job_id).resolve()
        if work.parent != root:
            raise ValueError("Invalid job id")
        work.mkdir(parents=True, exist_ok=True)
        lock = FileLock(work / ".production.lock")
        waited = False
        while True:
            try:
                lock.acquire(timeout=0)
                break
            except Timeout:
                waited = True
                await asyncio.sleep(1)
        try:
            latest = self.repository.get(job_id)
            if waited and latest and latest.status == JobStatus.succeeded:
                return latest
            return await self._run(job_id)
        finally:
            lock.release()

    async def _run(self, job_id: str):
        record = self.repository.get(job_id)
        if record is None:
            raise KeyError(job_id)
        root = self.settings.output_dir.resolve()
        work = (root / job_id).resolve()
        if work.parent != root:
            raise ValueError("Invalid job id")
        work.mkdir(parents=True, exist_ok=True)
        artifacts = dict(record.artifacts)
        gateway = self.gateway or ModelGateway(self.settings, audit_path=work / "model_calls.json")
        dirty = False

        async def stage(name: str, progress: float, filename: str, contract, action: Callable):
            nonlocal dirty
            self.repository.update(job_id, status=JobStatus.running, stage=name, progress=progress, error=None)
            target = work / filename
            cached = False
            if target.exists() and not dirty:
                try:
                    raw = json.loads(target.read_text(encoding="utf-8"))
                    result = contract.model_validate(raw) if contract else raw
                    cached = isinstance(raw, dict)
                except (ValueError, OSError):
                    cached = False
            if not cached:
                dirty = True
                result = action()
                if inspect.isawaitable(result):
                    result = await result
                write_json(target, result)
            artifacts[filename] = str(target)
            self.repository.update(job_id, artifacts=dict(artifacts))
            return result

        try:
            request_data = record.request.model_dump(exclude={"topic", "renderer", "tts_enabled", "playback_speed"}, exclude_none=True)
            # Let the router infer dimensions for non-landscape formats unless explicitly sized.
            if record.request.aspect_ratio != "16:9" and (record.request.width, record.request.height) == (1280, 720):
                request_data.pop("width", None)
                request_data.pop("height", None)
            async def identify():
                defaults = route_topic(record.topic, **request_data)
                if record.mode == "live" and record.request.domain is None:
                    classification = await gateway.generate_json(
                        "为知识视频选择主要学科。只返回 JSON 对象，domain 为 mathematics、history、physics、"
                        "biology、economics、literature 之一；title 为简短中文标题。"
                        "采用高中生与大学初学者受众，不询问用户。跨学科时选择解释核心概念的学科。",
                        json.dumps({"topic": record.topic, "keyword_hint": defaults.domain.value}, ensure_ascii=False),
                    )
                    defaults = route_topic(record.topic, **{**request_data, "domain": classification["domain"],
                        "title": classification.get("title", record.topic)})
                return defaults

            request = await stage("identify", .05, "video_request.json", VideoRequest, identify)
            findings = await stage("research", .15, "research.json", None,
                                   lambda: research(request, gateway))
            teaching = await stage("teaching", .28, "teaching_plan.json", TeachingPlan,
                                   lambda: plan(request, findings, gateway))
            visual = await stage("visual", .40, "visual_plan.json", VisualPlan,
                                 lambda: visual_plan(teaching))
            manifest = await stage("assets", .50, "asset_manifest.json", AssetManifest,
                                   lambda: AssetRetriever(self.settings.asset_catalog_path).retrieve(visual))

            def storyboard():
                result = build_storyboard(teaching, visual, manifest)
                # A renderer override is an execution choice, independent of scene-level domain routing.
                if record.request.renderer != "auto":
                    for scene in result.scenes:
                        scene.renderer = record.request.renderer
                return result

            video = await stage("storyboard", .60, "storyboard.json", VideoPlan, storyboard)
            write_json(work / "video_plan.json", video)
            artifacts["video_plan.json"] = str(work / "video_plan.json")
            cfg = self.settings
            if record.request.tts_enabled is not None:
                # Content source and narration are independent: a bundled lesson can have a real voice.
                cfg = cfg.model_copy(update={"tts_enabled": record.request.tts_enabled})
            if record.request.playback_speed is not None:
                cfg = cfg.model_copy(update={"playback_speed": record.request.playback_speed})
            if self.renderer_factory is None:
                from renderers.service import VideoRenderer
                renderer = VideoRenderer(cfg)
            else:
                renderer = self.renderer_factory(cfg)
            self.repository.update(job_id, stage="generation", progress=.68, artifacts=dict(artifacts))
            await finish_thread(renderer.generate, video, work)
            self.repository.update(job_id, stage="rendering", progress=.72)
            if inspect.iscoroutinefunction(renderer.render):
                final = await renderer.render(video, work)
            else:
                final = await finish_thread(renderer.render, video, work)
            final = Path(final).resolve()
            if not final.is_relative_to(work) or not final.is_file() or final.stat().st_size < 32:
                raise RuntimeError("渲染器未生成有效 final.mp4")
            for path in work.rglob("*"):
                if path.is_file() and path.suffix in {".json", ".py", ".srt", ".mp4", ".mp3", ".wav", ".svg", ".tex", ".pdf", ".png"}:
                    relative = path.relative_to(work).as_posix()
                    artifacts[relative] = str(path.resolve())
            return self.repository.update(job_id, status=JobStatus.succeeded, stage="complete", progress=1,
                                          output_path=str(final), artifacts=artifacts, error=None)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            for name in ("model_api_key", "minimax_api_key", "api_token", "s3_secret_key"):
                secret = secret_value(getattr(self.settings, name, ""))
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            return self.repository.update(job_id, status=JobStatus.failed, error=message[:3000], artifacts=artifacts)
