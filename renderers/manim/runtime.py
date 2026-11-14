"""Trusted Manim component implementations. Also copied next to generated scripts."""

from __future__ import annotations

from pathlib import Path

from manim import (
    Axes,
    Create,
    Dot,
    DOWN,
    FadeIn,
    GREEN,
    LEFT,
    Line,
    Polygon,
    RIGHT,
    RoundedRectangle,
    SVGMobject,
    Text,
    Transform,
    UP,
    ValueTracker,
    VGroup,
    WHITE,
    Write,
    always_redraw,
    smooth,
)

try:
    from vibe_render_base import math_function, validate_component
except ImportError:
    from renderers.base import math_function, validate_component

try:
    from vibe_typography import body_lines, caption_index, caption_pages, chinese_font_ranges
except ImportError:
    from renderers.manim.typography import body_lines, caption_index, caption_pages, chinese_font_ranges


def mixed_text(text, fonts, *, font_size=32, color=WHITE):
    return Text(str(text), font=fonts["english"], t2f=chinese_font_ranges(str(text), fonts["chinese"]),
                font_size=font_size, color=color)


def formula(params, key, *, color=WHITE, height=0.5, max_width=11.8):
    assets = params.get("_latex_assets", {})
    if key not in assets:
        raise ValueError(f"Missing compiled LaTeX asset: {key}. Regenerate the scene with its adapter.")
    path = Path(__file__).parent / assets[key]
    result = SVGMobject(str(path), should_center=True).set_color(color)
    result.set_height(height)
    if result.width > max_width:
        result.scale_to_fit_width(max_width)
    return result


def caption(text, fonts):
    result = Text(text, font=fonts["english"], t2f=chinese_font_ranges(text, fonts["subtitle"]),
                  weight=fonts.get("subtitle_weight", "BOLD"), font_size=32,
                  color=fonts.get("subtitle_color", "#FFFFFF"), line_spacing=0.7)
    if result.width > 12.7:
        result.scale_to_fit_width(12.7)
    result.set_stroke(fonts.get("outline_color", "#161044"),
                      width=float(fonts.get("outline_width", 5)), background=True)
    return result.to_edge(DOWN, buff=0.25).set_z_index(100)


def construct_scene(stage, scene, metadata, fonts):
    if scene.get("extensions", {}).get("math_animation_version") == "1.0":
        try:
            from vibe_math_runtime import construct_math_scene
        except ImportError:
            from renderers.manim.math_runtime import construct_math_scene
        return construct_math_scene(stage, scene, metadata, fonts)
    if isinstance(fonts, str):
        fonts = {"chinese": fonts, "english": "Times New Roman", "subtitle": "Microsoft YaHei"}
    components = scene.get("components") or [{"id": "general.title", "parameters": {}}]
    if len(components) > 1:
        narration_start = float(stage.time) + float(scene.get("audio", {}).get("narration_offset", 0))
        for component in components:
            stage.clear()
            part = {
                **scene,
                "components": [component],
                "duration": float(scene.get("duration", 10)) / len(components),
                "_narration_start": narration_start,
                "_narration_duration": float(scene.get("audio", {}).get("narration_duration", scene.get("duration", 10))),
            }
            construct_scene(stage, part, metadata, fonts)
        return
    time_start = float(stage.time)
    narration_start = scene.get("_narration_start", time_start + float(scene.get("audio", {}).get("narration_offset", 0)))
    style = scene.get("extensions", {}).get("visual_style", {})
    stage.camera.background_color = style.get("background", "#101820")
    duration = float(scene.get("duration", 10))
    cyan, gold = style.get("primary", "#65D8DF"), style.get("accent", "#F3C66B")
    text_color = style.get("text", WHITE)
    narration = str(scene.get("narration", ""))
    if narration:
        chunks = caption_pages(narration)
        narration_duration = max(.01, float(scene.get("_narration_duration",
            scene.get("audio", {}).get("narration_duration", duration))))

        def make_caption(index):
            return caption(chunks[index], fonts)

        initial_index = caption_index(chunks, (time_start-narration_start)
                                      /narration_duration)
        caption_mob = make_caption(initial_index)
        caption_mob.current_index = initial_index
        caption_mob.set_opacity(1 if narration_start <= float(stage.time) < narration_start + narration_duration else 0)

        def update_caption(mob, dt):
            # The dt parameter marks this as time-based for Manim. Without it,
            # Wait freezes the frame and leaves old captions through the cut.
            progress = (float(stage.time) - narration_start) / narration_duration
            index = caption_index(chunks, progress)
            if index != mob.current_index:
                mob.become(make_caption(index))
                mob.current_index = index
            # Caption timing follows the voice, including the silent transition
            # handles. Adjacent captions cannot ghost over each other in a dissolve.
            mob.set_opacity(1 if narration_start <= float(stage.time) < narration_start + narration_duration else 0)

        caption_mob.add_updater(update_caption)
        stage.add(caption_mob)
    title = mixed_text(
        scene.get("title") or scene.get("learning_goal") or "知识探索",
        fonts,
        font_size=36,
        color=text_color,
    )
    if title.width > 12:
        title.scale_to_fit_width(12)
    title.to_edge(UP, buff=0.35)
    stage.add(title)
    components = scene.get("components") or [{"id": "general.title", "parameters": {}}]
    component = components[0]
    kind, params = component.get("id", "general.title"), component.get("parameters", {})
    validate_component(kind, params)
    if kind in {"math.derivative_secant", "math.integral_riemann"}:
        fn = math_function(params.get("function", "x**2"))
        xmin, xmax = map(float, params.get("x_range", [-1, 3] if "derivative" in kind else [0, 2]))
        values = [fn(xmin + (xmax - xmin) * i / 100) for i in range(101)]
        ymin, ymax = min(0, min(values)), max(values)
        span = max(1, ymax - ymin)
        axes = Axes(
            x_range=[xmin, xmax, (xmax - xmin) / 4],
            y_range=[ymin, ymax + span * 0.15, span / 4],
            x_length=9,
            y_length=3.7,
            tips=False,
            axis_config={"color": "#6C8390", "stroke_opacity": 0.5},
        ).shift(UP * 0.15)
        graph = axes.plot(fn, x_range=[xmin, xmax], color=cyan)
        stage.add(axes, graph)
        if kind == "math.derivative_secant":
            x0 = float(params.get("x0", 1))
            start, end = float(params.get("dx_start", 1.5)), float(params.get("dx_end", 0.02))
            dx = ValueTracker(start)

            def slope():
                return (fn(x0 + dx.get_value()) - fn(x0)) / max(1e-7, dx.get_value())

            point_a = Dot(axes.c2p(x0, fn(x0)), color=gold)
            point_b = always_redraw(
                lambda: Dot(axes.c2p(x0 + dx.get_value(), fn(x0 + dx.get_value())), color=gold)
            )

            def clipped_secant():
                gradient, anchor_y = slope(), fn(x0)
                margin = (xmax - xmin) * 0.25
                left = max(xmin, x0 - margin)
                right = min(xmax, x0 + max(margin, dx.get_value()))
                # Intersect the line with the visible axes rectangle so it cannot
                # extend into the slope annotation or narration underneath it.
                if abs(gradient) > 1e-10:
                    y_intersections = sorted(
                        [x0 + (ymin - anchor_y) / gradient, x0 + (ymax + span * 0.15 - anchor_y) / gradient]
                    )
                    left = max(left, y_intersections[0])
                    right = min(right, y_intersections[1])
                return Line(
                    axes.c2p(left, anchor_y + gradient * (left - x0)),
                    axes.c2p(right, anchor_y + gradient * (right - x0)),
                    color=gold,
                )

            secant = always_redraw(clipped_secant)
            dx_label = formula(params, "dx", color=gold, height=.31)
            slope_label = formula(params, "slope", color=gold, height=.58)

            def numeric_label():
                # Math symbols and fraction are compiled LaTeX; only changing digits use Times.
                return VGroup(dx_label.copy(), Text(f"{dx.get_value():.2f}", font=fonts["english"], font_size=29, color=gold),
                              slope_label.copy(), Text(f"{slope():.3f}", font=fonts["english"], font_size=29, color=gold)
                              ).arrange(RIGHT, buff=.25).move_to(DOWN * 2.55)

            label = always_redraw(numeric_label)
            stage.add(point_a, point_b, secant, label)
            stage.play(dx.animate.set_value(end), run_time=duration * 0.98, rate_func=smooth)
        else:
            a, b = map(float, params.get("bounds", [max(0, xmin), xmax]))
            n0, n1 = int(params.get("n_start", 4)), int(params.get("n_end", 32))
            n0, n1 = max(1, n0), min(120, max(1, n1))
            rectangles = axes.get_riemann_rectangles(
                graph,
                x_range=[a, b],
                dx=(b - a) / n0,
                input_sample_type="center",
                color=cyan,
                fill_opacity=0.45,
                stroke_width=0.6,
            )
            reveal_duration = min(.6, duration * .08)
            stage.play(FadeIn(rectangles), run_time=reveal_duration)
            integral = formula(params, "integral", color=gold, height=.65).move_to(DOWN * 2.55)
            stage.add(integral)
            steps = sorted(set([n0, min(n1, n0 * 2), min(n1, n0 * 4), n1]))
            for count in steps[1:]:
                next_rects = axes.get_riemann_rectangles(
                    graph,
                    x_range=[a, b],
                    dx=(b - a) / count,
                    input_sample_type="center",
                    color=cyan,
                    fill_opacity=0.45,
                    stroke_width=0.6,
                )
                stage.play(
                    Transform(rectangles, next_rects), run_time=(duration * .98 - reveal_duration) / max(1, len(steps) - 1)
                )
    elif kind == "math.pythagorean":
        a, b = float(params.get("a", 3)), float(params.get("b", 4))

        def point(x, y):
            return RIGHT * x + UP * y

        triangle = Polygon(point(0, 0), point(b, 0), point(0, a), color=cyan, fill_opacity=0.2)
        squares = VGroup(
            Polygon(point(0, 0), point(0, a), point(-a, a), point(-a, 0), color=cyan, fill_opacity=0.3),
            Polygon(point(0, 0), point(b, 0), point(b, -b), point(0, -b), color=GREEN, fill_opacity=0.3),
            Polygon(point(b, 0), point(0, a), point(a, a + b), point(a + b, b), color=gold, fill_opacity=0.3),
        )
        VGroup(triangle, squares).scale_to_fit_height(4.3).move_to(LEFT * 3 + DOWN * 0.2)
        labels = VGroup(
            *[
                formula(params, key, color=WHITE, height=.28).move_to(square.get_center())
                for key, square in zip(["a", "b", "c"], squares)
            ]
        )
        stage.play(Create(triangle), run_time=duration * 0.12)
        for square, label in zip(squares, labels):
            stage.play(FadeIn(square), FadeIn(label), run_time=duration * 0.08)
        equations = (
            VGroup(
                *[
                    formula(params, key, color=gold, height=.45)
                    for key in ["area_a", "area_b", "total"]
                ]
            )
            .arrange(DOWN, buff=0.55)
            .shift(RIGHT * 3)
        )
        if equations.width > 5.5:
            equations.scale_to_fit_width(5.5)
        for equation in equations:
            stage.play(Write(equation), run_time=duration * 0.12)
    elif kind == "math.formula" or params.get("latex") or params.get("formula"):
        content = formula(params, "main", color=cyan, height=1.15).move_to(UP * .35)
        stage.play(Write(content), run_time=min(1.2, duration * .4))
        labels = params.get("labels", [])
        if labels:
            notes = VGroup(*[mixed_text(label, fonts, font_size=27, color=text_color) for label in labels])
            notes.arrange(DOWN, buff=.3).next_to(content, DOWN, buff=.65)
            if notes.width > 11.8:
                notes.scale_to_fit_width(11.8)
            stage.play(FadeIn(notes), run_time=min(.5, duration * .12))
    elif params.get("labels"):
        # Labels are audience content; visual_concept is a production instruction.
        # Show the Agent's concepts as cards without inventing unprovided edges.
        cards = VGroup()
        for label in params["labels"][:12]:
            text = mixed_text("\n".join(body_lines(str(label), max_units=12)), fonts, font_size=28, color=cyan)
            if text.width > 4.6:
                text.scale_to_fit_width(4.6)
            box = RoundedRectangle(width=5.1, height=max(.7, text.height+.28), corner_radius=.12,
                                   color=cyan, stroke_width=1.2, fill_color="#182633", fill_opacity=.9)
            cards.add(VGroup(box, text))
        cards.arrange_in_grid(cols=2, buff=(.4, .24))
        if cards.height > 4.8:
            cards.scale_to_fit_height(4.8)
        cards.move_to(UP * .05)
        stage.play(FadeIn(cards), run_time=min(.5, duration * .1))
    else:
        text = str(
            params.get("formula")
            or params.get("title")
            or scene.get("title", "")
        )
        lines = body_lines(text)[:5]
        content = VGroup(*[mixed_text(line, fonts, font_size=32, color=cyan) for line in lines]).arrange(
            DOWN, buff=0.4
        )
        if content.width > 11:
            content.scale_to_fit_width(11)
        stage.play(Write(content), run_time=min(.8, duration * .2))
    remaining = duration - (float(stage.time) - time_start)
    if remaining > 0:
        stage.wait(remaining)
