"""Apply frozen history transport capacity to API jobs as well as the CLI."""
import json
import math


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
    return settings.model_copy(update={"model_max_tokens": max(settings.model_max_tokens, tokens),
                                       "model_timeout": max(settings.model_timeout, timeout),
                                       "model_retries": min(settings.model_retries, 2)})
