"""Real LaTeX -> PDF -> vector paths or transparent pixels; never a text fallback."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from filelock import FileLock

try:
    from .base import RendererError, setting
except ImportError:
    from vibe_render_base import RendererError, setting


_COMMANDS = set("""
frac dfrac tfrac sqrt lim limsup liminf sum prod int iint iiint oint
infty partial nabla Delta delta alpha beta gamma Gamma theta Theta lambda Lambda
mu nu pi Pi rho sigma Sigma tau phi Phi varphi psi Psi omega Omega epsilon varepsilon
eta zeta xi Xi kappa upsilon Upsilon
sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln exp min max sup inf
det gcd Pr mod bmod pmod
to rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow mapsto xrightarrow xleftarrow
le leq ge geq ne neq approx sim simeq equiv propto in notin subset supset subseteq supseteq
cup cap emptyset forall exists neg land lor
cdot times div pm mp circ degree prime
left right big Big bigg Bigg lvert rvert vert lVert rVert Vert langle rangle
underbrace overbrace overline underline bar hat widehat tilde widetilde vec dot ddot
mathrm mathit mathbf mathsf mathtt mathcal mathbb mathfrak boldsymbol operatorname
text textrm textit textbf displaystyle textstyle scriptstyle scriptscriptstyle
quad qquad limits nolimits substack binom dbinom tbinom
begin end ldots cdots vdots ddots hline cr
""".split())
_ENVIRONMENTS = {"aligned", "gathered", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "cases"}
_ESCAPES = {",", ";", ":", "!", " ", "{", "}", "%", "_", "#", "&", "\\", "|"}


def validate_latex(expression: str) -> str:
    """Accept bounded math markup, never arbitrary TeX programs or document commands."""
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 2000:
        raise RendererError("LaTeX formula must contain 1 to 2000 characters")
    expression = expression.strip()
    if expression.startswith("$$") and expression.endswith("$$"):
        expression = expression[2:-2].strip()
    elif expression.startswith("$") and expression.endswith("$"):
        expression = expression[1:-1].strip()
    if not expression or any(ord(char) > 127 for char in expression):
        raise RendererError("Use LaTeX commands for mathematical symbols, e.g. \\int and \\Delta")
    if any(char in expression for char in ("\x00", "\x1b", "$", "~")) or "^^" in expression:
        raise RendererError("Unsupported LaTeX control syntax")

    def check_command(match):
        token = match.group(1)
        if token not in _COMMANDS and token not in _ESCAPES:
            raise RendererError(f"Unsupported LaTeX command: \\{token}")
        return ""

    remaining = re.sub(r"\\([A-Za-z]+|[^A-Za-z])", check_command, expression)
    if "\\" in remaining or "%" in remaining or "#" in remaining:
        raise RendererError("Unsupported LaTeX syntax")
    for environment in re.findall(r"\\(?:begin|end)\s*\{([^{}]+)\}", expression):
        if environment not in _ENVIRONMENTS:
            raise RendererError("Only mathematical LaTeX environments are supported")
    depth = 0
    for char in re.sub(r"\\[{}]", "", expression):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if depth < 0 or depth > 30:
            raise RendererError("Unbalanced or overly nested LaTeX braces")
    if depth:
        raise RendererError("Unbalanced LaTeX braces")
    return expression


def find_compiler(settings=None) -> Path:
    configured = setting(settings, "latex_compiler_path", "") or os.environ.get("LATEX_COMPILER_PATH", "")
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.is_file():
            return path
        raise RendererError("LATEX_COMPILER_PATH does not point to an existing executable")
    project = Path(setting(settings, "project_root", Path(__file__).resolve().parents[1]))
    for candidate in (project / ".tools/latex/tectonic.exe", project / ".tools/latex/tectonic"):
        if candidate.is_file():
            return candidate.resolve()
    for executable in ("tectonic", "pdflatex"):
        found = shutil.which(executable)
        if found:
            return Path(found).resolve()
    raise RendererError("Real LaTeX requires Tectonic or pdflatex. Set LATEX_COMPILER_PATH; no text fallback is used.")


def _paths(expression: str, cache_dir: Path, settings=None):
    expression = validate_latex(expression)
    compiler = find_compiler(settings)
    fingerprint = hashlib.sha256(json.dumps({
        "expression": expression, "compiler": str(compiler), "compiler_size": compiler.stat().st_size,
        "template": "article-amsmath-paths-v1",
    }, sort_keys=True).encode()).hexdigest()
    folder = Path(cache_dir).resolve() / fingerprint
    folder.mkdir(parents=True, exist_ok=True)
    return expression, compiler, folder


def _compile(expression: str, compiler: Path, folder: Path) -> Path:
    pdf = folder / "formula.pdf"
    marker = folder / "compiled.ok"
    if pdf.is_file() and pdf.stat().st_size > 100 and marker.is_file():
        return pdf
    source = folder / "formula.tex"
    source.write_text(
        "\\documentclass[12pt]{article}\n\\usepackage{amsmath,amssymb}\n"
        "\\pagestyle{empty}\n\\begin{document}\n\\noindent$\\displaystyle "
        + expression + "$\n\\end{document}\n", encoding="utf-8",
    )
    if "tectonic" in compiler.name.casefold():
        command = [str(compiler), "--untrusted", "--keep-logs", "--outdir", str(folder), str(source)]
    else:
        command = [str(compiler), "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                   "-output-directory", str(folder), str(source)]
    try:
        # Tectonic first-run format creation uses a shared cache. Concurrent
        # Windows renames can fail even when separate formulas have separate dirs.
        lock_name = hashlib.sha256(str(compiler).encode()).hexdigest()[:24]
        with FileLock(Path(tempfile.gettempdir()) / f"vibe-latex-{lock_name}.lock", timeout=660):
            result = subprocess.run(command, cwd=folder, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RendererError(f"LaTeX compiler could not finish ({type(exc).__name__})") from exc
    if result.returncode or not pdf.is_file():
        detail = (result.stderr + "\n" + result.stdout)[-2500:]
        raise RendererError(f"LaTeX compilation failed: {detail}")
    marker.write_text("success\n", encoding="ascii")
    return pdf


def _cropped_document(pdf: Path):
    try:
        import pymupdf
    except ImportError as exc:
        raise RendererError("Install pymupdf to convert compiled LaTeX PDF into SVG/PNG") from exc
    doc = pymupdf.open(pdf)
    if len(doc) != 1:
        doc.close()
        raise RendererError("A formula must render on one PDF page")
    page = doc[0]
    bounds = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                bounds.append(pymupdf.Rect(span["bbox"]))
    for drawing in page.get_drawings():
        bounds.append(drawing["rect"])
    if not bounds:
        doc.close()
        raise RendererError("LaTeX produced no visible mathematical glyphs")
    rect = bounds[0]
    for item in bounds[1:]:
        rect |= item
    rect = (rect + (-2, -2, 2, 2)) & page.rect
    page.set_cropbox(rect)
    return doc


def render_latex_svg(expression: str, cache_dir: Path, settings=None) -> Path:
    expression, compiler, folder = _paths(expression, cache_dir, settings)
    svg = folder / "formula.svg"
    with FileLock(folder / ".compile.lock", timeout=660):
        if svg.is_file() and svg.stat().st_size > 100:
            return svg
        pdf = _compile(expression, compiler, folder)
        with _cropped_document(pdf) as doc:
            svg.write_text(doc[0].get_svg_image(text_as_path=True), encoding="utf-8")
    return svg


def render_latex_png(expression: str, cache_dir: Path, settings=None, scale: float = 3) -> Path:
    if not 0.5 <= scale <= 12:
        raise RendererError("LaTeX raster scale must be between 0.5 and 12")
    expression, compiler, folder = _paths(expression, cache_dir, settings)
    png = folder / f"formula-{scale:g}.png"
    with FileLock(folder / ".compile.lock", timeout=660):
        if png.is_file() and png.stat().st_size > 32:
            return png
        pdf = _compile(expression, compiler, folder)
        with _cropped_document(pdf) as doc:
            import pymupdf
            doc[0].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=True).save(png)
    return png
