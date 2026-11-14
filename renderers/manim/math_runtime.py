"""Frame-driven mathematical parts using the shared observed-speech timeline."""
from __future__ import annotations

from manim import Axes, Dot, Line, Polygon, RoundedRectangle, SurroundingRectangle, Text, VGroup, config
import numpy as np

try:
    from vibe_math_animation import evaluate_math_timeline, tangent_slope
    from vibe_render_base import math_function, validate_component
    from vibe_manim_runtime import formula, mixed_text
    from vibe_typography import chinese_font_ranges
except ImportError:
    from harness.math_animation import evaluate_math_timeline, tangent_slope
    from renderers.base import math_function, validate_component
    from renderers.manim.runtime import formula, mixed_text
    from renderers.manim.typography import chinese_font_ranges


def _fit(mob, width, height):
    factor = min(1, width / max(.001, mob.width), height / max(.001, mob.height))
    return mob.scale(factor)


def _opacity(mob, amount):
    # Preserve transparent graph fills and translucent regions while fading.
    for item in mob.family_members_with_points():
        item.set_fill(opacity=item.get_fill_opacity()*amount)
        item.set_stroke(opacity=item.get_stroke_opacity()*amount)
    return mob


def _partial(mob, amount):
    if amount <= 0:
        return mob.set_opacity(0)
    if amount >= 1:
        return mob
    leaves = mob.family_members_with_points()
    for index, item in enumerate(leaves):
        local = min(1.0, max(0.0, amount * len(leaves) - index))
        original = item.copy()
        if local <= 0:
            item.set_opacity(0)
        else:
            item.pointwise_become_partial(original, 0, local)
    return mob


def _component_parts(component, fonts, cyan, gold, white):
    """Return static parts, a pure numeric-state builder, and a stable fit envelope."""
    kind, params = component["id"], component.get("parameters", {})
    validate_component(kind, params)
    static, dynamic = {}, lambda values: {}
    if kind in {"math.derivative_secant", "math.integral_riemann"}:
        fn = math_function(params.get("function", "x**2"))
        xmin, xmax = map(float, params.get("x_range", [-1, 3] if "derivative" in kind else [0, 2]))
        samples = [fn(xmin + (xmax-xmin)*i/100) for i in range(101)]
        ymin, ymax = min(0, min(samples)), max(samples)
        span = max(1, ymax-ymin)
        ymax += span * .15
        axes = Axes(x_range=[xmin, xmax, (xmax-xmin)/4], y_range=[ymin, ymax, span/4],
                    x_length=9, y_length=3.4, tips=False,
                    axis_config={"color": "#6C8390", "stroke_opacity": .55}).shift(np.array([0, .35, 0]))
        graph = axes.plot(fn, x_range=[xmin, xmax], color=cyan)
        static.update(axes=axes, curve=graph)
        if kind == "math.derivative_secant":
            x0 = float(params.get("x0", 1))
            static["point_a"] = Dot(axes.c2p(x0, fn(x0)), color=gold)
            dx_tex, slope_tex = formula(params, "dx", color=gold, height=.3), formula(params, "slope", color=gold, height=.47)
            tangent_tex = formula(params,"tangent",color=gold,height=.4)
            exact = tangent_slope(params.get("function","x**2"),x0)
            tangent_left, tangent_right = xmin, xmax
            if abs(exact) > 1e-10:
                low, high = sorted([x0+(ymin-fn(x0))/exact,x0+(ymax-fn(x0))/exact])
                tangent_left, tangent_right = max(xmin,low),min(xmax,high)
            static["tangent"] = Line(axes.c2p(tangent_left,fn(x0)+exact*(tangent_left-x0)),
                                     axes.c2p(tangent_right,fn(x0)+exact*(tangent_right-x0)),color=gold,stroke_width=5)
            number_templates = {}
            def number_text(value, font_size=27):
                key = value,font_size
                if key not in number_templates:
                    number_templates[key] = Text(value,font=fonts["english"],font_size=font_size,color=gold)
                    if len(number_templates)>512:
                        number_templates.pop(next(iter(number_templates)))
                return number_templates[key].copy()
            def derivative(values):
                wanted = set(values.get("visible_parts",["point_b","secant","delta","formula"]))
                if not wanted.intersection({"point_b","secant","delta","formula"}):
                    return {}
                dx = max(1e-7, values.get("dx", float(params.get("dx_start", 1.5))))
                y0, y1 = fn(x0), fn(x0+dx)
                gradient = (y1-y0)/dx
                left, right = max(xmin, x0-(xmax-xmin)*.25), min(xmax, x0+max(dx, (xmax-xmin)*.25))
                if abs(gradient) > 1e-10:
                    low, high = sorted([x0+(ymin-y0)/gradient, x0+(ymax-y0)/gradient])
                    left, right = max(left, low), min(right, high)
                parts = {}
                if "point_b" in wanted:
                    parts["point_b"] = Dot(axes.c2p(x0+dx,y1),color=gold)
                if "secant" in wanted:
                    parts["secant"] = Line(axes.c2p(left,y0+gradient*(left-x0)),axes.c2p(right,y0+gradient*(right-x0)),color=gold)
                if "delta" in wanted:
                    parts["delta"] = VGroup(Line(axes.c2p(x0,y0),axes.c2p(x0+dx,y0),color=white),
                                            Line(axes.c2p(x0+dx,y0),axes.c2p(x0+dx,y1),color=white))
                if "formula" in wanted:
                    if values.get("tangent_active"):
                        label = VGroup(tangent_tex.copy(),number_text(f"{exact:.3f}",29)).arrange(buff=.2)
                    else:
                        label = VGroup(dx_tex.copy(),number_text(f"{dx:.2f}"),slope_tex.copy(),number_text(f"{gradient:.3f}")).arrange(buff=.2)
                    parts["formula"] = _fit(label,9,.6).move_to(np.array([0,-1.95,0]))
                return parts
            dynamic = derivative
        else:
            a, b = map(float, params.get("bounds", [max(0, xmin), xmax]))
            static["bounds"] = VGroup(Line(axes.c2p(a, 0), axes.c2p(a, fn(a)), color=gold),
                                      Line(axes.c2p(b, 0), axes.c2p(b, fn(b)), color=gold))
            static["formula"] = _fit(formula(params, "integral", color=gold, height=.62), 9, .68).move_to(np.array([0,-1.95,0]))
            def integral(values):
                if "visible_parts" in values and "rectangles" not in values["visible_parts"]:
                    return {}
                n = min(120, max(1, round(values.get("n", params.get("n_start", 4)))))
                return {"rectangles": axes.get_riemann_rectangles(graph, x_range=[a,b], dx=(b-a)/n,
                         input_sample_type="center", color=cyan, fill_opacity=.45, stroke_width=.6)}
            dynamic = integral
    elif kind == "math.pythagorean":
        a, b = float(params.get("a", 3)), float(params.get("b", 4))
        def point(x,y):
            return np.array([x,y,0])
        triangle = Polygon(point(0,0),point(b,0),point(0,a),color=cyan,fill_opacity=.15)
        squares = [Polygon(point(0,0),point(0,a),point(-a,a),point(-a,0),color=cyan,fill_opacity=.25),
                   Polygon(point(0,0),point(b,0),point(b,-b),point(0,-b),color="#8CCF90",fill_opacity=.25),
                   Polygon(point(b,0),point(0,a),point(a,a+b),point(a+b,b),color=gold,fill_opacity=.25)]
        VGroup(triangle,*squares).scale_to_fit_height(4).move_to(np.array([-2.7,0,0]))
        static["triangle"] = triangle
        for key, square in zip("abc", squares):
            static[f"square_{key}"] = square
            static[f"label_{key}"] = formula(params,key,height=.27).move_to(square.get_center())
        for key, tex, y in [("equation_a","area_a",1.1),("equation_b","area_b",0),("result","total",-1.1)]:
            static[key] = _fit(formula(params,tex,color=gold,height=.48),4.7,.65).move_to(np.array([2.9,y,0]))
    else:
        static["formula"] = formula(params,"main",color=cyan,height=.8,max_width=10.5).move_to(np.array([0,.6,0]))
        for index, _step in enumerate(params.get("steps", [])):
            # Steps replace one another through visible_parts; no automatic stack.
            static[f"step_{index+1}"] = formula(params,f"step_{index+1}",color=gold,height=.8,max_width=10.5).move_to(np.array([0,-.65,0]))
        for index, label in enumerate(params.get("labels", [])):
            static[f"label_{index+1}"] = _fit(mixed_text(label,fonts,font_size=28,color=white),10.5,.65).move_to(np.array([0,-1.7,0]))
    envelope = VGroup(*[part.copy() for part in static.values()], *dynamic({}).values())
    return static, dynamic, envelope


def construct_math_scene(stage, scene, metadata, fonts):
    timeline = scene.get("extensions", {}).get("math_timeline")
    if not timeline:
        raise ValueError("Mathematical animation requires the compiled observed-speech timeline")
    if isinstance(fonts, str):
        fonts = {"chinese": fonts,"english":"Times New Roman","subtitle":"Microsoft YaHei"}
    style = scene.get("extensions", {}).get("visual_style", {})
    cyan, gold, white = style.get("primary", "#63D8CE"),style.get("accent", "#F7C96B"),style.get("text", "#E9EFF7")
    stage.camera.background_color = style.get("background", "#0D1424")
    width, height = float(config.frame_width), float(config.frame_height)
    static, dynamic, envelope = _component_parts(scene["components"][0],fonts,cyan,gold,white)
    origin = envelope.get_center()
    # Reserve additional margin for the explicit 14% emphasis enlargement.
    factor = min(width*.84/max(.001,envelope.width),height*.54/max(.001,envelope.height)) / 1.16
    destination = np.array([0,height*.05,0])
    started = float(stage.time)
    if str(scene.get("title", "")).strip():
        title = _fit(mixed_text(scene["title"],fonts,font_size=30,color=white),width*.86,height*.07)
        title.move_to(np.array([0,height*.405,0]))
        stage.add(title)
    content = VGroup()
    def update_content(mob, dt):
        state = evaluate_math_timeline(timeline,float(stage.time)-started)
        parts = {**static, **dynamic({**state["values"], "tangent_active": "tangent" in state["parts"],
                                     "visible_parts": list(state["parts"])})}
        visible = VGroup()
        emphasis = state["emphasis"]
        target = None
        for identity, presentation in state["parts"].items():
            item = parts[identity].copy().shift(-origin).scale(factor,about_point=np.zeros(3)).shift(destination)
            opacity = presentation["opacity"]
            if emphasis and identity != emphasis["target"] and emphasis["kind"] == "focus":
                opacity *= 1-.65*emphasis["strength"]
            _opacity(item,opacity)
            _partial(item,presentation["draw"])
            if emphasis and identity == emphasis["target"]:
                if emphasis["kind"] in {"pulse","focus"}:
                    item.scale(emphasis["scale"])
                target = item
            visible.add(item)
        if target is not None and target.width > .01 and target.height > .01:
            visible.add(_opacity(SurroundingRectangle(target,color=gold,buff=.1,stroke_width=3+4*emphasis["strength"]),
                                 emphasis["strength"]))
        mob.become(visible)
    content.add_updater(update_content)
    update_content(content,0)
    stage.add(content)
    captions, cache = VGroup(), {}
    def update_caption(mob, dt):
        text = evaluate_math_timeline(timeline,float(stage.time)-started)["caption"]
        if text not in cache:
            if not text:
                cache[text] = VGroup()
            else:
                label = Text(text,font=fonts["english"],t2f=chinese_font_ranges(text,fonts["subtitle"]),
                             weight=fonts.get("subtitle_weight","BOLD"),font_size=34,color=fonts.get("subtitle_color","#FFFFFF"))
                _fit(label,width*.85,height*.10)
                label.set_stroke(fonts.get("outline_color","#161044"),width=float(fonts.get("outline_width",5)),background=True)
                background = RoundedRectangle(width=min(width*.88,label.width+.35),height=label.height+.16,
                                              corner_radius=.07,stroke_width=0,fill_color="#000000",fill_opacity=.18)
                cache[text] = VGroup(background,label).move_to(np.array([0,-height*.39,0])).set_z_index(100)
        mob.become(cache[text].copy())
    captions.add_updater(update_caption)
    update_caption(captions,0)
    stage.add(captions)
    stage.wait(float(scene["duration"]),frozen_frame=False)
