"""Acceptance run: the configured project Agent writes and produces a fresh video."""
import argparse
import asyncio
import json
import re
from pathlib import Path

from harness.orchestrator import Orchestrator
from harness.schemas import JobCreate, JobStatus
from harness.settings import Settings, secret_value
from storage.repository import JobRepository
from renderers.ffmpeg import FFmpeg


def inspect_media(folder, report, settings):
    """Measure speech-only boundary silence before the continuous BGM is mixed."""
    ffmpeg = FFmpeg(settings)
    log = ffmpeg.run(["-i", str(folder / "joined.mp4"), "-af", "silencedetect=noise=-45dB:d=0.02",
                      "-f", "null", "-"])
    silences, start = [], None
    for kind, raw in re.findall(r"silence_(start|end):\s*([0-9.]+)", log):
        if kind == "start":
            start = float(raw)
        elif start is not None:
            silences.append((start, float(raw)))
            start = None
    boundaries = []
    for transition in report["composition"]["transitions"]:
        middle = (transition["start"] + transition["end"]) / 2
        gap = next((b - a for a, b in silences if a - .05 <= middle <= b + .05), 0)
        boundaries.append({"at": middle, "measured_silence": gap})
    black_log = ffmpeg.run(["-i", str(folder / "final.mp4"), "-an", "-vf",
                           "blackdetect=d=0.1:pix_th=0.02:pic_th=0.999", "-f", "null", "-"])
    result = {"boundaries": boundaries, "max_boundary_silence": max((b["measured_silence"] for b in boundaries), default=0),
              "black_intervals": len(re.findall(r"black_start:", black_log))}
    (folder / "media_verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


async def verify(args):
    settings = Settings()
    if not settings.model_name or not secret_value(settings.model_api_key):
        raise RuntimeError("端到端验收需要项目的 MODEL_NAME 和 MODEL_API_KEY")
    if not settings.tts_enabled or not secret_value(settings.minimax_api_key):
        raise RuntimeError("端到端验收需要启用真实 MiniMax 配音")
    repository = JobRepository(settings.database_url)
    try:
        existing = args.resume or args.inspect
        job = repository.get(existing) if existing else repository.create(
            JobCreate(topic=args.topic, mode="live", duration=args.duration, renderer="auto", tts_enabled=True,
                      narration_char_budget=args.narration_chars)
        )
        if job is None or job.mode != "live":
            raise RuntimeError("验收只能创建或恢复 live 任务")
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        (settings.output_dir / "latest_live_job.txt").write_text(job.id, encoding="utf-8")
        print(f"job_id={job.id}; model={settings.model_name}; speed={settings.playback_speed}", flush=True)
        if args.inspect:
            result = job
        else:
            task = asyncio.create_task(Orchestrator(settings, repository).run(job.id))
            previous = None
            while not task.done():
                current = repository.get(job.id)
                if current.stage != previous:
                    print(f"stage={current.stage}", flush=True)
                    previous = current.stage
                await asyncio.wait({task}, timeout=5)
            result = await task
        if result.status != JobStatus.succeeded:
            raise RuntimeError(result.error)
        folder = Path(result.output_path).parent
        calls = json.loads((folder / "model_calls.json").read_text(encoding="utf-8"))
        report = json.loads((folder / "render_report.json").read_text(encoding="utf-8"))
        media = await asyncio.to_thread(inspect_media, folder, report, settings)
        checks = {
            "live_agent": result.mode == "live",
            "configured_model_used": len(calls) >= 3 and all(c["model"] == settings.model_name for c in calls),
            "all_scenes_voiced": all(s["narration"] == "minimax" for s in report["scenes"]),
            "configured_bgm_mixed": not settings.bgm_path or report["bgm"] == str(settings.bgm_path),
            "synchronized_speed": report["composition"]["playback_speed"] == settings.playback_speed,
            "duration_matches_timeline": abs(report["duration"] - report["composition"]["expected_duration"]) < .12,
            "all_boundaries_transition": len(report["composition"]["transitions"]) == len(report["scenes"]) - 1,
            "no_long_boundary_silence": media["max_boundary_silence"] < .35,
            "no_black_intervals": media["black_intervals"] == 0,
        }
        acceptance = {"job_id": job.id, "model": settings.model_name, "model_calls": len(calls),
                      "checks": checks, "duration": report["duration"], "bgm": report["bgm"], "output": result.output_path}
        (folder / "live_acceptance.json").write_text(json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8")
        repository.update(job.id, artifacts={**result.artifacts,
            "live_acceptance.json": str(folder / "live_acceptance.json"),
            "media_verification.json": str(folder / "media_verification.json"),
        })
        print(json.dumps(acceptance, ensure_ascii=False, indent=2), flush=True)
        if not all(checks.values()):
            raise RuntimeError("Live acceptance failed; see live_acceptance.json")
    finally:
        repository.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="微积分的本质")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--narration-chars", type=int, help="给项目 Agent 的全片旁白字符预算，含标点")
    existing = parser.add_mutually_exclusive_group()
    existing.add_argument("--resume", help="恢复同一真实 Agent 任务的技术失败")
    existing.add_argument("--inspect", help="只检查已完成的 live 成片及其模型调用证据")
    asyncio.run(verify(parser.parse_args()))
