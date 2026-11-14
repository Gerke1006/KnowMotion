from __future__ import annotations

import importlib.util
import copy
import json
import shutil
import sys
from pathlib import Path

from renderers.base import RendererError, require_output, run_command, scene_filename, setting


def component_formulas(component: dict) -> dict[str, str]:
    """Static math fragments are typeset once, while moving numeric values stay dynamic."""
    kind, params = component.get("id", ""), component.get("parameters", {})
    if kind == "math.derivative_secant":
        return {"dx": r"\Delta x =", "slope": r"\frac{\Delta y}{\Delta x} =", "tangent": r"f'(x_0) ="}
    if kind == "math.integral_riemann":
        return {"integral": r"\int_a^b f(x)\,\mathrm{d}x=\lim_{n\to\infty}\sum_{i=1}^n f(x_i^*)\,\Delta x"}
    if kind == "math.pythagorean":
        a, b = float(params.get("a", 3)), float(params.get("b", 4))
        return {"a": "a^2", "b": "b^2", "c": "c^2", "area_a": f"a^2={a*a:g}",
                "area_b": f"b^2={b*b:g}", "total": f"a^2+b^2={a*a+b*b:g}=c^2"}
    if kind == "math.formula" or params.get("latex") or params.get("formula"):
        expression = params.get("latex") or params.get("formula")
        if not isinstance(expression, str) or not expression.strip():
            raise RendererError("A math.formula component requires a nonempty LaTeX expression")
        return {"main": expression, **{f"step_{index+1}": step for index, step in enumerate(params.get("steps", []))}}
    return {}


class ManimRenderer:
    def __init__(self, settings=None):
        self.settings = settings
        self.python = str(setting(settings, "manim_python", None) or sys.executable)

    def available(self) -> bool:
        if self.python == sys.executable:
            return importlib.util.find_spec("manim") is not None
        try:
            run_command([self.python, "-c", "import manim"], timeout=20)
            return True
        except RendererError:
            return False

    def generate(self, scene: dict, metadata: dict, output_dir: Path) -> Path:
        scene_filename(scene)
        output_dir.mkdir(parents=True, exist_ok=True)
        scene = copy.deepcopy(scene)
        for component in scene.get("components", []):
            expressions = component_formulas(component)
            if expressions:
                from renderers.latex import render_latex_svg
                assets = {}
                for name, expression in expressions.items():
                    path = render_latex_svg(expression, output_dir / "latex", self.settings)
                    assets[name] = Path(path).resolve().relative_to(output_dir.resolve()).as_posix()
                component.setdefault("parameters", {})["_latex_assets"] = assets
        # All executable code is a trusted template; model data remains a JSON literal.
        # Copy the trusted runtime so each scene source is editable and rerunnable.
        shutil.copyfile(Path(__file__).with_name("runtime.py"), output_dir / "vibe_manim_runtime.py")
        shutil.copyfile(Path(__file__).parents[1] / "base.py", output_dir / "vibe_render_base.py")
        shutil.copyfile(Path(__file__).with_name("typography.py"), output_dir / "vibe_typography.py")
        shutil.copyfile(Path(__file__).with_name("math_runtime.py"), output_dir / "vibe_math_runtime.py")
        shutil.copyfile(Path(__file__).parents[2] / "harness" / "math_animation.py", output_dir / "vibe_math_animation.py")
        data = json.dumps(
            {
                "scene": scene,
                "metadata": metadata,
                "fonts": {
                    "chinese": setting(self.settings, "chinese_font", "SimSun"),
                    "english": setting(self.settings, "english_font", "Times New Roman"),
                    "subtitle": setting(self.settings, "subtitle_font", "Microsoft YaHei"),
                    "subtitle_weight": setting(self.settings, "subtitle_font_weight", "BOLD"),
                    "subtitle_color": setting(self.settings, "subtitle_color", "#FFFFFF"),
                    "outline_color": setting(self.settings, "subtitle_outline_color", "#161044"),
                    "outline_width": setting(self.settings, "subtitle_outline_width", 5),
                },
            },
            ensure_ascii=False,
        )
        source = (
            "# Generated from trusted Vibe component templates. Model output is data only.\n"
            "import json\nfrom manim import Scene\nfrom vibe_manim_runtime import construct_scene\n\n"
            f"DATA = json.loads({data!r})\n\n"
            "class KnowledgeScene(Scene):\n"
            "    def construct(self):\n"
            "        construct_scene(self, DATA['scene'], DATA['metadata'], DATA['fonts'])\n"
        )
        path = output_dir / f"{scene_filename(scene)}.py"
        path.write_text(source, encoding="utf-8")
        return path

    def render(self, scene: dict, metadata: dict, output_dir: Path) -> Path:
        if not self.available():
            raise RendererError(
                "Manim is not installed. Install the [manim] extra or select renderer='canvas'."
            )
        source = self.generate(scene, metadata, output_dir)
        media = output_dir / (scene_filename(scene) + "_media")
        name = scene_filename(scene) + ".mp4"
        args = [
            self.python,
            "-m",
            "manim",
            "--disable_caching",
            "--format",
            "mp4",
            "--resolution",
            f"{metadata.get('width', 1280)},{metadata.get('height', 720)}",
            "--fps",
            str(metadata.get("fps", 24)),
            "--media_dir",
            str(media.resolve()),
            "--output_file",
            name,
            str(source.resolve()),
            "KnowledgeScene",
        ]
        run_command(args, cwd=output_dir.resolve())
        candidates = [p for p in media.rglob(name) if "partial_movie_files" not in p.parts]
        if len(candidates) != 1:
            raise RendererError("Manim did not produce exactly one scene video")
        target = output_dir / name
        shutil.copyfile(candidates[0], target)
        return require_output(target)
