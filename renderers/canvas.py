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
                    frame = self.frame(scene, metadata, frame_number / max(1, frames - 1))
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
