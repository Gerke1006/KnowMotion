"""Versioned, validated contracts shared by all domain packs and renderers."""
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Domain(str, Enum):
    mathematics = "mathematics"
    history = "history"
    physics = "physics"
    biology = "biology"
    economics = "economics"
    literature = "literature"


Mode = Literal["demo", "live"]
Renderer = Literal["manim", "canvas", "svg", "remotion", "blender"]
Topic = Annotated[str, Field(min_length=1, max_length=300)]


class JobCreate(Contract):
    topic: Topic
    mode: Mode = "live"
    renderer: Literal["auto", "manim", "canvas", "svg", "remotion", "blender"] = "auto"
    duration: float = Field(default=60, ge=10, le=600)
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    domain: Domain | None = None
    width: int = Field(default=1280, ge=320, le=3840, multiple_of=2)
    height: int = Field(default=720, ge=320, le=3840, multiple_of=2)
    fps: int = Field(default=30, ge=10, le=60)
    tts_enabled: bool | None = None
    playback_speed: float | None = Field(default=None, ge=.5, le=2)
    narration_char_budget: int | None = Field(default=None, ge=50, le=5000)

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("主题不能为空")
        return value


class VideoRequest(Contract):
    schema_version: str = "1.0"
    topic: Topic
    title: str = ""
    domain: Domain
    audience: str = "高中生与大学初学者"
    duration: float = Field(default=60, ge=10, le=600)
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    width: int = Field(default=1280, ge=320, le=3840, multiple_of=2)
    height: int = Field(default=720, ge=320, le=3840, multiple_of=2)
    fps: int = Field(default=30, ge=10, le=60)
    style: str = "academic"
    mode: Mode = "live"
    narration_char_budget: int | None = Field(default=None, ge=50, le=5000)


class ComponentRef(Contract):
    id: str = Field(min_length=1, max_length=100)
    parameters: dict = Field(default_factory=dict)


class Scene(Contract):
    scene_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    title: str = Field(default="", max_length=200)
    domain: Domain
    learning_goal: str
    narration: str = Field(max_length=6000)
    visual_concept: str
    components: list[ComponentRef] = Field(default_factory=list, max_length=20)
    animation_sequence: list[dict] = Field(default_factory=list)
    camera: dict = Field(default_factory=dict)
    audio: dict = Field(default_factory=dict)
    duration: float = Field(gt=0, le=600)
    renderer: Renderer = "manim"
    extensions: dict = Field(default_factory=dict)


class TeachingPlan(Contract):
    request: VideoRequest
    learning_objectives: list[str]
    teaching_structure: list[str]
    scenes: list[Scene] = Field(min_length=1, max_length=30)
    sources: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [s.scene_id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id must be unique")
        return self


class VisualPlan(Contract):
    scenes: list[Scene] = Field(min_length=1, max_length=30)
    style: dict = Field(default_factory=dict)


class AssetSelection(Contract):
    scene_id: str
    component_id: str
    tier: Literal["complete", "composed", "generated"]
    asset_ids: list[str] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)


class AssetManifest(Contract):
    assets: list[AssetSelection] = Field(default_factory=list)


class VideoPlan(Contract):
    schema_version: str = "1.0"
    metadata: VideoRequest
    domain: Domain
    learning_objectives: list[str]
    teaching_structure: list[str]
    scenes: list[Scene] = Field(min_length=1, max_length=30)
    style: dict = Field(default_factory=dict)
    music_timeline: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [s.scene_id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id must be unique")
        return self


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRecord(Contract):
    id: str
    topic: str
    mode: Mode = "live"
    request: JobCreate
    status: JobStatus = JobStatus.queued
    stage: str = "queued"
    progress: float = Field(default=0, ge=0, le=1)
    error: str | None = None
    output_path: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
