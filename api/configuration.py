"""Local API overrides, isolated from requests, job artifacts and the project .env."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from urllib.parse import urlsplit

from pydantic import SecretStr

from harness.settings import Settings, secret_value


PUBLIC_FIELDS = (
    "model_base_url", "model_name", "minimax_base_url", "minimax_model", "minimax_voice_id",
)
SECRET_FIELDS = ("model_api_key", "minimax_api_key")
ALLOWED_FIELDS = {*PUBLIC_FIELDS, *SECRET_FIELDS}


class ConfigurationError(ValueError):
    """Messages are fixed and never include caller-supplied values."""


def validate_changes(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict) or not payload:
        raise ConfigurationError("Provide at least one API setting.")
    if set(payload) - ALLOWED_FIELDS:
        raise ConfigurationError("Unknown API setting.")
    clean = {}
    for field, value in payload.items():
        if not isinstance(value, str):
            raise ConfigurationError("API settings must be strings.")
        value = value.strip()
        if field in SECRET_FIELDS and not value:
            continue  # Empty password inputs preserve existing credentials.
        if not value or len(value) > (4096 if field in SECRET_FIELDS else 2048):
            raise ConfigurationError("An API setting is empty or too long.")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ConfigurationError("API settings cannot contain control characters.")
        if field.endswith("base_url"):
            try:
                parsed = urlsplit(value)
                valid = (
                    parsed.scheme in {"http", "https"} and parsed.hostname
                    and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment
                    and not any(char.isspace() for char in value)
                    and (parsed.port is None or 0 < parsed.port < 65536)
                )
            except ValueError:
                valid = False
            if not valid:
                raise ConfigurationError("API Base URL must be an HTTP(S) URL without credentials, query or fragment.")
            value = value.rstrip("/")
        clean[field] = value
    return clean


class ApiConfiguration:
    def __init__(self, defaults: Settings, path: Path):
        self.defaults = defaults.model_copy(deep=True)
        self.path = path
        self.lock = RLock()
        self.overrides: dict[str, str] = {}
        self.editable = defaults.execution_backend == "local"
        if self.editable and path.exists():
            try:
                if path.stat().st_size > 20000:
                    raise ValueError
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.overrides = validate_changes(raw) if raw else {}
            except (OSError, ValueError):
                raise RuntimeError("Saved API settings could not be read; repair or remove data/runtime-api-settings.json.") from None

    def snapshot(self) -> Settings:
        with self.lock:
            values = {name: SecretStr(value) if name in SECRET_FIELDS else value
                      for name, value in self.overrides.items()}
            return self.defaults.model_copy(update=values, deep=True)

    def public(self) -> dict:
        with self.lock:
            current = self.snapshot()
            return {
                **{field: getattr(current, field) for field in PUBLIC_FIELDS},
                "model_key_configured": bool(secret_value(current.model_api_key)),
                "minimax_key_configured": bool(secret_value(current.minimax_api_key)),
                "customized": bool(self.overrides),
                "editable": self.editable,
                "execution_backend": current.execution_backend,
            }

    def save(self, changes: dict[str, str]) -> dict:
        with self.lock:
            candidate = {**self.overrides, **changes}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                # The secret file is runtime data under the ignored data/ folder.
                # Only this dedicated file is changed; .env remains untouched.
                with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                        prefix=".runtime-api-", suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                    os.chmod(temporary, 0o600)
                    json.dump(candidate, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(self.path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            self.overrides = candidate
            return self.public()

    def reset(self) -> dict:
        with self.lock:
            self.path.unlink(missing_ok=True)
            self.overrides = {}
            return self.public()
