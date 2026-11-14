"""A deterministic CPU renderer for reusable 2D diagrams, including offline previews."""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .base import RendererError, math_function, require_output, scene_filename, setting, validate_component
from .ffmpeg import FFmpeg


def font_path(configured=None, role="chinese") -> str:
    defaults = {
        "chinese": ["C:/Windows/Fonts/simsun.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"],
        "english": ["C:/Windows/Fonts/times.ttf", "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"],
        "subtitle": ["C:/Windows/Fonts/msyhbd.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
    }
    candidates = [
        configured,
        os.environ.get("VIBE_FONT_PATH"),
        *defaults[role],
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for item in candidates:
        if item and Path(item).is_file():
            return str(item)
    raise RendererError(f"No {role} font found. Configure its font file path.")


class MixedScriptDraw:
    """Use the requested Chinese font and Times New Roman on a common baseline."""

    def __init__(self, image, english_path):
        self.draw = ImageDraw.Draw(image)
        self.english_path = english_path
        self._fonts = {}

    def __getattr__(self, name):
        return getattr(self.draw, name)

    def font_for(self, char, font):
        if ord(char) < 128:
            if font.size not in self._fonts:
                self._fonts[font.size] = ImageFont.truetype(self.english_path, font.size)
            return self._fonts[font.size]
        return font

    def runs(self, text, font):
        runs = []
        for char in str(text):
            selected = self.font_for(char, font)
            if runs and runs[-1][1] is selected:
                runs[-1] = (runs[-1][0] + char, selected)
            else:
                runs.append((char, selected))
        return runs

    def textlength(self, text, font, **kwargs):
        return sum(self.draw.textlength(run, font=selected, **kwargs) for run, selected in self.runs(text, font))

    def text(self, xy, text, font, **kwargs):
        x, y = xy
        baseline = y + font.getmetrics()[0]
        for run, selected in self.runs(text, font):
            self.draw.text((x, baseline), run, font=selected, anchor="ls", **kwargs)
            x += self.draw.textlength(run, font=selected)


def wrapped(text: str, font, width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines, line = [], ""
    for char in str(text):
        if char == "\n" or (line and draw.textlength(line + char, font=font) > width):
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    if line:
        lines.append(line)
    return lines


def ease(progress):
    t = min(1.0, max(0.0, progress))
    return t * t * (3 - 2 * t)


class CanvasRenderer:
    def __init__(self, settings=None):
        self.settings = settings
        self._font = font_path(setting(settings, "font_path"))
        self._english_font = font_path(setting(settings, "english_font_path"), "english")
        self._subtitle_font = font_path(setting(settings, "subtitle_font_path"), "subtitle")
        self._latex_cache = Path(setting(settings, "latex_cache_dir", "") or "outputs/.latex-cache")
        self._formula_images = {}

    def formula_image(self, expression, height, color, max_width=None):
        """Compile a static LaTeX fragment once, then recolor and resize its alpha mask."""
        from .latex import render_latex_png

        key = (expression, round(height), color, round(max_width) if max_width else None)
        if key not in self._formula_images:
            path = render_latex_png(expression, self._latex_cache, self.settings, scale=3)
            with Image.open(path) as raw:
                alpha = raw.convert("RGBA").getchannel("A")
                bounds = alpha.getbbox()
                if bounds is None:
                    raise RendererError("LaTeX produced an empty formula")
                alpha = alpha.crop(bounds)
                colored = Image.new("RGBA", alpha.size, color)
                colored.putalpha(alpha)
                factor = min(height / colored.height, max_width / colored.width if max_width else float("inf"))
                result = colored.resize((max(1, round(colored.width * factor)), max(1, round(colored.height * factor))), Image.Resampling.LANCZOS)
                self._formula_images[key] = result
        return self._formula_images[key]

    def paste_formula(self, image, expression, xy, height, color, max_width=None, centered=False):
        formula = self.formula_image(expression, height, color, max_width)
        x, y = xy
        if centered:
            x -= formula.width / 2
            y -= formula.height / 2
        image.paste(formula, (round(x), round(y)), formula)
        return formula.width

    def formula_row(self, image, draw, items, xy, font, color, height, max_width):
        """Static LaTeX identifiers with dynamic numerical values, no per-frame TeX compiler."""
        fragments = [(self.formula_image(value, height * (1.8 if any(command in value for command in (r"\frac", r"\sum", r"\int")) else 1), color)
                      if kind == "latex" else value) for kind, value in items]
        gap = max(5, font.size * .4)
        widths = [item.width if isinstance(item, Image.Image) else draw.textlength(item, font=font) for item in fragments]
        total = sum(widths) + gap * (len(widths) - 1)
        row_height = max(font.size * 1.3, *(item.height for item in fragments if isinstance(item, Image.Image))) + 6
        row = Image.new("RGBA", (max(1, round(total + 2)), max(1, round(row_height))), (0, 0, 0, 0))
        row_draw = MixedScriptDraw(row, self._english_font)
        x = 0
        for fragment, width in zip(fragments, widths):
            if isinstance(fragment, Image.Image):
                row.alpha_composite(fragment, (round(x), round((row.height - fragment.height) / 2)))
            else:
                row_draw.text((x, (row.height - font.size * 1.2) / 2), fragment, font=font, fill=color)
            x += width + gap
        if row.width > max_width:
            row = row.resize((round(max_width), max(1, round(row.height * max_width / row.width))), Image.Resampling.LANCZOS)
        image.paste(row, (round(xy[0]), round(xy[1])), row)

    def generate(self, scene: dict, metadata: dict, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{scene_filename(scene)}.canvas.json"
        path.write_text(
            json.dumps(
                {"renderer": "canvas", "scene": scene, "metadata": metadata}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        return path

    def frame(self, scene: dict, metadata: dict, progress: float) -> Image.Image:
        if scene.get("extensions", {}).get("math_animation_version") == "1.0":
            return self.math_frame(scene, metadata, progress * float(scene["duration"]))
        width, height = int(metadata.get("width", 1280)), int(metadata.get("height", 720))
        style = scene.get("extensions", {}).get("visual_style", {})
        image = Image.new("RGB", (width, height), style.get("background", "#101820"))
        draw = MixedScriptDraw(image, self._english_font)
        scale = width / 1280
        title_font = ImageFont.truetype(self._font, max(12, int(38 * scale)))
        label_font = ImageFont.truetype(self._font, max(10, int(25 * scale)))
        small_font = ImageFont.truetype(self._font, max(9, int(21 * scale)))
        caption_font = ImageFont.truetype(self._subtitle_font, max(14, int(34 * scale)))
        pad = int(width * 0.065)
        accent, secondary, muted, white = (
            style.get("primary", "#65D8DF"),
            style.get("accent", "#F3C66B"),
            "#6C8390",
            style.get("text", "#EDF5F6"),
        )
        title = scene.get("title") or scene.get("learning_goal") or "知识探索"
        for i, line in enumerate(wrapped(title, title_font, width - 2 * pad, draw)[:2]):
            draw.text((pad, height * 0.055 + i * title_font.size * 1.2), line, font=title_font, fill=white)
        draw.line((pad, height * 0.19, width - pad, height * 0.19), fill="#2C414C", width=max(1, int(scale)))
        left, right, top, bottom = width * 0.16, width * 0.88, height * 0.29, height * 0.72
        components = scene.get("components") or [{"id": "general.title", "parameters": {}}]
        overall_progress = progress
        phase = min(len(components) - 1, int(progress * len(components)))
        component = components[phase]
        progress = min(1, progress * len(components) - phase)
        kind, params = component.get("id", "general.title"), component.get("parameters", {})
        if kind == "general.composed_chart":
            kind = "general.chart"
        if kind not in {
            "math.derivative_secant",
            "math.integral_riemann",
            "math.pythagorean",
            "math.formula",
            "general.title",
            "general.timeline",
            "general.chart",
            "general.process",
            "general.relationship",
        }:
            kind = (
                "general.chart"
                if params.get("values")
                else "general.process"
                if params.get("labels")
                else "general.title"
            )
        validate_component(kind, params)
        t = ease(progress / 0.85)
        if kind in {"math.derivative_secant", "math.integral_riemann"}:
            fn = math_function(params.get("function", "x**2"))
            xmin, xmax = map(float, params.get("x_range", [-1, 3] if "derivative" in kind else [0, 2]))
            if xmax <= xmin:
                raise RendererError("x_range must be strictly increasing")
            samples = [xmin + (xmax - xmin) * i / 180 for i in range(181)]
            ys = [fn(x) for x in samples]
            ymin, ymax = min(0, min(ys)), max(ys)
            span = max(1, ymax - ymin)
            ymin, ymax = ymin - span * 0.08, ymax + span * 0.15

            def xy(x, y):
                return (
                    left + (x - xmin) / (xmax - xmin) * (right - left),
                    bottom - (y - ymin) / (ymax - ymin) * (bottom - top),
                )

            zero_y, zero_x = xy(xmin, 0)[1], xy(max(xmin, min(0, xmax)), 0)[0]
            draw.line((left, zero_y, right, zero_y), fill=muted, width=max(1, int(2 * scale)))
            draw.line((zero_x, top, zero_x, bottom), fill=muted, width=max(1, int(2 * scale)))
            for index in range(5):
                x = xmin + (xmax - xmin) * index / 4
                px, py = xy(x, 0)
                draw.text((px - 10 * scale, py + 8 * scale), f"{x:g}", font=small_font, fill=muted)
            if kind == "math.integral_riemann":
                a, b = map(float, params.get("bounds", [max(0, xmin), xmax]))
                count = int(
                    params.get("n_start", 4) + t * (params.get("n_end", 32) - params.get("n_start", 4))
                )
                count = min(120, max(1, count))
                dx = (b - a) / count
                for index in range(count):
                    x, y = a + index * dx, fn(a + (index + 0.5) * dx)
                    p1, p2 = xy(x, 0), xy(x + dx, y)
                    draw.rectangle(
                        (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])),
                        fill="#24565D",
                        outline=accent,
                    )
                estimate = sum(fn(a + (i + 0.5) * dx) * dx for i in range(count))
                label = [("latex", "n="), ("number", str(count)),
                         ("latex", r"\sum_{i=1}^{n}f(x_i)\Delta x\approx"), ("number", f"{estimate:.3f}")]
            else:
                x0 = float(params.get("x0", 1))
                dx = float(params.get("dx_start", 1.5)) * (1 - t) + float(params.get("dx_end", 0.02)) * t
                if abs(dx) < 1e-7:
                    dx = 1e-7
                slope = (fn(x0 + dx) - fn(x0)) / dx
                p1, p2 = xy(x0, fn(x0)), xy(x0 + dx, fn(x0 + dx))
                # Bound line extent to the plotting rectangle to avoid covering captions.
                extent = (xmax - xmin) * .3
                line_xs = [max(xmin, x0 - extent), min(xmax, x0 + max(extent, dx))]
                if abs(slope) > 1e-10:
                    crossing = sorted([x0 + (ymin - fn(x0)) / slope, x0 + (ymax - fn(x0)) / slope])
                    line_xs = [max(line_xs[0], crossing[0]), min(line_xs[1], crossing[1])]
                line_pts = [xy(x, fn(x0) + slope * (x - x0)) for x in line_xs]
                draw.line(line_pts, fill=secondary, width=max(2, int(3 * scale)))
                draw.line((p1[0], p1[1], p2[0], p1[1]), fill=muted, width=max(1, int(2 * scale)))
                draw.line((p2[0], p1[1], p2[0], p2[1]), fill=muted, width=max(1, int(2 * scale)))
                for px, py in (p1, p2):
                    draw.ellipse(
                        (px - 6 * scale, py - 6 * scale, px + 6 * scale, py + 6 * scale), fill=secondary
                    )
                label = [("latex", r"\Delta x="), ("number", f"{dx:.2f}"),
                         ("latex", r"\frac{\Delta y}{\Delta x}="), ("number", f"{slope:.3f}")]
            visible = max(2, int(len(samples) * min(1, progress / 0.25)))
            draw.line([xy(x, fn(x)) for x in samples[:visible]], fill=accent, width=max(2, int(4 * scale)))
            self.formula_row(image, draw, label, (left, height * 0.205), label_font, secondary,
                             max(12, 28 * scale), right - left)
        elif kind == "math.pythagorean":
            a, b = float(params.get("a", 3)), float(params.get("b", 4))
            if a <= 0 or b <= 0:
                raise RendererError("Pythagorean legs must be positive")
            c = math.hypot(a, b)
            unit = min(width * 0.42 / (2 * a + b), (bottom - top) / (a + 2 * b))
            x, y = left + a * unit, bottom - b * unit

            def point(px, py):
                return (x + px * unit, y - py * unit)

            vertices = [point(0, 0), point(b, 0), point(0, a), point(0, 0)]
            squares = [
                ([(0, 0), (0, a), (-a, a), (-a, 0)], "#28545B", f"a^2={a * a:g}", (-a / 2, a / 2)),
                ([(0, 0), (b, 0), (b, -b), (0, -b)], "#46533F", f"b^2={b * b:g}", (b / 2, -b / 2)),
                (
                    [(b, 0), (0, a), (a, a + b), (a + b, b)],
                    "#655536",
                    f"c^2={c * c:g}",
                    ((a + b) / 2, (a + b) / 2),
                ),
            ]
            for i, (corners, color, label, center) in enumerate(squares):
                if progress >= i * 0.18:
                    draw.polygon(
                        [point(*corner) for corner in corners],
                        fill=color,
                        outline=secondary if i == 2 else accent,
                    )
                    px, py = point(*center)
                    self.paste_formula(image, label, (px, py), max(10, 20 * scale), white, width * .16, centered=True)
            draw.polygon(vertices, fill="#183C45")
            draw.line(vertices, fill=accent, width=max(2, int(4 * scale)))
            equations = [f"a^2={a * a:g}", f"b^2={b * b:g}", f"a^2+b^2=c^2={c * c:g}"]
            for i, equation in enumerate(equations):
                if progress >= i * 0.22:
                    self.paste_formula(image, equation, (width * 0.61, top + i * height * 0.13),
                                       max(12, 32 * scale), secondary if i == 2 else white, width * .33)
        elif kind == "general.timeline":
            labels = params.get("labels") or ["起因", "关键事件", "转折", "结果"]
            labels = [str(label) for label in labels][:6]
            y = (top + bottom) / 2
            draw.line((left, y, right, y), fill=muted, width=max(2, int(3 * scale)))
            for i, label in enumerate(labels):
                x = left + (right - left) * i / max(1, len(labels) - 1)
                active = progress >= i / max(1, len(labels)) * 0.8
                draw.ellipse(
                    (x - 8 * scale, y - 8 * scale, x + 8 * scale, y + 8 * scale),
                    fill=accent if active else muted,
                )
                if active:
                    lines = wrapped(label, label_font, int((right - left) / max(2, len(labels) - 0.5)), draw)
                    for j, line in enumerate(lines[:3]):
                        draw.text(
                            (x - 40 * scale, y + 25 * scale + j * 30 * scale),
                            line,
                            font=label_font,
                            fill=white,
                        )
        elif kind == "general.chart":
            labels = params.get("labels") or ["A", "B", "C", "D"]
            values = params.get("values") or [1, 3, 2, 4]
            values = [float(v) for v in values[:8]]
            maximum = max(1, *[abs(v) for v in values])
            for i, value in enumerate(values):
                step = (right - left) / len(values)
                x = left + i * step
                bar_h = abs(value) / maximum * (bottom - top) * t
                draw.rectangle((x, bottom - bar_h, x + step * 0.62, bottom), fill=accent)
                draw.text(
                    (x, bottom + 12 * scale),
                    str(labels[i] if i < len(labels) else i + 1)[:10],
                    font=small_font,
                    fill=white,
                )
                draw.text((x, bottom - bar_h - 30 * scale), f"{value:g}", font=small_font, fill=secondary)
        elif kind in {"general.process", "general.relationship"}:
            labels = [str(label) for label in (params.get("labels") or ["观察", "机制", "结果"])][:5]
            n = len(labels)
            for i, label in enumerate(labels):
                x = left + (right - left) * (i + 0.5) / n
                y = (top + bottom) / 2 + (
                    math.sin(i * math.pi) * height * 0.08 if kind == "general.relationship" else 0
                )
                box_w = (right - left) / n * 0.82
                active = progress >= (i / max(1, n)) * 0.75
                if i and active:
                    draw.line(
                        (x - (right - left) / n + box_w / 2, y, x - box_w / 2, y),
                        fill=secondary,
                        width=max(2, int(3 * scale)),
                    )
                draw.rounded_rectangle(
                    (x - box_w / 2, y - height * 0.09, x + box_w / 2, y + height * 0.09),
                    radius=12 * scale,
                    fill="#1B3945" if active else "#17242C",
                    outline=accent if active else muted,
                    width=max(1, int(2 * scale)),
                )
                for j, line in enumerate(wrapped(label, label_font, int(box_w * 0.85), draw)[:3]):
                    tw = draw.textlength(line, font=label_font)
                    draw.text(
                        (x - tw / 2, y - height * 0.045 + j * 30 * scale),
                        line,
                        font=label_font,
                        fill=white if active else muted,
                    )
        elif kind == "math.formula":
            expression = params.get("latex") or params.get("formula")
            if not expression:
                raise RendererError("math.formula requires parameters.latex")
            self.paste_formula(image, str(expression), (width / 2, height * .45),
                               max(28, height * .16), accent, width * .80, centered=True)
            # The equation is mathematical typesetting; explanatory labels remain Chinese/English text.
            labels = [str(value) for value in params.get("labels", [])]
            y = height * .65
            for line in wrapped("   ·   ".join(labels), label_font, width * .82, draw)[:2]:
                tw = draw.textlength(line, font=label_font)
                draw.text(((width - tw) / 2, y), line, font=label_font, fill=white)
                y += label_font.size * 1.3
        else:
            text = params.get("title") or scene.get("visual_concept") or title
            lines = wrapped(str(text), title_font, int(width * 0.75), draw)
            y = height * 0.36
            for line in lines[:4]:
                tw = draw.textlength(line, font=title_font)
                draw.text(((width - tw) / 2, y), line, font=title_font, fill=accent)
                y += title_font.size * 1.6
            line_y = min(height * 0.68, y + 15 * scale)
            draw.line(
                (width * 0.25, line_y, width * 0.25 + width * 0.5 * t, line_y),
                fill=secondary,
                width=max(2, int(4 * scale)),
            )
        # Captions advance by sentence-sized chunks, leaving enough room for teaching graphics.
        narration = scene.get("narration", "")
        caption_lines = wrapped(narration, caption_font, width - 2 * pad, draw)
        chunk_count = max(1, math.ceil(len(caption_lines) / 2))
        planned_seconds = float(scene.get("duration", 10))
        spoken_seconds = float(scene.get("audio", {}).get("narration_duration", planned_seconds))
        voice_offset = float(scene.get("audio", {}).get("narration_offset", 0))
        caption_progress = max(0, min(1, (overall_progress * planned_seconds - voice_offset) / max(.01, spoken_seconds)))
        chunk = min(chunk_count - 1, int(caption_progress * chunk_count)) * 2
        if not voice_offset <= overall_progress * planned_seconds < voice_offset + spoken_seconds:
            caption_lines = []
        for i, line in enumerate(caption_lines[chunk : chunk + 2]):
            tw = draw.textlength(line, font=caption_font)
            draw.text(
                ((width - tw) / 2, height * 0.83 + i * caption_font.size * 1.3),
                line,
                font=caption_font,
                fill=setting(self.settings, "subtitle_color", "#FFFFFF"),
                stroke_fill=setting(self.settings, "subtitle_outline_color", "#161044"),
                stroke_width=max(1, round(float(setting(self.settings, "subtitle_outline_width", 5)) * scale)),
            )
        draw.rectangle((0, height - 4 * scale, width * overall_progress, height), fill=accent)
        return image

    def math_frame(self, scene, metadata, seconds):
        """Render only the parts selected by the observed-narration timeline."""
        from harness.math_animation import evaluate_math_timeline, tangent_slope

        timeline = scene.get("extensions", {}).get("math_timeline")
        if not timeline:
            raise RendererError("Mathematical animation requires observed-speech compilation")
        state = evaluate_math_timeline(timeline, seconds)
        width, height = int(metadata.get("width",1280)), int(metadata.get("height",720))
        scale = width/1280
        style = scene.get("extensions",{}).get("visual_style",{})
        background, cyan, gold, white = (style.get("background","#0D1424"),style.get("primary","#63D8CE"),
                                         style.get("accent","#F7C96B"),style.get("text","#E9EFF7"))
        image = Image.new("RGBA",(width,height),background)
        draw = MixedScriptDraw(image,self._english_font)
        title_font = ImageFont.truetype(self._font,max(12,round(32*scale)))
        label_font = ImageFont.truetype(self._font,max(12,round(28*scale)))
        subtitle_font = ImageFont.truetype(self._subtitle_font,max(14,round(38*scale)))
        title = str(scene.get("title", ""))
        while draw.textlength(title,font=title_font) > width*.86 and title_font.size > 10:
            title_font = ImageFont.truetype(self._font,title_font.size-1)
        draw.text(((width-draw.textlength(title,font=title_font))/2,height*.055),title,font=title_font,fill=white)
        component = scene["components"][0]
        kind, params = component["id"],component.get("parameters",{})
        validate_component(kind,params)
        line_width = max(2,round(3*scale))
        chart = None
        if kind in {"math.derivative_secant","math.integral_riemann"}:
            fn = math_function(params.get("function","x**2"))
            xmin,xmax = map(float,params.get("x_range",[-1,3] if "derivative" in kind else [0,2]))
            samples = [xmin+(xmax-xmin)*i/180 for i in range(181)]
            ys = [fn(x) for x in samples]
            ymin,ymax = min(0,min(ys)),max(ys)
            span = max(1,ymax-ymin)
            ymin,ymax = ymin-span*.08,ymax+span*.15
            left,right,top,bottom = width*.18,width*.82,height*.22,height*.58
            def xy(x,y):
                return left+(x-xmin)/(xmax-xmin)*(right-left),bottom-(y-ymin)/(ymax-ymin)*(bottom-top)
            chart = fn,xmin,xmax,samples,ymin,ymax,xy

        def stroke(painter, points, color, amount=1, thickness=line_width):
            if amount <= 0 or len(points)<2:
                return
            lengths = [math.dist(a,b) for a,b in zip(points,points[1:])]
            remain = sum(lengths)*min(1,amount)
            visible = [points[0]]
            for a,b,length in zip(points,points[1:],lengths):
                if remain >= length:
                    visible.append(b)
                    remain -= length
                else:
                    ratio = remain/max(length,1e-8)
                    visible.append((a[0]+(b[0]-a[0])*ratio,a[1]+(b[1]-a[1])*ratio))
                    break
            if len(visible)>1:
                painter.line(visible,fill=color,width=thickness)

        def polygon(painter, points, color, amount):
            if amount >= .98:
                painter.polygon(points,fill=color)
            stroke(painter,[*points,points[0]],gold,amount)

        def math_text(layer, expression, center, max_height, max_width, amount):
            asset = self.formula_image(expression,max_height,gold,max_width)
            if amount < 1:
                asset = asset.crop((0,0,max(1,round(asset.width*amount)),asset.height))
            # Revealing a formula keeps its complete expression's left edge fixed.
            complete = self.formula_image(expression,max_height,gold,max_width)
            layer.alpha_composite(asset,(round(center[0]-complete.width/2),round(center[1]-complete.height/2)))

        for identity,presentation in state["parts"].items():
            amount = presentation["draw"]
            if amount <= 0 or presentation["opacity"] <= 0:
                continue
            layer = Image.new("RGBA",image.size,(0,0,0,0))
            painter = ImageDraw.Draw(layer)
            if chart:
                fn,xmin,xmax,samples,ymin,ymax,xy = chart
                if identity=="axes":
                    stroke(painter,[xy(xmin,0),xy(xmax,0)],"#6C8390",min(1,amount*2))
                    zero=max(xmin,min(0,xmax))
                    stroke(painter,[xy(zero,ymin),xy(zero,ymax)],"#6C8390",max(0,amount*2-1))
                elif identity=="curve":
                    stroke(painter,[xy(x,fn(x)) for x in samples],cyan,amount,max(2,round(4*scale)))
                elif kind=="math.derivative_secant":
                    x0=float(params.get("x0",1)); dx=max(1e-7,state["values"].get("dx",params.get("dx_start",1.5)))
                    y0,y1=fn(x0),fn(x0+dx)
                    gradient=(y1-y0)/dx
                    if identity in {"point_a","point_b"}:
                        px,py=xy(x0,y0) if identity=="point_a" else xy(x0+dx,y1)
                        radius=max(2,7*scale)*amount
                        painter.ellipse((px-radius,py-radius,px+radius,py+radius),fill=gold)
                    elif identity in {"secant","tangent"}:
                        if identity=="tangent":
                            gradient=tangent_slope(params.get("function","x**2"),x0)
                        lo,hi=xmin,xmax
                        if abs(gradient)>1e-10:
                            lower,upper=sorted([x0+(ymin-y0)/gradient,x0+(ymax-y0)/gradient])
                            lo,hi=max(lo,lower),min(hi,upper)
                        stroke(painter,[xy(lo,y0+gradient*(lo-x0)),xy(hi,y0+gradient*(hi-x0))],gold,amount)
                    elif identity=="delta":
                        stroke(painter,[xy(x0,y0),xy(x0+dx,y0),xy(x0+dx,y1)],white,amount)
                    elif identity=="formula":
                        if "tangent" in state["parts"]:
                            fragments=[("latex",r"f'(x_0)="),("number",f"{tangent_slope(params.get('function','x**2'),x0):.3f}")]
                        else:
                            fragments=[("latex",r"\Delta x="),("number",f"{dx:.2f}"),("latex",r"\frac{\Delta y}{\Delta x}="),("number",f"{gradient:.3f}")]
                        self.formula_row(layer,MixedScriptDraw(layer,self._english_font),fragments,
                                         (width*.23,height*.64),label_font,gold,max(12,25*scale),width*.56)
                else:
                    a,b=map(float,params.get("bounds",[max(0,xmin),xmax]))
                    if identity=="bounds":
                        stroke(painter,[xy(a,0),xy(a,fn(a))],gold,min(1,amount*2))
                        stroke(painter,[xy(b,0),xy(b,fn(b))],gold,max(0,amount*2-1))
                    elif identity=="rectangles":
                        count=min(120,max(1,round(state["values"].get("n",params.get("n_start",4)))))
                        dx=(b-a)/count
                        for index in range(count):
                            partial=min(1,max(0,amount*count-index))
                            if partial<=0:
                                continue
                            x=a+index*dx; y=fn(x+dx/2)
                            polygon(painter,[xy(x,0),xy(x+dx,0),xy(x+dx,y),xy(x,y)],"#24565D",partial)
                    elif identity=="formula":
                        math_text(layer,r"\int_a^b f(x)\,\mathrm{d}x=\lim_{n\to\infty}\sum_{i=1}^n f(x_i^*)\,\Delta x",
                                  (width*.5,height*.665),height*.07,width*.74,amount)
            elif kind=="math.pythagorean":
                a,b=float(params.get("a",3)),float(params.get("b",4))
                unit=min(width*.40/(2*a+b),height*.44/(a+2*b))
                def point(x,y):
                    return width*.32+(x-b/2)*unit,height*.44+(a/2-y)*unit
                squares={"a":([(0,0),(0,a),(-a,a),(-a,0)],(-a/2,a/2),"#28545B"),
                         "b":([(0,0),(b,0),(b,-b),(0,-b)],(b/2,-b/2),"#46533F"),
                         "c":([(b,0),(0,a),(a,a+b),(a+b,b)],((a+b)/2,(a+b)/2),"#655536")}
                if identity=="triangle":
                    polygon(painter,[point(0,0),point(b,0),point(0,a)],"#183C45",amount)
                elif identity.startswith("square_"):
                    corners,_,color=squares[identity[-1]]
                    polygon(painter,[point(*p) for p in corners],color,amount)
                elif identity.startswith("label_"):
                    _,center,_=squares[identity[-1]]
                    math_text(layer,f"{identity[-1]}^2",point(*center),height*.035,width*.10,amount)
                else:
                    formulas={"equation_a":(f"a^2={a*a:g}",.29),"equation_b":(f"b^2={b*b:g}",.43),
                              "result":(f"a^2+b^2={a*a+b*b:g}=c^2",.57)}
                    expression,y=formulas[identity]
                    math_text(layer,expression,(width*.74,height*y),height*.07,width*.33,amount)
            else:
                if identity=="formula":
                    math_text(layer,params.get("latex") or params.get("formula"),(width*.5,height*.34),height*.10,width*.74,amount)
                elif identity.startswith("step_"):
                    expression=params["steps"][int(identity.split("_")[1])-1]
                    math_text(layer,expression,(width*.5,height*.52),height*.10,width*.74,amount)
                else:
                    text=params["labels"][int(identity.split("_")[1])-1]
                    font=label_font
                    mixed=MixedScriptDraw(layer,self._english_font)
                    while mixed.textlength(text,font=font)>width*.76 and font.size>10:
                        font=ImageFont.truetype(self._font,font.size-1)
                    text_width=mixed.textlength(text,font=font)
                    mixed.text(((width-text_width)/2,height*.65),text,font=font,fill=white)
            if amount < 1 and ((chart and kind=="math.derivative_secant" and identity=="formula")
                               or (kind=="math.formula" and identity.startswith("label_"))):
                text_bounds=layer.getbbox()
                if text_bounds:
                    x1,y1,x2,y2=text_bounds
                    ImageDraw.Draw(layer).rectangle((x1+(x2-x1)*amount,0,width,height),fill=(0,0,0,0))
            opacity=presentation["opacity"]
            emphasis=state["emphasis"]
            if emphasis and identity!=emphasis["target"] and emphasis["kind"]=="focus":
                opacity*=1-.65*emphasis["strength"]
            if opacity<1:
                layer.putalpha(layer.getchannel("A").point(lambda value:round(value*opacity)))
            bounds=layer.getbbox()
            if emphasis and identity==emphasis["target"] and bounds:
                x1,y1,x2,y2=bounds
                if emphasis["kind"] in {"pulse","focus"}:
                    cropped=layer.crop(bounds)
                    zoom=emphasis["scale"]
                    enlarged=cropped.resize((max(1,round(cropped.width*zoom)),max(1,round(cropped.height*zoom))),Image.Resampling.LANCZOS)
                    x1=round((x1+x2-enlarged.width)/2); y1=round((y1+y2-enlarged.height)/2)
                    layer=Image.new("RGBA",image.size,(0,0,0,0))
                    layer.alpha_composite(enlarged,(x1,y1))
                    x2,y2=x1+enlarged.width,y1+enlarged.height
                ImageDraw.Draw(layer).rounded_rectangle((x1-7*scale,y1-7*scale,x2+7*scale,y2+7*scale),
                    radius=6*scale,outline=(247,201,107,round(255*emphasis["strength"])),width=max(2,round(5*scale)))
            image.alpha_composite(layer)
        caption=state["caption"]
        if caption:
            mixed=MixedScriptDraw(image,self._english_font)
            while mixed.textlength(caption,font=subtitle_font)>width*.85 and subtitle_font.size>10:
                subtitle_font=ImageFont.truetype(self._subtitle_font,subtitle_font.size-1)
            text_width=mixed.textlength(caption,font=subtitle_font)
            y=height*.89-subtitle_font.size*.6
            backing=Image.new("RGBA",image.size,(0,0,0,0))
            ImageDraw.Draw(backing).rounded_rectangle(((width-text_width)/2-12*scale,y-6*scale,
                        (width+text_width)/2+12*scale,y+subtitle_font.size*1.3+6*scale),radius=5*scale,fill=(0,0,0,46))
            image.alpha_composite(backing)
            MixedScriptDraw(image,self._english_font).text(((width-text_width)/2,y),caption,font=subtitle_font,
                fill=setting(self.settings,"subtitle_color","#FFFFFF"),
                stroke_fill=setting(self.settings,"subtitle_outline_color","#161044"),
                stroke_width=max(1,round(float(setting(self.settings,"subtitle_outline_width",5))*scale)))
        return image.convert("RGB")

    def render(self, scene: dict, metadata: dict, output_dir: Path) -> Path:
        self.generate(scene, metadata, output_dir)
        width, height, fps = (
            int(metadata.get("width", 1280)),
            int(metadata.get("height", 720)),
            int(metadata.get("fps", 24)),
        )
        if width % 2 or height % 2:
            raise RendererError("Video dimensions must be even for H.264 yuv420p")
        duration = float(scene.get("duration", 10))
        frames = max(1, round(duration * fps))
        output = output_dir / f"{scene_filename(scene)}.mp4"
        ffmpeg = FFmpeg(self.settings)
        args = [
            ffmpeg.binary,
            "-hide_banner",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
        log = output.with_suffix(".render.log")
        with log.open("wb") as stderr:
            proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr)
            try:
                for frame_number in range(frames):
                    denominator = frames if scene.get("extensions", {}).get("math_animation_version") == "1.0" else max(1,frames-1)
                    frame = self.frame(scene, metadata, frame_number / denominator)
                    if frame_number == frames // 2:
                        frame.save(output.with_suffix(".png"))
                    proc.stdin.write(frame.tobytes())
                proc.stdin.close()
                if proc.wait(timeout=120):
                    raise RendererError("Canvas encoding failed; inspect scene render log")
            except BaseException:
                proc.kill()
                proc.wait()
                raise
        return require_output(output)
