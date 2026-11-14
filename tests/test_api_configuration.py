"""Isolated configuration regressions; these do not replace live video acceptance."""
import asyncio
import json
import secrets
from threading import Event
import time

from fastapi.testclient import TestClient
import pytest

from api.configuration import ApiConfiguration
from api.main import create_app
from harness.settings import Settings, secret_value


def config_for(tmp_path, **changes):
    return Settings(_env_file=None, project_root=tmp_path, output_dir=tmp_path / "outputs",
                    database_url="sqlite:///:memory:", **changes)


def test_api_configuration_persists_and_resets_without_exposing_or_overwriting_env(tmp_path):
    original_key, custom_key, voice_key = [secrets.token_urlsafe() for _ in range(3)]
    defaults = config_for(tmp_path, model_name="default-model", model_api_key=original_key)
    env = tmp_path / ".env"
    env.write_text("fixture environment remains unchanged", encoding="utf-8")
    settings_file = tmp_path / "data" / "runtime-api-settings.json"

    with TestClient(create_app(defaults)) as client:
        initial = client.get("/settings/api").json()
        assert initial["model_name"] == "default-model"
        assert initial["model_key_configured"] is True
        assert initial["minimax_key_configured"] is False
        assert initial["customized"] is False
        updated = client.put("/settings/api", json={
            "model_base_url": "https://provider.example/v1/", "model_name": "custom-model",
            "model_api_key": custom_key, "minimax_api_key": voice_key,
        })
        assert updated.status_code == 200
        assert updated.json()["model_base_url"] == "https://provider.example/v1"
        assert updated.json()["model_name"] == "custom-model"
        assert updated.json()["customized"] is True
        assert updated.json()["minimax_key_configured"] is True
        assert all(value not in updated.text for value in [original_key, custom_key, voice_key])
        assert not {"model_api_key", "minimax_api_key"}.intersection(updated.json())
        assert settings_file.is_file()
        unchanged = client.put("/settings/api", json={"model_api_key": " ", "minimax_api_key": ""})
        assert unchanged.status_code == 200
        assert ApiConfiguration(defaults, settings_file).snapshot().model_api_key.get_secret_value() == custom_key
        assert client.get("/jobs").json() == []

    with TestClient(create_app(defaults)) as client:
        assert client.get("/settings/api").json()["model_name"] == "custom-model"
        reset = client.delete("/settings/api")
        assert reset.status_code == 200
        assert reset.json()["model_name"] == "default-model"
        assert reset.json()["customized"] is False
        assert reset.json()["model_key_configured"] is True
        assert reset.json()["minimax_key_configured"] is False
        assert not settings_file.exists()
    assert env.read_text(encoding="utf-8") == "fixture environment remains unchanged"


def test_api_configuration_is_protected_and_validation_never_echoes_credentials(tmp_path):
    key = secrets.token_urlsafe()
    token = secrets.token_urlsafe()
    with TestClient(create_app(config_for(tmp_path, api_token=token))) as client:
        for method in ("GET", "PUT", "DELETE"):
            assert client.request(method, "/settings/api").status_code == 401
        client.headers["Authorization"] = f"Bearer {token}"
        cases = [
            {"model_api_key": [key]},
            {"unknown_field": key},
            {"model_base_url": "https://example.com?key=" + key},
            {"model_base_url": "https://user:" + key + "@example.com"},
            {"model_base_url": "file:///" + key},
            {"model_api_key": key, "model_name": ""},
            [],
        ]
        for payload in cases:
            response = client.put("/settings/api", json=payload)
            assert response.status_code == 422
            assert key not in response.text
        malformed = client.put("/settings/api", content='{"model_api_key":"' + key)
        assert malformed.status_code == 422
        assert key not in malformed.text
        oversized = client.put("/settings/api", content=key * 1000)
        assert oversized.status_code == 413
        assert key not in oversized.text
        assert not (tmp_path / "data" / "runtime-api-settings.json").exists()


def test_settings_changes_only_affect_jobs_that_have_not_started(tmp_path):
    original_key, replacement_key = [secrets.token_urlsafe() for _ in range(2)]
    started = Event()
    release = Event()
    observations = []

    class Producer:
        def __init__(self, settings, repository):
            self.settings = settings
            self.repository = repository

        async def run(self, job_id):
            self.repository.update(job_id, status="running", stage="identify")
            if not observations:
                started.set()
                while not release.is_set():
                    await asyncio.sleep(.01)
            observations.append((self.settings.model_name, secret_value(self.settings.model_api_key)))
            return self.repository.update(job_id, status="succeeded", stage="complete", progress=1)

    defaults = config_for(tmp_path, model_name="first", model_api_key=original_key, local_workers=1)
    with TestClient(create_app(defaults, orchestrator_factory=Producer)) as client:
        first = client.post("/jobs", json={"topic": "first isolated fixture"}).json()
        assert started.wait(3)
        second = client.post("/jobs", json={"topic": "queued isolated fixture"}).json()
        assert client.put("/settings/api", json={"model_name": "second", "model_api_key": replacement_key}).status_code == 200
        release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and len(observations) < 2:
            time.sleep(.01)
        assert observations == [("first", original_key), ("second", replacement_key)]
        for job in (first, second):
            body = client.get(f'/jobs/{job["id"]}').text
            assert original_key not in body and replacement_key not in body


def test_corrupt_configuration_does_not_dump_payload(tmp_path):
    key = secrets.token_urlsafe()
    path = tmp_path / "data" / "runtime-api-settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"model_api_key": key, "model_name": []}), encoding="utf-8")
    with pytest.raises(RuntimeError) as failure:
        create_app(config_for(tmp_path))
    assert key not in str(failure.value)


def test_temporal_configuration_cannot_claim_to_override_remote_workers(tmp_path, monkeypatch):
    temporal_client = pytest.importorskip("temporalio.client")

    class Client:
        async def start_workflow(self, *args, **kwargs):
            pass

    async def connect(*args, **kwargs):
        return Client()

    monkeypatch.setattr(temporal_client.Client, "connect", connect)
    defaults = config_for(tmp_path, execution_backend="temporal")
    with TestClient(create_app(defaults)) as client:
        assert client.get("/settings/api").json()["editable"] is False
        assert client.put("/settings/api", json={"model_name": "remote"}).status_code == 409
        assert client.delete("/settings/api").status_code == 409
