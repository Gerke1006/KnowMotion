"""Small-model gateway. Only transient transport errors are retried; no AI review loop."""
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from harness.settings import Settings, secret_value


class ModelError(RuntimeError):
    pass


class ModelGateway:
    def __init__(self, settings: Settings, transport=None, audit_path: Path | None = None):
        self.settings = settings
        self.transport = transport
        self.audit_path = audit_path

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
                try:
                    response = await client.post(
                        cfg.model_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + key}, json=payload,
                    )
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < cfg.model_retries:
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    if response.is_error:
                        # Provider response bodies may include request credentials; never persist them.
                        raise ModelError(f"模型服务返回 HTTP {response.status_code}")
                    body = response.json()
                    if body.get("base_resp", {}).get("status_code", 0) != 0:
                        raise ModelError("模型服务拒绝了请求，请检查配置与账号状态。")
                    content = body["choices"][0]["message"]["content"]
                    result = self.parse_json(content)
                    if self.audit_path:
                        calls = json.loads(self.audit_path.read_text(encoding="utf-8")) if self.audit_path.exists() else []
                        calls.append({
                            "model": cfg.model_name,
                            "provider": urlsplit(cfg.model_base_url).hostname,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "response_sha256": hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                            "usage": body.get("usage", {}),
                        })
                        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
                        temp = self.audit_path.with_suffix(".tmp")
                        temp.write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
                        temp.replace(self.audit_path)
                    return result
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= cfg.model_retries:
                        raise ModelError("模型服务网络请求失败或超时") from exc
                    await asyncio.sleep(min(2 ** attempt, 8))
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise ModelError("模型返回值不符合 JSON 对象协议") from exc
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
