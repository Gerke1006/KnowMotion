"""Environment-only secrets and conservative resource limits."""
from pathlib import Path
import sys
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    project_root: Path = PROJECT_ROOT
    output_dir: Path = Path("outputs")
    database_url: str = "sqlite:///data/jobs.db"
    model_base_url: str = "https://api.minimax.cn/v1"
    model_name: str = ""
    model_api_key: SecretStr = SecretStr("")
    model_timeout: float = 180
    model_max_tokens: int = 8000
    model_retries: int = Field(default=2, ge=0, le=5)
    minimax_api_key: SecretStr = SecretStr("")
    minimax_base_url: str = "https://api.minimax.cn"
    minimax_voice_id: str = "Chinese (Mandarin)_Gentle_Youth"
    minimax_voice_name: str = "温润青年"
    minimax_model: str = "speech-2.8-turbo"
    tts_enabled: bool = True
    bgm_path: str = ""
    bgm_volume: float = Field(default=.30, ge=0, le=1)
    tts_speed: float = Field(default=1, ge=.5, le=2)
    playback_speed: float = Field(default=1.15, ge=.5, le=2)
    transition_duration: float = Field(default=.30, ge=0, le=1)
    narration_gap: float = Field(default=.08, ge=0, le=.5)
    narration_lufs: float = Field(default=-16, ge=-30, le=-10)
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    font_path: str = ""
    manim_font: str = "SimSun"
    chinese_font: str = "SimSun"
    english_font: str = "Times New Roman"
    subtitle_font: str = "Microsoft YaHei"
    subtitle_font_weight: str = "BOLD"
    subtitle_color: str = "#FFFFFF"
    subtitle_outline_color: str = "#161044"
    subtitle_outline_width: float = Field(default=5, ge=0, le=20)
    english_font_path: str = ""
    subtitle_font_path: str = ""
    latex_compiler_path: str = ""
    latex_cache_dir: Path = Path("data/latex-cache")
    manim_python: str = sys.executable
    renderer_fallback: bool = False
    remotion_project: str = ""
    remotion_entry: str = "src/index.ts"
    remotion_concurrency: int = Field(default=2, ge=1, le=16)
    remotion_browser_executable: str = ""
    history_director_enabled: bool = True
    blender_path: str = "blender"
    blender_template: str = ""
    render_concurrency: int = Field(default=2, ge=1, le=16)
    execution_backend: Literal["local", "temporal"] = "local"
    local_workers: int = Field(default=2, ge=1, le=16)
    max_queued_jobs: int = Field(default=100, ge=1, le=10000)
    api_token: SecretStr = SecretStr("")
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "vibe-video"
    s3_endpoint: str = ""
    s3_bucket: str = "vibe-assets"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")

    @property
    def asset_catalog_path(self) -> Path:
        return self.project_root / "assets" / "catalog.json"


def secret_value(value) -> str:
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value or "")
