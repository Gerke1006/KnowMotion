import pytest
from types import SimpleNamespace

from renderers.base import RendererError
from renderers.latex import find_compiler, validate_latex


@pytest.mark.parametrize("formula", [r"\frac{d}{dx}x^2=2x", r"\int_0^1 x^2\,dx=\frac{1}{3}",
                                   r"\lim_{h\to0}\frac{f(x+h)-f(x)}{h}",
                                   r"\begin{cases}x & x>0\\0 & x=0\end{cases}"])
def test_math_commands_allowed(formula):
    assert validate_latex(formula) == formula


@pytest.mark.parametrize("formula", [r"\input{secret}", r"\write18{command}", r"\csname input\endcsname",
                                   r"\begin{document}x\end{document}", r"^^5cinput{secret}", r"x%comment",
                                   r"\frac{1}{2", "∫x dx"])
def test_rejects_document_programming_and_legacy_unicode(formula):
    with pytest.raises(RendererError):
        validate_latex(formula)


@pytest.mark.parametrize("source", ["settings", "environment", "path", "bundled"])
def test_compiler_keeps_symlink_invocation_name(tmp_path, monkeypatch, source):
    """Resolving pdflatex to pdftex silently selects the wrong TeX format."""
    target = tmp_path / "pdftex"
    target.write_bytes(b"compiler fixture")
    alias = tmp_path / "pdflatex"
    if source == "bundled":
        alias = tmp_path / ".tools" / "latex" / "tectonic"
        alias.parent.mkdir(parents=True)
    try:
        alias.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable: {exc}")
    monkeypatch.delenv("LATEX_COMPILER_PATH", raising=False)
    monkeypatch.setattr("renderers.latex.shutil.which", lambda name: str(alias) if name == "pdflatex" else None)
    settings = SimpleNamespace(project_root=tmp_path, latex_compiler_path="")
    if source == "settings":
        settings.latex_compiler_path = str(alias)
    elif source == "environment":
        monkeypatch.setenv("LATEX_COMPILER_PATH", str(alias))

    compiler = find_compiler(settings)
    assert compiler == alias.absolute()
    assert compiler != target.absolute()
    assert compiler.stat().st_size == target.stat().st_size
