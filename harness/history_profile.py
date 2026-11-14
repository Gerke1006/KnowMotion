"""Apply frozen history transport capacity to API jobs as well as the CLI."""
import json
import math

from pydantic import BaseModel, ConfigDict, Field


class HistoryTypography(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chinese_font: str = Field(default="History Serif", min_length=1, max_length=80)
    english_font: str = "Times New Roman"
    subtitle_font: str = Field(default="History Serif", min_length=1, max_length=80)
    subtitle_font_weight: str = "900"
    subtitle_outline_color: str = Field(default="#292824", pattern=r"^#[0-9A-Fa-f]{6}$")
    subtitle_outline_width: float = Field(default=1.0, ge=0, le=3, allow_inf_nan=False)
    subtitle_background_opacity: float = Field(default=.18, ge=0, le=.5, allow_inf_nan=False)


def history_settings(settings):
    path = settings.project_root / "assets/history/production_profile.json"
    if not path.is_file():
        return settings
    profile = json.loads(path.read_text(encoding="utf-8"))
    tokens = profile.get("model_max_tokens", 16000)
    timeout = profile.get("model_timeout", 600.0)
    if (type(tokens) is not int or not 8000 <= tokens <= 64000
            or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 180 <= timeout <= 900):
        raise ValueError("Invalid history transport capacity in frozen production profile")
    typography = HistoryTypography.model_validate(profile["typography"]).model_dump() if "typography" in profile else {}
    required = profile.get("require_narrative_bindings", False)
    if type(required) is not bool:
        raise ValueError("History narrative binding policy must be boolean")
    return settings.model_copy(update={**typography, "history_narrative_bindings": required,
                                       "model_max_tokens": max(settings.model_max_tokens, tokens),
                                       "model_timeout": max(settings.model_timeout, timeout),
                                       "model_retries": min(settings.model_retries, 2)})
