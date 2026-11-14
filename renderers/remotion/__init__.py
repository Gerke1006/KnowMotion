"""Bundled History Remotion project and configurable trusted external projects."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from filelock import FileLock

from renderers.base import RendererError, require_output, run_command, scene_filename, setting

BUNDLED_PROJECT = Path(__file__).with_name("project")


class RemotionRenderer:
    def __init__(self, settings=None):
        self.settings = settings
        configured = setting(settings, "remotion_project", "")
        self.project = (Path(configured) if configured else BUNDLED_PROJECT).resolve()

    def dependencies(self) -> tuple[str, Path, Path]:
        node = shutil.which("node")
        cli = self.project / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        entry = self.project / setting(self.settings, "remotion_entry", "src/index.ts")
        if not node or not cli.is_file() or not entry.is_file():
            raise RendererError(
                f'Remotion requires Node.js and installed project dependencies. Run npm ci --prefix "{self.project}"; '
                "the entry must register KnowledgeScene."
            )
        return node, cli, entry

    def preflight(self, *, ensure_browser: bool = False) -> None:
        node, cli, _ = self.dependencies()
        browser = setting(self.settings, "remotion_browser_executable", "")
        if browser:
            if not Path(browser).is_file():
                raise RendererError("REMOTION_BROWSER_EXECUTABLE does not point to an installed browser")
        elif ensure_browser:
            lock_path = self.project / "node_modules" / ".cache" / "vibe-browser.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(lock_path, timeout=600):
                run_command([node, str(cli), "browser", "ensure", "--log=error"], cwd=self.project, timeout=600)

    def fingerprint(self) -> str:
        """Include TS, browser assets and pinned packages in scene cache validity."""
        digest = hashlib.sha256()
        paths = [self.project / name for name in ("package.json", "package-lock.json", "remotion.config.ts", "tsconfig.json")]
        paths += [p for folder in ("src", "public") for p in (self.project / folder).rglob("*") if p.is_file()]
        for path in sorted(paths):
            if path.is_file():
                digest.update(path.relative_to(self.project).as_posix().encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def generate(self, scene, metadata, output_dir):
        self.preflight()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        scene = copy.deepcopy(scene)
        director = scene.pop("director", None)
        sources = scene.get("extensions", {}).get("historical_sources", [])
        for index, component in enumerate(scene.get("components", [])):
            if component.get("id", "").startswith("history."):
                from harness.history import normalize_history_component
                scene["components"][index] = normalize_history_component(
                    component, sources=sources, require_sources=metadata.get("mode") == "live"
                )
                asset = scene["components"][index]["parameters"].get("portrait_asset")
                if asset:
                    catalog = self.project / "public" / "portraits" / "SOURCES.json"
                    records = json.loads(catalog.read_text(encoding="utf-8")).get("assets", []) if catalog.is_file() else []
                    licensed = next((item for item in records if item.get("path") == asset
                                     and item.get("license") and item.get("source_url") and item.get("caption")), None)
                    image = (self.project / "public" / asset).resolve()
                    if not licensed or not image.is_relative_to((self.project / "public").resolve()) or not image.is_file():
                        raise RendererError("Historical portraits require an existing approved asset with license, source and caption")
        fonts = {
            "chinese": setting(self.settings, "chinese_font", "SimSun"),
            "english": setting(self.settings, "english_font", "Times New Roman"),
            "subtitle": setting(self.settings, "subtitle_font", "Microsoft YaHei"),
            "subtitle_weight": setting(self.settings, "subtitle_font_weight", "BOLD"),
            "subtitle_color": setting(self.settings, "subtitle_color", "#FFFFFF"),
            "outline_color": setting(self.settings, "subtitle_outline_color", "#161044"),
            "outline_width": setting(self.settings, "subtitle_outline_width", 5),
            "background_opacity": setting(self.settings, "subtitle_background_opacity", .18),
        }
        path = output_dir / f"{scene_filename(scene)}.remotion.json"
        props = {"scene": scene, "metadata": metadata, "fonts": fonts, "sources": sources}
        if director is not None:
            if director.get("protocol") != "history-director-v2":
                raise RendererError("Unsupported history director protocol")
            props["director"] = director
        path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def check_director(self, props: Path, output: Path) -> dict:
        node, _, _ = self.dependencies()
        expected_hash = hashlib.sha256(props.read_bytes()).hexdigest()
        # A previous pass must never survive a crashed check of different props.
        output.unlink(missing_ok=True)
        command = [node, str(self.project / "node_modules/tsx/dist/cli.mjs"),
                   str(self.project / "tools/check-director.ts"), "--props", str(props.resolve()),
                   "--output", str(output.resolve())]
        try:
            run_command(command, cwd=self.project, timeout=120)
        except RendererError:
            if not output.is_file():
                raise
        if not output.is_file():
            raise RendererError("Director frame evaluator did not return an execution report")
        report = json.loads(output.read_text(encoding="utf-8"))
        if report.get("props_sha256") != expected_hash:
            raise RendererError("Director execution report does not match the current props fingerprint")
        return report

    def render(self, scene, metadata, output_dir):
        node, cli, entry = self.dependencies()
        props = self.generate(scene, metadata, output_dir)
        output = output_dir / f"{scene_filename(scene)}.mp4"
        args = [node, str(cli), "render", str(entry), "KnowledgeScene", str(output.resolve()),
                "--props", str(props.resolve()), "--codec=h264", "--crf=20", "--pixel-format=yuv420p",
                "--image-format=jpeg", "--jpeg-quality=95", "--x264-preset=fast", "--log=error",
                "--concurrency", str(setting(self.settings, "remotion_concurrency", 2)), "--timeout=120000"]
        browser = setting(self.settings, "remotion_browser_executable", "")
        if browser:
            args += ["--browser-executable", str(browser)]
        log = run_command(args, cwd=self.project)
        (Path(output_dir) / "remotion-render.log").write_text(log, encoding="utf-8")
        return require_output(output)
