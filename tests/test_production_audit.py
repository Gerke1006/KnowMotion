"""Frozen-run and configured-model provenance, entirely isolated from live services."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from harness.model_gateway import ModelError, ModelGateway
from harness.production_audit import FrozenRun, build_snapshot, public_configuration, save_json
from harness.settings import Settings


def isolated_settings(tmp_path, **overrides):
    root = tmp_path / "project"
    (root / "harness").mkdir(parents=True, exist_ok=True)
    (root / "harness" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "assets" / "audio").mkdir(parents=True, exist_ok=True)
    bgm = root / "assets" / "audio" / "fixture.m4a"
    bgm.write_bytes(b"isolated-original-music" * 4)
    values = dict(project_root=root, output_dir=tmp_path / "runs", bgm_path=str(bgm),
                  model_name="isolated-text-model", model_base_url="https://model.example/v1",
                  model_api_key="private-model-fixture", minimax_api_key="private-voice-fixture",
                  api_token="private-app-fixture", s3_secret_key="private-storage-fixture",
                  model_retries=0)
    values.update(overrides)
    return Settings(_env_file=None, **values)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def test_frozen_build_detects_runtime_and_resource_changes_but_excludes_node_cache(tmp_path):
    cfg = isolated_settings(tmp_path)
    audit = FrozenRun(cfg, tmp_path / "run", "isolated topic")
    cache = cfg.project_root / "renderers/remotion/project/node_modules/package/index.js"
    cache.parent.mkdir(parents=True)
    cache.write_text("dependency cache", encoding="utf-8")
    assert audit.verify()["build_unchanged"] is True
    (cfg.project_root / "harness/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="build changed"):
        audit.verify()


def test_initial_build_and_configuration_are_frozen(tmp_path):
    cfg = isolated_settings(tmp_path)
    original = build_snapshot(cfg.project_root)
    (cfg.project_root / "harness/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Build changed"):
        FrozenRun(cfg, tmp_path / "first", "isolated topic", initial_build=original)
    audit = FrozenRun(cfg, tmp_path / "second", "isolated topic")
    cfg.bgm_volume = .15
    with pytest.raises(ValueError, match="configuration changed"):
        audit.verify()


def test_frozen_configuration_tracks_external_bgm_content(tmp_path):
    external = tmp_path / "external.m4a"
    external.write_bytes(b"external music fixture" * 4)
    cfg = isolated_settings(tmp_path, bgm_path=str(external))
    audit = FrozenRun(cfg, tmp_path / "run", "isolated topic")
    external.write_bytes(b"changed external music" * 4)
    with pytest.raises(ValueError, match="configuration changed"):
        audit.verify()


@pytest.mark.parametrize("delete", [False, True])
def test_frozen_run_rejects_changed_or_removed_recorded_artifact(tmp_path, delete):
    audit = FrozenRun(isolated_settings(tmp_path), tmp_path / "run", "isolated topic")
    path = audit.folder / "script.json"
    save_json(path, {"source": "isolated configured-model fixture"})
    audit.record("script", [path], origin="configured_model", call_ids=["fixture-call"])
    assert audit.verify()["artifact_hashes_valid"] is True
    if delete:
        path.unlink()
    else:
        save_json(path, {"source": "external replacement"})
    with pytest.raises(ValueError, match="outside its recorded stage"):
        audit.verify()


def test_artifact_evidence_must_stay_inside_run_and_reopen_topic_must_match(tmp_path):
    cfg = isolated_settings(tmp_path)
    audit = FrozenRun(cfg, tmp_path / "run", "isolated topic")
    outside = tmp_path / "outside.json"
    save_json(outside, {"outside": True})
    with pytest.raises(ValueError, match="inside the run directory"):
        audit.record("script", [outside])
    with pytest.raises(ValueError, match="topic"):
        FrozenRun(cfg, audit.folder, "different topic")


def test_manifest_and_public_configuration_do_not_contain_credentials(tmp_path):
    cfg = isolated_settings(tmp_path)
    audit = FrozenRun(cfg, tmp_path / "run", "isolated topic")
    text = audit.path.read_text(encoding="utf-8")
    assert "private-" not in text
    public = public_configuration(cfg)
    assert not any("api_key" in key or "secret" in key or "token" == key for key in public)
    assert public["bgm_sha256"] == hashlib.sha256(Path(cfg.bgm_path).read_bytes()).hexdigest()


async def audited_gateway(tmp_path, cfg=None, *, response=None):
    cfg = cfg or isolated_settings(tmp_path)
    audit = FrozenRun(cfg, tmp_path / "run", "isolated topic")
    payload = {"choices": [{"message": {"content": json.dumps(response or {"ok": True})}}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
    gateway = ModelGateway(cfg, httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
                           audit_path=audit.folder / "model_calls.json")
    gateway.stage = "script"
    result = await gateway.generate_json("fixture system", "fixture topic")
    return audit, gateway, result


async def test_model_request_response_artifacts_match_canonical_digests_and_stage(tmp_path):
    audit, gateway, result = await audited_gateway(tmp_path)
    calls = json.loads(gateway.audit_path.read_text(encoding="utf-8"))
    assert len(calls) == 1 and result == {"ok": True}
    call = calls[0]
    assert call["stage"] == "script" and call["status"] == "succeeded" and call["attempt"] == 1
    for prefix in ("request", "response"):
        path = audit.folder / call[f"{prefix}_artifact"]
        value = json.loads(path.read_text(encoding="utf-8"))
        assert canonical_hash(value) == call[f"{prefix}_sha256"]
        assert "private-" not in path.read_text(encoding="utf-8")
    audit.record_model_calls()
    records = json.loads(audit.records_path.read_text(encoding="utf-8"))["artifacts"]
    assert records[call["response_artifact"]]["producer_call_ids"] == [call["call_id"]]
    assert audit.verify()["artifact_hashes_valid"]


async def test_provider_http_error_does_not_archive_credential_echo(tmp_path):
    cfg = isolated_settings(tmp_path)
    path = tmp_path / "model_calls.json"
    gateway = ModelGateway(cfg, httpx.MockTransport(lambda _: httpx.Response(401, text="private-model-fixture")),
                           audit_path=path)
    with pytest.raises(ModelError, match="HTTP 401") as error:
        await gateway.generate_json("fixture system", "fixture topic")
    assert "private-model-fixture" not in str(error.value)
    for file in tmp_path.rglob("*.json"):
        assert "private-model-fixture" not in file.read_text(encoding="utf-8")
    call = json.loads(path.read_text(encoding="utf-8"))[0]
    assert call["status"] == "failed" and call["error_code"] == "http_401"


async def test_model_audit_redacts_credentials_even_with_json_escape_characters(tmp_path):
    secret = 'private-"quoted\\fixture'
    cfg = isolated_settings(tmp_path, model_api_key=secret)
    audit, _, _ = await audited_gateway(tmp_path, cfg, response={"echo": secret})
    for path in audit.folder.rglob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert all(secret not in text for text in strings(value)), path.name


async def test_model_usage_metadata_cannot_leak_credentials(tmp_path):
    cfg = isolated_settings(tmp_path)
    audit = FrozenRun(cfg, tmp_path / "run", "isolated topic")
    body = {"choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 5, "provider_note": "private-voice-fixture"}}
    gateway = ModelGateway(cfg, httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
                           audit_path=audit.folder / "model_calls.json")
    await gateway.generate_json("fixture system", "fixture topic")
    assert "private-voice-fixture" not in gateway.audit_path.read_text(encoding="utf-8")


async def test_model_call_record_rejects_response_changed_before_registration(tmp_path):
    audit, gateway, _ = await audited_gateway(tmp_path)
    call = json.loads(gateway.audit_path.read_text(encoding="utf-8"))[0]
    save_json(audit.folder / call["response_artifact"], {"ok": "external edit"})
    with pytest.raises(ValueError):
        audit.record_model_calls()


async def test_recorded_model_call_cannot_be_rebaselined_after_external_edit(tmp_path):
    audit, gateway, _ = await audited_gateway(tmp_path)
    audit.record_model_calls()
    call = json.loads(gateway.audit_path.read_text(encoding="utf-8"))[0]
    save_json(audit.folder / call["response_artifact"], {"ok": "external edit"})
    with pytest.raises(ValueError):
        audit.record_model_calls()


async def test_each_call_artifact_links_only_its_own_call(tmp_path):
    audit, gateway, _ = await audited_gateway(tmp_path)
    gateway.stage = "director"
    await gateway.generate_json("fixture system", "second fixture prompt")
    audit.record_model_calls()
    calls = json.loads(gateway.audit_path.read_text(encoding="utf-8"))
    records = json.loads(audit.records_path.read_text(encoding="utf-8"))["artifacts"]
    assert len(calls) == 2
    for call in calls:
        for kind in ("request_artifact", "response_artifact"):
            assert records[call[kind]]["producer_call_ids"] == [call["call_id"]]
