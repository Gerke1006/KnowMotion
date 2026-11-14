"""Small-model gateway. Only transient transport errors are retried; no AI review loop."""
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from harness.settings import Settings, secret_value


class ModelError(RuntimeError):
    def __init__(self, message, *, code="model_error"):
        super().__init__(message)
        self.code = code


class ModelGateway:
    def __init__(self, settings: Settings, transport=None, audit_path: Path | None = None):
        self.settings = settings
        self.transport = transport
        self.audit_path = audit_path
        self.stage = "unspecified"
        self.last_response = None

    def sanitize(self, value):
        """Redact credentials before returning or retaining provider-supplied content."""
        if isinstance(value, dict):
            return {self.sanitize(key): self.sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.sanitize(item) for item in value]
        if isinstance(value, str):
            for name in ("model_api_key", "minimax_api_key", "api_token", "s3_secret_key"):
                secret = secret_value(getattr(self.settings, name, ""))
                if secret:
                    for variant in (secret, json.dumps(secret, ensure_ascii=False)[1:-1],
                                    json.dumps(secret, ensure_ascii=True)[1:-1]):
                        value = value.replace(variant, "[REDACTED]")
        return value

    def _audit(self, call_id, payload, result, *, attempt, started_at, status, error_code=None, usage=None):
        if not self.audit_path:
            return
        from harness.production_audit import save_json
        payload, result = self.sanitize(payload), self.sanitize(result)
        request_name = f"calls/{call_id}.request.json"
        response_name = f"calls/{call_id}.response.json"
        save_json(self.audit_path.parent / request_name, payload)
        save_json(self.audit_path.parent / response_name, result)
        calls = json.loads(self.audit_path.read_text(encoding="utf-8")) if self.audit_path.exists() else []
        calls.append({
            "call_id": call_id, "stage": self.stage, "attempt": attempt,
            "model": self.settings.model_name, "provider": urlsplit(self.settings.model_base_url).hostname,
            "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": status, "error_code": error_code,
            "request_artifact": request_name, "response_artifact": response_name,
            "request_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "response_sha256": hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "usage": self.sanitize(usage or {}),
        })
        save_json(self.audit_path, calls)

    async def generate_json(self, system: str, prompt: str) -> dict:
        cfg = self.settings
        key = secret_value(cfg.model_api_key)
        if not cfg.model_name or not key:
            raise ModelError("Live 模式需要配置 MODEL_NAME 和 MODEL_API_KEY；端到端验收必须使用项目的真实模型。")
        payload = {
            "model": cfg.model_name,
            "messages": [
                {"role": "system", "content": system + "\nReturn exactly one JSON object, no markdown."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.35,
            "max_tokens": cfg.model_max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=cfg.model_timeout, transport=self.transport) as client:
            for attempt in range(cfg.model_retries + 1):
                call_id = uuid4().hex
                started_at = datetime.now(timezone.utc).isoformat()
                self.last_response = None
                usage = None
                try:
                    response = await client.post(
                        cfg.model_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + key}, json=payload,
                    )
                    if response.is_error:
                        # Read usage alone from an error body; never retain provider text/headers.
                        try:
                            error_body = response.json()
                            usage = error_body.get("usage") if isinstance(error_body, dict) else None
                        except ValueError:
                            usage = None
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < cfg.model_retries:
                        self._audit(call_id, payload, None, attempt=attempt + 1, started_at=started_at,
                                    status="failed", error_code=f"http_{response.status_code}", usage=usage)
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    if response.is_error:
                        # Provider response bodies may include request credentials; never persist them.
                        self._audit(call_id, payload, None, attempt=attempt + 1, started_at=started_at,
                                    status="failed", error_code=f"http_{response.status_code}", usage=usage)
                        raise ModelError(f"模型服务返回 HTTP {response.status_code}", code="transport")
                    body = response.json()
                    usage = body.get("usage", {}) if isinstance(body, dict) else None
                    if body.get("base_resp", {}).get("status_code", 0) != 0:
                        self._audit(call_id, payload, None, attempt=attempt + 1, started_at=started_at,
                                    status="failed", error_code="provider_rejected", usage=usage)
                        raise ModelError("模型服务拒绝了请求，请检查配置与账号状态。")
                    content = self.sanitize(body["choices"][0]["message"]["content"])
                    self.last_response = content
                    result = self.parse_json(content)
                    self._audit(call_id, payload, result, attempt=attempt + 1, started_at=started_at,
                                status="succeeded", usage=body.get("usage", {}))
                    return result
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    self._audit(call_id, payload, None, attempt=attempt + 1, started_at=started_at,
                                status="failed", error_code="network")
                    if attempt >= cfg.model_retries:
                        raise ModelError("模型服务网络请求失败或超时", code="transport") from exc
                    await asyncio.sleep(min(2 ** attempt, 8))
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    self._audit(call_id, payload, self.last_response, attempt=attempt + 1, started_at=started_at,
                                status="failed", error_code="format", usage=usage)
                    raise ModelError("模型返回值不符合 JSON 对象协议", code="format") from exc
        raise ModelError("模型调用失败")

    @staticmethod
    def parse_json(content: str) -> dict:
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("Expected JSON object")
        return value
