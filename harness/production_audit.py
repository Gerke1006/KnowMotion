"""Content-addressed production evidence; never treats edited checkpoints as model output."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_snapshot(root: Path) -> dict:
    files = {}
    for folder in ("harness", "workflows", "renderers", "domains", "assets", "scripts", "tools", "docs", "third_party"):
        for directory, directories, filenames in os.walk(root / folder):
            directories[:] = [name for name in directories if name not in {
                "node_modules", "__pycache__", ".cache", "out", "media"
            }]
            for filename in filenames:
                path = Path(directory) / filename
                relative = path.relative_to(root)
                if path.suffix.lower() in {
                ".py", ".json", ".md", ".ts", ".tsx", ".css", ".svg", ".png", ".jpg", ".geojson", ".wav", ".m4a",
                ".otf", ".ttf", ".woff", ".woff2", ".txt"
                } or path.name == "LICENSE":
                    files[relative.as_posix()] = sha256(path)
    for name in ("pyproject.toml", "AGENTS.md"):
        path = root / name
        if path.is_file():
            files[name] = sha256(path)
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"fingerprint": fingerprint, "files": files}


def public_configuration(settings) -> dict:
    names = ("model_name", "model_base_url", "model_max_tokens", "model_timeout", "model_retries", "minimax_model",
             "minimax_base_url", "minimax_voice_id", "tts_enabled", "tts_speed", "playback_speed",
             "bgm_volume", "transition_duration", "narration_gap", "narration_lufs", "chinese_font",
             "english_font", "subtitle_font", "subtitle_font_weight", "subtitle_color",
             "subtitle_outline_color", "subtitle_outline_width", "subtitle_background_opacity",
             "history_narrative_bindings", "history_validation_enabled", "remotion_project", "remotion_entry")
    result = {name: getattr(settings, name) for name in names}
    bgm = Path(settings.bgm_path) if settings.bgm_path else None
    result["bgm_sha256"] = sha256(bgm) if bgm and bgm.is_file() else None
    return result


class FrozenRun:
    def __init__(self, settings, folder: Path, topic: str, *, profile="history-animation-v2", initial_build=None):
        self.settings = settings
        self.folder = Path(folder).resolve()
        self.root = Path(settings.project_root).resolve()
        self.path = self.folder / "run_manifest.json"
        self.records_path = self.folder / "artifact_records.json"
        self.folder.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.manifest = json.loads(self.path.read_text(encoding="utf-8"))
            if self.manifest["input"]["topic"] != topic:
                raise ValueError("Frozen run topic does not match the submitted input")
            self.verify()
        else:
            build = initial_build or build_snapshot(self.root)
            if build_snapshot(self.root)["fingerprint"] != build["fingerprint"]:
                raise ValueError("Build changed while identifying topic; restart with a frozen build")
            self.manifest = {
                "schema_version": "2.0", "profile": profile,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "input": {"topic": topic}, "build": build,
                "configuration": public_configuration(settings),
                "policy": "Project Agent produces content. No external edits or reused lesson outputs.",
            }
            save_json(self.path, self.manifest)
            save_json(self.records_path, {"schema_version": "2.0", "artifacts": {}})

    def verify(self) -> dict:
        if build_snapshot(self.root)["fingerprint"] != self.manifest["build"]["fingerprint"]:
            raise ValueError("Production build changed during frozen run; start a new run after software fixes")
        if public_configuration(self.settings) != self.manifest["configuration"]:
            raise ValueError("Production configuration changed during frozen run")
        records = json.loads(self.records_path.read_text(encoding="utf-8"))
        for relative, record in records["artifacts"].items():
            path = (self.folder / relative).resolve()
            if not path.is_relative_to(self.folder) or not path.is_file() or sha256(path) != record["sha256"]:
                raise ValueError(f"Production artifact was changed outside its recorded stage: {relative}")
        return {"build_unchanged": True, "configuration_unchanged": True,
                "artifact_hashes_valid": True, "artifacts": len(records["artifacts"])}

    def record(self, stage: str, paths, *, origin="deterministic", call_ids=None, inputs=None) -> None:
        records = json.loads(self.records_path.read_text(encoding="utf-8"))
        input_hashes = {str(p.relative_to(self.folder)): sha256(p) for p in (inputs or []) if p.is_file()}
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if not path.is_relative_to(self.folder):
                raise ValueError("Production evidence must stay inside the run directory")
            relative = path.relative_to(self.folder).as_posix()
            previous = records["artifacts"].get(relative)
            records["artifacts"][relative] = {
                "stage": stage, "origin": origin, "sha256": sha256(path),
                "producer_call_ids": call_ids or [], "input_artifact_hashes": input_hashes,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "previous_sha256": previous["sha256"] if previous else None,
            }
        save_json(self.records_path, records)

    def record_model_calls(self) -> None:
        path = self.folder / "model_calls.json"
        if not path.is_file():
            return
        calls = json.loads(path.read_text(encoding="utf-8"))
        records = json.loads(self.records_path.read_text(encoding="utf-8"))["artifacts"]
        for call in calls:
            for key in ("request_artifact", "response_artifact"):
                if call.get(key):
                    artifact = (self.folder / call[key]).resolve()
                    if not artifact.is_relative_to(self.folder):
                        raise ValueError("Model evidence escaped its run directory")
                    raw = json.loads(artifact.read_text(encoding="utf-8"))
                    canonical = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    if canonical != call[key.replace("_artifact", "_sha256")]:
                        raise ValueError("Model request/response does not match its gateway hash")
                    relative = artifact.relative_to(self.folder).as_posix()
                    if relative in records and sha256(artifact) != records[relative]["sha256"]:
                        raise ValueError("Previously recorded model evidence was externally changed")
                    self.record("model_gateway", [artifact], origin="configured_model", call_ids=[call["call_id"]])
        self.record("model_gateway", [path], origin="configured_model",
                    call_ids=[call["call_id"] for call in calls if call.get("call_id")])
