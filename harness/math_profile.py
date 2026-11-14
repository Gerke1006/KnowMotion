"""Transport capacity for model-authored, word-aligned mathematics animation."""


def apply_math_settings(settings):
    return settings.model_copy(update={
        "model_max_tokens": max(settings.model_max_tokens, 16000),
        "model_timeout": max(settings.model_timeout, 600.0),
        "model_retries": min(settings.model_retries, 2),
    })
