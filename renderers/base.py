from __future__ import annotations

import ast
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Protocol


class RendererError(RuntimeError):
    """An actionable technical render failure, never an AI review score."""


def as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return vars(value)


def setting(settings: Any, name: str, default: Any = None) -> Any:
    value = settings.get(name, default) if isinstance(settings, dict) else getattr(settings, name, default)
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return value


def scene_filename(scene: dict) -> str:
    name = str(scene["scene_id"])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
        raise RendererError("scene_id must contain only letters, digits, '_' or '-'.")
    return name


def run_command(args: list[str], *, cwd: Path | None = None, timeout: float = 1800) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RendererError(f"Could not execute {Path(args[0]).name}: {type(exc).__name__}") from exc
    if result.returncode:
        raise RendererError(f"{Path(args[0]).name} exited with {result.returncode}: {result.stderr[-4000:]}")
    return result.stdout + result.stderr


def require_output(path: Path) -> Path:
    if not path.is_file() or path.stat().st_size < 32:
        raise RendererError(f"Renderer did not produce a nonempty file: {path.name}")
    return path


_FUNCS = {name: getattr(math, name) for name in ("sin", "cos", "tan", "exp", "sqrt", "log", "log10", "fabs")}
_FUNCS["abs"] = abs


def math_function(expression: str):
    """Compile a small mathematical AST without eval, exec, or attribute access."""
    if not isinstance(expression, str) or len(expression) > 160:
        raise RendererError("Function expression must be a string of at most 160 characters.")
    try:
        tree = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise RendererError("Invalid mathematical expression") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 64:
        raise RendererError("Mathematical expression is too complex")

    def calculate(node, x):
        if isinstance(node, ast.Expression):
            return calculate(node.body, x)
        if isinstance(node, ast.Constant) and type(node.value) in (float, int) and abs(node.value) <= 1e6:
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in {"x", "pi", "e"}:
            return {"x": x, "pi": math.pi, "e": math.e}[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = calculate(node.operand, x)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            a, b = calculate(node.left, x), calculate(node.right, x)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
            if isinstance(node.op, ast.Pow) and abs(b) <= 20:
                return a**b
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and len(node.args) == 1
            and not node.keywords
        ):
            return _FUNCS[node.func.id](calculate(node.args[0], x))
        raise RendererError(
            "Unsupported mathematical syntax; use x, numbers, arithmetic and standard functions."
        )

    # Validate the complete syntax even when a sample point falls outside its domain.
    allowed = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.UnaryOp,
        ast.USub,
        ast.UAdd,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Call,
    )
    if any(not isinstance(n, allowed) for n in nodes):
        raise RendererError("Unsupported mathematical syntax")
    for node in nodes:
        if isinstance(node, ast.Name) and node.id not in {"x", "pi", "e", *_FUNCS}:
            raise RendererError("Unknown mathematical name")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS):
            raise RendererError("Unsupported mathematical function")

    def fn(x):
        value = calculate(tree, float(x))
        if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e12:
            raise RendererError("Function value exceeds the supported real plotting range")
        return float(value)

    return fn


class RendererAdapter(Protocol):
    def generate(self, scene: dict, metadata: dict, output_dir: Path) -> Path: ...
    def render(self, scene: dict, metadata: dict, output_dir: Path) -> Path: ...


def validate_component(kind: str, params: dict) -> None:
    if kind in {"math.derivative_secant", "math.integral_riemann"}:
        domain = params.get("x_range", [-1, 3] if "derivative" in kind else [0, 2])
        if not isinstance(domain, (list, tuple)) or len(domain) != 2:
            raise RendererError("x_range needs two numeric bounds")
        xmin, xmax = map(float, domain)
        if not math.isfinite(xmin) or not math.isfinite(xmax) or xmin >= xmax:
            raise RendererError("x_range must contain finite, strictly increasing bounds")
        if kind == "math.integral_riemann":
            bounds = params.get("bounds", [max(0, xmin), xmax])
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                raise RendererError("Integral bounds need two numbers")
            a, b = map(float, bounds)
            if not xmin <= a < b <= xmax:
                raise RendererError("Integral bounds must be increasing and within x_range")
            start, end = params.get("n_start", 4), params.get("n_end", 32)
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= 120:
                raise RendererError("Riemann counts must be integers with 1 <= n_start <= n_end <= 120")
        else:
            x0 = float(params.get("x0", 1))
            start, end = float(params.get("dx_start", 1.5)), float(params.get("dx_end", 0.02))
            if not xmin <= x0 < xmax or not 0 < end <= start or x0 + start > xmax:
                raise RendererError("Secant requires positive decreasing dx and both points within x_range")
    if kind == "math.pythagorean":
        a, b = float(params.get("a", 3)), float(params.get("b", 4))
        if not 0 < a <= 1e4 or not 0 < b <= 1e4:
            raise RendererError("Pythagorean legs must be positive and at most 10000")
