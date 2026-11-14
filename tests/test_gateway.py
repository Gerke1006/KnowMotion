import httpx
import pytest

from harness.model_gateway import ModelError, ModelGateway
from harness.settings import Settings


async def test_gateway_retries_only_transient_status_and_parses_json():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"ok":true}\n```'}}]})
    cfg = Settings(_env_file=None, model_name="small-model", model_api_key="test")
    result = await ModelGateway(cfg, httpx.MockTransport(handler)).generate_json("system", "topic")
    assert result == {"ok": True}
    assert len(calls) == 2
    assert calls[0].headers["Authorization"] == "Bearer test"


async def test_auth_error_body_never_leaks_credentials():
    cfg = Settings(_env_file=None, model_name="small-model", model_api_key="private-value")
    gateway = ModelGateway(cfg, httpx.MockTransport(lambda _: httpx.Response(401, text="private-value")))
    with pytest.raises(ModelError, match="HTTP 401") as error:
        await gateway.generate_json("system", "topic")
    assert "private-value" not in str(error.value)


def test_json_requires_object():
    with pytest.raises(ValueError):
        ModelGateway.parse_json("[]")
