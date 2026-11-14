"""Metadata-only asset retrieval, with complete/composed/generated provenance."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from harness.schemas import AssetManifest, AssetSelection, VisualPlan


class AssetRetriever:
    def __init__(self, catalog_path: Path | str | None = None):
        self.catalog_path = Path(catalog_path) if catalog_path else Path(__file__).resolve().parents[1] / "assets" / "catalog.json"
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.assets: list[dict[str, Any]] = raw["assets"] if isinstance(raw, dict) else raw
        ids = [item["id"] for item in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("素材目录包含重复 ID")

    def history_candidates(self, segments=None) -> dict:
        """Small typed inventory; the production Agent chooses actors, props and sounds."""
        path = self.catalog_path.parent / "history" / "animation_resources.json"
        resources = json.loads(path.read_text(encoding="utf-8"))
        for kind in ("environments", "visual_assets", "sfx_assets"):
            ids = [item["id"] for item in resources[kind]]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate history resource IDs in {kind}")
        if segments is not None:
            candidates = []
            for raw in segments:
                segment = raw.model_dump() if hasattr(raw, "model_dump") else raw
                intent = str(segment["intent"])
                # Topic-independent lexical retrieval over the declared narrative intent.
                words = re.findall(r"[A-Za-z]+|[\u3400-\u9fff]+", intent.casefold())
                terms = set(words)
                terms.update(word[i:i + 2] for word in words for i in range(len(word) - 1))
                def rank(card):
                    description = json.dumps({key: card.get(key) for key in ("description", "intents", "conditions")},
                                             ensure_ascii=False).casefold()
                    return -sum(len(term) for term in terms if term in description)
                selected = {"segment_id": segment["id"], "intent": intent}
                for kind, key, limit in (("environments", "environment_ids", 3),
                                         ("visual_assets", "visual_ids", 6), ("sfx_assets", "sfx_ids", 5)):
                    selected[key] = [card["id"] for card in sorted(resources[kind], key=rank)[:limit]]
                candidates.append(selected)
            resources["intent_candidates"] = candidates
        return resources

    def search(self, *, domain: str | None = None, scene: str | None = None, animation: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        def matches(asset: dict[str, Any]) -> bool:
            return ((not domain or domain in asset.get("domains", []) or "general" in asset.get("domains", []))
                    and (not scene or scene in asset.get("scenes", []))
                    and (not animation or animation in asset.get("animations", []))
                    and (not kind or kind == asset.get("kind")))
        return [asset for asset in self.assets if matches(asset)]

    def retrieve(self, visual: VisualPlan) -> AssetManifest:
        selections = []
        for scene in visual.scenes:
            for component in scene.components:
                candidates = self.search(domain=scene.domain.value, kind="animation")
                exact = next((item for item in candidates if item.get("component_id") == component.id and item.get("level") == "complete"), None)
                if exact:
                    tier, ids = "complete", [exact["id"]]
                else:
                    # Basis assets advertise the composed IDs they can implement, not merely similar tags.
                    basic = [item for item in candidates if component.id in item.get("supports", []) and item.get("level") == "basic"]
                    if basic:
                        tier, ids = "composed", [item["id"] for item in basic]
                    else:
                        tier, ids = "generated", ["primitive.generic"]
                selections.append(AssetSelection(scene_id=scene.scene_id, component_id=component.id,
                                                  tier=tier, asset_ids=ids, parameters=component.parameters))
        return AssetManifest(assets=selections)
