"""Blender adapter for an explicitly configured, trusted scene template."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from renderers.base import RendererError, require_output, run_command, scene_filename, setting


class BlenderRenderer:
    def __init__(self, settings=None):
        self.settings = settings

    def generate(self, scene, metadata, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{scene_filename(scene)}.blender.json"
        path.write_text(
            json.dumps({"scene": scene, "metadata": metadata}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    def render(self, scene, metadata, output_dir):
        binary = setting(self.settings, "blender_path") or shutil.which("blender")
        template = setting(self.settings, "blender_template")
        if not binary or not template or not Path(template).is_file():
            raise RendererError("Blender requires BLENDER_PATH and a trusted BLENDER_TEMPLATE Python script.")
        manifest = self.generate(scene, metadata, output_dir)
        output = output_dir / f"{scene_filename(scene)}.mp4"
        run_command(
            [
                str(binary),
                "--background",
                "--python",
                str(Path(template).resolve()),
                "--",
                "--manifest",
                str(manifest.resolve()),
                "--output",
                str(output.resolve()),
            ]
        )
        return require_output(output)
