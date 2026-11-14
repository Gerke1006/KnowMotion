import pytest

from renderers.base import RendererError
from renderers.latex import validate_latex


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
