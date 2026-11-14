from renderers.manim.adapter import component_formulas
from renderers.manim.typography import body_lines, caption_index, caption_pages, chinese_font_ranges


def test_latin_runs_stay_in_roman_font():
    text = "导数 Derivative 与 f(x)"
    ranges = chinese_font_ranges(text, "SimSun")
    assert ranges == {"[0:2]": "SimSun", "[14:15]": "SimSun"}


def test_subtitles_preserve_all_characters_and_page_by_progress():
    text = "顺便一提，这就是计算器计算正弦函数的方法。English text stays Roman."
    pages = caption_pages(text, max_chars=20)
    assert "".join(pages) == text
    assert all(len(page) <= 20 for page in pages)
    assert caption_index(pages, 0) == 0
    assert caption_index(pages, 1) == len(pages) - 1


def test_math_fragments_are_real_latex():
    derivative = component_formulas({"id": "math.derivative_secant"})
    assert derivative["slope"] == r"\frac{\Delta y}{\Delta x} ="
    integral = component_formulas({"id": "math.integral_riemann"})
    assert r"\int" in integral["integral"] and r"\sum" in integral["integral"]
    expression = r"F(x)=\int_0^x f(t)\,\mathrm{d}t"
    assert component_formulas({"id": "math.formula", "parameters": {"latex": expression}})["main"] == expression


def test_caption_wrap_does_not_leave_punctuation_on_its_own():
    text = "这" * 30 + "。"
    pages = caption_pages(text)
    assert "".join(pages) == text
    assert all(1 < len(page) <= 30 for page in pages)


def test_caption_clock_keeps_ticking_during_static_wait(tmp_path):
    import pytest
    manim = pytest.importorskip("manim")
    from renderers.manim.runtime import construct_scene

    class CaptionScene(manim.Scene):
        def construct(self):
            construct_scene(self, {
                "scene_id": "clock", "title": "Title", "duration": 1,
                "narration": "A short caption.",
                "audio": {"narration_duration": .5, "narration_offset": .1},
                "components": [{"id": "general.title", "parameters": {"title": "Concept"}}],
            }, {}, {"chinese": "SimSun", "english": "Times New Roman", "subtitle": "Microsoft YaHei"})
            self.final_caption = next(m for m in self.mobjects if hasattr(m, "current_index"))

    # Exercise Manim's real Wait logic without encoding a fixture video.
    with manim.tempconfig({"dry_run": True, "write_to_movie": False, "disable_caching": True,
                           "media_dir": str(tmp_path), "pixel_width": 320, "pixel_height": 180,
                           "frame_rate": 10, "progress_bar": "none", "verbosity": "ERROR"}):
        scene = CaptionScene()
        scene.render()
        assert scene.time == pytest.approx(1)
        assert all(m.get_fill_opacity() == 0 for m in scene.final_caption.family_members_with_points())


def test_body_wrap_preserves_latin_words_and_explicit_lines():
    assert body_lines("中文宋体\nTimes New Roman") == ["中文宋体", "Times New Roman"]
    assert " ".join(body_lines("Calculus " * 12)).split() == ["Calculus"] * 12


def test_generated_scene_bundles_formula_assets(tmp_path, monkeypatch):
    from renderers import latex
    from renderers.manim import ManimRenderer

    calls = []

    def render(expression, output_dir, settings):
        calls.append(expression)
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"formula_{len(calls)}.svg"
        target.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 1"/></svg>')
        return target

    monkeypatch.setattr(latex, "render_latex_svg", render)
    scene = {"scene_id": "s1", "components": [{"id": "math.derivative_secant", "parameters": {}}]}
    source = ManimRenderer().generate(scene, {}, tmp_path)
    assert len(calls) == 2
    assert (tmp_path / "latex/formula_1.svg").is_file()
    assert "latex/formula_1.svg" in source.read_text(encoding="utf-8")
    assert "SimSun" in source.read_text(encoding="utf-8")
    assert "Times New Roman" in source.read_text(encoding="utf-8")
    assert "_latex_assets" not in scene["components"][0]["parameters"]
