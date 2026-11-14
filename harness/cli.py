"""One-command production and explicit offline demos."""
import argparse
import asyncio
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from harness.schemas import JobCreate, JobStatus
from harness.settings import Settings, secret_value
from storage.repository import JobRepository


def doctor(settings: Settings) -> dict:
    from renderers.ffmpeg.composer import FFmpeg
    from renderers.latex import find_compiler
    from renderers.remotion import RemotionRenderer
    remotion = RemotionRenderer(settings)
    try:
        remotion.preflight()
        remotion_status = "ready"
    except RuntimeError:
        remotion_status = "needs npm ci / Node.js"
    try:
        ffmpeg = FFmpeg(settings).binary
    except Exception:
        ffmpeg = shutil.which("ffmpeg") or "unavailable"
    try:
        latex = str(find_compiler(settings))
    except RuntimeError:
        latex = "unavailable"
    return {
        "python": sys.version.split()[0], "ffmpeg": str(ffmpeg),
        "manim_installed": importlib.util.find_spec("manim") is not None,
        "remotion": {"project": str(remotion.project), "dependencies": remotion_status},
        "model_configured": bool(settings.model_name and secret_value(settings.model_api_key)),
        "tts_configured": bool(secret_value(settings.minimax_api_key)),
        "voice": settings.minimax_voice_name,
        "tts_enabled": settings.tts_enabled,
        "model": settings.model_name,
        "playback_speed": settings.playback_speed,
        "transition_duration": settings.transition_duration,
        "latex_compiler": latex,
        "fonts": {"chinese": settings.chinese_font, "english": settings.english_font,
                  "subtitle": settings.subtitle_font},
        "bgm": ("present" if Path(settings.bgm_path).is_file() else "missing") if settings.bgm_path else "disabled",
        "backend": settings.execution_backend,
    }


def main():
    parser = argparse.ArgumentParser(description="多学科知识视频自动生产系统")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="一键生成主题视频")
    generate.add_argument("topic")
    generate.add_argument("--mode", choices=["demo", "live"], default="live")
    generate.add_argument("--renderer", choices=["auto", "manim", "canvas", "svg", "remotion", "blender"], default="auto")
    generate.add_argument("--duration", type=float, default=60)
    generate.add_argument("--narration-chars", dest="narration_char_budget", type=int, default=None,
                          help="全片旁白字符预算（含标点），传给项目 Agent 控制短片长度")
    generate.add_argument("--aspect-ratio", choices=["16:9", "9:16", "1:1"], default="16:9")
    generate.add_argument("--width", type=int, default=1280)
    generate.add_argument("--height", type=int, default=720)
    generate.add_argument("--fps", type=int, default=30)
    generate.add_argument("--speed", dest="playback_speed", type=float, default=None,
                          help="画面和人声同步倍速，默认 PLAYBACK_SPEED=1.15；保持音高")
    generate.add_argument("--tts", dest="tts_enabled", action=argparse.BooleanOptionalAction, default=None,
                          help="配音开关；默认使用 TTS_ENABLED，--no-tts 显式生成静音演示")
    commands.add_parser("doctor", help="检查依赖和配置，不显示密钥")
    resume = commands.add_parser("resume", help="从有效中间产物恢复失败任务")
    resume.add_argument("job_id")
    status = commands.add_parser("status")
    status.add_argument("job_id")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings()
    if args.command == "doctor":
        print(json.dumps(doctor(settings), ensure_ascii=False, indent=2))
        return
    if args.command == "serve":
        import uvicorn
        uvicorn.run("api.main:create_app", factory=True, host=args.host, port=args.port)
        return
    repo = JobRepository(settings.database_url)
    try:
        if args.command == "generate":
            values = vars(args).copy()
            values.pop("command")
            job = repo.create(JobCreate(**values))
        else:
            job = repo.get(args.job_id)
            if job is None:
                parser.error("任务不存在")
        if args.command == "status":
            print(job.model_dump_json(indent=2))
            return
        if args.command == "resume" and job.status == JobStatus.running:
            parser.error("任务仍在运行；请先停止原 worker，避免重复执行")
        from harness.orchestrator import Orchestrator
        print(f"job_id={job.id}", flush=True)
        result = asyncio.run(Orchestrator(settings, repo).run(job.id))
        print(result.model_dump_json(indent=2))
        if result.status != JobStatus.succeeded:
            raise SystemExit(1)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
