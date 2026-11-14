"""Optional project-based Remotion adapter; no silent fallback for missing projects."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from renderers.base import RendererError, require_output, run_command, scene_filename, setting


class RemotionRenderer:
    def __init__(self, settings=None):
        self.settings = settings

    def generate(self, scene, metadata, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{scene_filename(scene)}.remotion.json"
        path.write_text(
            json.dumps({"scene": scene, "metadata": metadata}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    def render(self, scene, metadata, output_dir):
        project = setting(self.settings, "remotion_project")
        if not project or not Path(project).is_dir():
            raise RendererError(
                "Remotion requires REMOTION_PROJECT with an installed @remotion/cli and KnowledgeScene composition."
            )
        project = Path(project).resolve()
        cli = project / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        node = shutil.which("node")
        entry = project / setting(self.settings, "remotion_entry", "src/index.ts")
        if not node or not cli.is_file() or not entry.is_file():
            raise RendererError(
                "Remotion project needs node, local @remotion/cli, and its configured entrypoint."
            )
        props = self.generate(scene, metadata, output_dir)
        output = output_dir / f"{scene_filename(scene)}.mp4"
        run_command(
            [
                node,
                str(cli),
                "render",
                str(entry),
                "KnowledgeScene",
                str(output.resolve()),
                "--props",
                str(props.resolve()),
                "--codec",
                "h264",
            ],
            cwd=project,
        )
        return require_output(output)
