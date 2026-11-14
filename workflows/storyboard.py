"""Join validated teaching, visuals and asset selection into a renderer-neutral plan."""
from __future__ import annotations

from harness.schemas import AssetManifest, TeachingPlan, VideoPlan, VisualPlan


def build_storyboard(teaching: TeachingPlan, visual: VisualPlan, manifest: AssetManifest) -> VideoPlan:
    if {scene.scene_id for scene in teaching.scenes} != {scene.scene_id for scene in visual.scenes}:
        raise ValueError("教学计划与视觉计划的场景不一致")
    selected = {(asset.scene_id, asset.component_id): asset for asset in manifest.assets}
    scenes = []
    for scene in visual.scenes:
        updated = scene.model_copy(deep=True)
        for component in updated.components:
            selection = selected.get((scene.scene_id, component.id))
            if selection is None:
                raise ValueError(f"缺少素材选择：{scene.scene_id}/{component.id}")
        updated.extensions["asset_selections"] = [asset.model_dump(mode="json") for asset in manifest.assets if asset.scene_id == scene.scene_id]
        scenes.append(updated)
    duration = sum(scene.duration for scene in scenes)
    return VideoPlan(metadata=teaching.request, domain=teaching.request.domain,
                     learning_objectives=teaching.learning_objectives, teaching_structure=teaching.teaching_structure,
                     scenes=scenes, style=visual.style, sources=teaching.sources,
                     music_timeline=[{"at": 0, "action": "fade_in", "duration": min(2, duration / 10), "gain": 0.12},
                                     {"at": max(0, duration - 2), "action": "fade_out", "duration": min(2, duration)}])
