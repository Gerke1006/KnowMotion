"""Small, provenance-preserving research stage with an explicit offline demo mode."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from harness.schemas import VideoRequest
from workflows.planning import demo_lesson

USER_AGENT = "VibeKnowledgeAgent/0.1 (educational video research; local development)"


async def _wiki_sources(topic: str, language: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
    endpoint = f"https://{language}.wikipedia.org/w/api.php"
    response = await client.get(endpoint, params={"action": "query", "format": "json", "list": "search", "srsearch": topic, "srlimit": 3})
    response.raise_for_status()
    pages = response.json().get("query", {}).get("search", [])
    if not pages:
        return []
    response = await client.get(endpoint, params={"action": "query", "format": "json", "prop": "extracts|info", "inprop": "url",
                                                "explaintext": 1, "exchars": 6000, "pageids": "|".join(str(page["pageid"]) for page in pages)})
    response.raise_for_status()
    result = []
    for page in response.json().get("query", {}).get("pages", {}).values():
        if page.get("extract") and page.get("fullurl"):
            result.append({"title": page["title"], "url": page["fullurl"], "excerpt": page["extract"],
                           "provider": "wikipedia", "status": "retrieved", "retrieved_at": datetime.now(timezone.utc).isoformat()})
    return result


async def research(request: VideoRequest, gateway: Any = None) -> dict[str, Any]:
    if request.mode == "demo":
        lesson = demo_lesson(request)
        return {"mode": "demo", "topic": request.topic, "knowledge": lesson.get("knowledge", []),
                "sources": [{**item, "status": "reference_not_fetched"} for item in lesson.get("sources", [])],
                "limitations": "本地人工编写示范课；所列参考链接没有在本次运行中联网获取。"}
    if gateway is None:
        raise ValueError("live 研究需要模型网关")
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        attempts = await asyncio.gather(*(_wiki_sources(request.topic, language, client) for language in ("zh", "en")), return_exceptions=True)
    sources = [source for result in attempts if isinstance(result, list) for source in result]
    if not sources:
        raise RuntimeError("没有获取到可追溯的研究资料。请检查 Wikipedia 网络连通性；可用 demo 模式运行已编写课程。")
    grounded = await gateway.generate_json(
        "你是教学资料整理员。将所给资料中的事实整理为 JSON：knowledge（字符串列表）、misconceptions（字符串列表）、"
        "limitations（字符串）。不要增加材料以外的日期、数字、引用或推测。不生成来源链接，调用者保留真实来源。",
        json.dumps({"topic": request.topic, "domain": request.domain.value, "sources": sources}, ensure_ascii=False),
    )
    return {"mode": "live", "topic": request.topic, "knowledge": grounded.get("knowledge", []),
            "misconceptions": grounded.get("misconceptions", []), "limitations": grounded.get("limitations", ""), "sources": sources}
