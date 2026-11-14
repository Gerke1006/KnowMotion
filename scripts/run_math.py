"""Create one configured-Agent mathematics video without tests or media acceptance."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import json
from pathlib import Path

from api.configuration import ApiConfiguration
from harness.math_profile import apply_math_settings
from harness.orchestrator import Orchestrator
from harness.production_audit import build_snapshot, save_json
from harness.schemas import Domain, JobCreate, JobStatus
from harness.settings import Settings, secret_value
from storage.repository import JobRepository


def public_text(value, settings):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    for name in ("model_api_key", "minimax_api_key", "api_token", "s3_access_key", "s3_secret_key"):
        secret = secret_value(getattr(settings, name, ""))
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


async def run(topic: str):
    defaults = Settings()
    settings = ApiConfiguration(defaults, defaults.project_root / "data/runtime-api-settings.json").snapshot()
    settings = apply_math_settings(settings).model_copy(update={
        "tts_enabled": True, "tts_speed": 1.0, "playback_speed": 1.15,
        "video_validation_enabled": False,
    })
    repository, task = JobRepository(settings.database_url), None
    try:
        request = JobCreate(topic=topic, domain=Domain.mathematics, mode="live", renderer="manim",
                            duration=90, narration_char_budget=440, aspect_ratio="16:9",
                            width=1280, height=720, fps=30, tts_enabled=True, playback_speed=1.15)
        job = repository.create(request)
        folder = (settings.output_dir / job.id).resolve()
        save_json(folder / "math_run.json", {
            "input": {"topic": topic}, "model": settings.model_name,
            "protocol": "math-animation-1.0", "validation_performed": False,
            "build": build_snapshot(settings.project_root),
            "profile": {"narration_char_budget": 440, "target_duration": [75, 90],
                        "width": 1280, "height": 720, "fps": 30, "playback_speed": 1.15,
                        "voice_id": settings.minimax_voice_id, "bgm_volume": settings.bgm_volume},
        })
        print(public_text({"job_id": job.id, "model": settings.model_name,
                           "validation_performed": False}, settings), flush=True)
        task = asyncio.create_task(Orchestrator(settings, repository).run(job.id))
        previous = None
        while not task.done():
            current = repository.get(job.id)
            if current is not None and current.stage != previous:
                print(public_text({"job_id": job.id, "stage": current.stage,
                                   "progress": current.progress}, settings), flush=True)
                previous = current.stage
            await asyncio.wait({task}, timeout=5)
        result = await task
        if result.status != JobStatus.succeeded or not result.output_path:
            raise RuntimeError(result.error or "数学 Agent 任务未完成")
        render = json.loads((folder / "render_report.json").read_text(encoding="utf-8"))
        report = {"job_id": job.id, "input": {"topic": topic}, "model": settings.model_name,
                  "protocol": "math-animation-1.0", "status": "generated", "validation_performed": False,
                  "duration": render.get("duration"), "playback_speed": settings.playback_speed,
                  "bgm_volume": settings.bgm_volume, "output": str(Path(result.output_path).resolve()),
                  "telemetry": result.telemetry}
        save_json(folder / "generation_report.json", report)
        artifacts = dict(result.artifacts)
        artifacts.update({"generation_report.json": str(folder / "generation_report.json"),
                          "math_run.json": str(folder / "math_run.json")})
        repository.update(job.id, artifacts=artifacts)
        print(public_text(report, settings), flush=True)
        return report
    except Exception as error:
        raise RuntimeError(public_text(str(error), settings)) from None
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        repository.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--topic", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.topic))
    except Exception as error:
        print(f"生成失败：{error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
