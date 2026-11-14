"""Submit one topic to a fresh, profile-controlled history Agent production run."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.orchestrator import Orchestrator
from harness.history_profile import HistoryTypography, history_settings
from harness.schemas import Domain, JobCreate, JobStatus
from harness.settings import Settings, secret_value
from storage.repository import JobRepository


class ProductionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    version: str
    duration_budget: int = Field(ge=10, le=600)
    target_final_duration: list[int] = Field(min_length=2, max_length=2)
    narration_char_budget: int = Field(ge=380, le=480)
    width: int = Field(ge=320, le=3840, multiple_of=2)
    height: int = Field(ge=320, le=3840, multiple_of=2)
    fps: int = Field(ge=10, le=60)
    playback_speed: float = Field(ge=.5, le=2, allow_inf_nan=False)
    style_id: str
    sfx_per_minute: list[int] = Field(min_length=2, max_length=2)
    director_repairs: int
    transport_attempts: int = Field(ge=1, le=3)
    model_timeout: float = Field(default=600.0, ge=180, le=900, allow_inf_nan=False)
    model_max_tokens: int = Field(default=16000, ge=16000, le=64000)
    runtime_ai_review: bool
    require_narrative_bindings: bool = False
    typography: HistoryTypography | None = None

    @model_validator(mode="after")
    def supported_protocol(self):
        if (self.id != "history-animation-v2" or self.version != "2.0" or self.style_id != "gufeng"
                or self.director_repairs != 1 or self.runtime_ai_review or self.sfx_per_minute != [12, 18]):
            raise ValueError("Profile must use the supported history v2 protocol and single technical repair")
        if not 0 < self.target_final_duration[0] <= self.target_final_duration[1]:
            raise ValueError("Target duration bounds must be positive and ordered")
        if self.width * 9 != self.height * 16:
            raise ValueError("The history production profile must use a 16:9 stage")
        return self


def load_profile(settings: Settings) -> ProductionProfile:
    path = Path(settings.project_root) / "assets" / "history" / "production_profile.json"
    return ProductionProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def public_text(value, settings: Settings) -> str:
    """Print only whitelisted fields; additionally redact any known credentials."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    for name in ("model_api_key", "minimax_api_key", "api_token", "s3_access_key", "s3_secret_key"):
        secret = secret_value(getattr(settings, name, ""))
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


async def verify(topic: str, *, validate: bool = True) -> dict:
    """Always create a new job; content and technical retries belong to Orchestrator."""
    settings = Settings()
    try:
        profile = load_profile(settings)
        settings = settings.model_copy(update={
            "history_director_enabled": True, "tts_enabled": True, "tts_speed": 1.0,
            "playback_speed": profile.playback_speed, "model_retries": profile.transport_attempts - 1,
            "model_timeout": max(settings.model_timeout, profile.model_timeout),
            "model_max_tokens": profile.model_max_tokens,
        })
        settings = history_settings(settings)
        settings = settings.model_copy(update={"history_validation_enabled": validate})
        if not settings.model_name or not secret_value(settings.model_api_key):
            raise RuntimeError("正式历史验收需要项目配置的文本模型与密钥")
        if not secret_value(settings.minimax_api_key):
            raise RuntimeError("正式历史验收需要项目配置的 MiniMax 密钥")
        if not settings.bgm_path or not Path(settings.bgm_path).is_file():
            raise RuntimeError("正式历史验收需要配置有效的用户 BGM 文件")
        request = JobCreate(
            topic=topic, domain=Domain.history, mode="live", renderer="remotion", tts_enabled=True,
            duration=profile.duration_budget, narration_char_budget=profile.narration_char_budget,
            aspect_ratio="16:9", width=profile.width, height=profile.height, fps=profile.fps,
            playback_speed=profile.playback_speed,
        )
        repository = JobRepository(settings.database_url)
        task = None
        try:
            job = repository.create(request)
            settings.output_dir.mkdir(parents=True, exist_ok=True)
            (settings.output_dir / "latest_history_job.txt").write_text(job.id, encoding="utf-8")
            print(public_text({"job_id": job.id, "model": settings.model_name, "profile": profile.id,
                               "playback_speed": profile.playback_speed, "validation_enabled": validate}, settings), flush=True)
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
                raise RuntimeError(result.error or "历史 Agent 任务未完成")
            folder = (settings.output_dir / job.id).resolve()
            output = Path(result.output_path).resolve()
            if not output.is_relative_to(folder) or not output.is_file():
                raise RuntimeError("历史 Agent 未在新任务目录产生有效成片")
            if not validate:
                summary = {"job_id": job.id, "model": settings.model_name, "validation_performed": False,
                           "output": str(output), "report": str(folder / "generation_report.json")}
                print(public_text(summary, settings), flush=True)
                return summary
            report_path = folder / "live_acceptance.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            checks = report.get("checks")
            if (report.get("job_id") != job.id or report.get("protocol") != "history-director-v2"
                    or report.get("input") != {"topic": request.topic}
                    or report.get("model") != settings.model_name
                    or not isinstance(checks, dict) or not checks
                    or any(value is not True for value in checks.values())):
                raise RuntimeError("正式历史验收未通过；请查看该任务的 live_acceptance.json")
            summary = {"job_id": job.id, "model": settings.model_name, "profile": profile.id,
                       "protocol": report["protocol"], "duration": report.get("duration"),
                       "target_final_duration": profile.target_final_duration,
                       "model_calls": report.get("model_calls"), "director_repairs": report.get("director_repairs"),
                       "checks": checks, "output": str(output), "acceptance": str(report_path)}
            print(public_text(summary, settings), flush=True)
            return summary
        finally:
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            repository.close()
    except Exception as error:
        raise RuntimeError(public_text(str(error), settings)) from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--topic", required=True, help="唯一内容输入；由项目 Agent 独立研究、写稿、编排和成片")
    args = parser.parse_args(argv)
    try:
        asyncio.run(verify(args.topic))
    except Exception as error:
        print(f"验收失败：{error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
