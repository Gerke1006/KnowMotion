import sys
from pathlib import Path
from types import ModuleType

from PIL import Image, ImageDraw, ImageFont
import pytest

from renderers.base import RendererError
from renderers.canvas import CanvasRenderer, MixedScriptDraw


def scene(component="general.title", parameters=None):
    return {"scene_id": "s1", "title": "数学 Mathematics", "narration": "顺便一提，这是新的字幕样式。",
            "duration": 5, "components": [{"id": component, "parameters": parameters or {"title": "知识"}}]}


def fake_latex(monkeypatch, tmp_path):
    calls = []
    glyph = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    ImageDraw.Draw(glyph).rectangle((5, 5, 110, 50), fill=(0, 0, 0, 255))
    path = tmp_path / "formula.png"
    glyph.save(path)
    module = ModuleType("renderers.latex")
    def render(expression, *args, **kwargs):
        calls.append(expression)
        return path
    module.render_latex_png = render
    monkeypatch.setitem(sys.modules, "renderers.latex", module)
    return calls


def test_mixed_script_uses_distinct_body_latin_and_subtitle_fonts():
    renderer = CanvasRenderer()
    draw = MixedScriptDraw(Image.new("RGB", (600, 200)), renderer._english_font)
    body = ImageFont.truetype(renderer._font, 32)
    caption = ImageFont.truetype(renderer._subtitle_font, 32)
    assert draw.font_for("中", body).path == body.path
    assert Path(draw.font_for("A", body).path) == Path(renderer._english_font)
    assert draw.font_for("中", caption).path == caption.path
    assert Path(caption.path) != Path(body.path)
    assert draw.textlength("中文 ABC", font=body) > draw.textlength("中文", font=body)


def test_subtitle_is_white_with_navy_outline():
    output = CanvasRenderer().frame(scene(), {"width": 1280, "height": 720}, .5)
    colors = set(output.crop((0, 590, 1280, 710)).getdata())
    assert (255, 255, 255) in colors
    assert (22, 16, 68) in colors


def test_subtitle_finishes_with_narration_before_visual_hold():
    renderer = CanvasRenderer()
    source = scene()
    source.update(duration=20, audio={"narration_duration": 8},
                  narration="首先观察曲线上的两个点，理解平均变化率。" * 6 + "最后，导数描述瞬时变化率。")
    spoken_end = renderer.frame(source, {"width": 1280, "height": 720}, .5)
    scene_end = renderer.frame(source, {"width": 1280, "height": 720}, 1)
    region = (0, 590, 1280, 710)
    assert spoken_end.crop(region).tobytes() == scene_end.crop(region).tobytes()


def test_formula_uses_latex_and_cached_raster(monkeypatch, tmp_path):
    calls = fake_latex(monkeypatch, tmp_path)
    renderer = CanvasRenderer()
    source = scene("math.formula", {"latex": r"\int_0^2 x^2\,dx=\frac{8}{3}"})
    for progress in (.1, .5, .9):
        renderer.frame(source, {"width": 640, "height": 360}, progress)
    assert calls == [source["components"][0]["parameters"]["latex"]]


def test_dynamic_numbers_do_not_recompile_latex_each_frame(monkeypatch, tmp_path):
    calls = fake_latex(monkeypatch, tmp_path)
    renderer = CanvasRenderer()
    source = scene("math.derivative_secant", {"function": "x**2", "x_range": [-1, 3], "x0": 1,
                                               "dx_start": 1.5, "dx_end": .02})
    for progress in (.1, .3, .7, 1):
        renderer.frame(source, {"width": 640, "height": 360}, progress)
    assert calls == [r"\Delta x=", r"\frac{\Delta y}{\Delta x}="]


def test_missing_latex_does_not_turn_into_plain_text():
    with pytest.raises(RendererError, match="parameters.latex"):
        CanvasRenderer().frame(scene("math.formula", {"title": "no equation"}), {"width": 640, "height": 360}, .5)
