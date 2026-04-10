from urllib.parse import unquote

from cogs.calculator import (
    build_latex_image_url,
    calculate_diff,
    calculate_integrate,
    calculate_latex,
    calculate_solve,
    calculate_simplify,
)


def test_simplify_expression():
    result = calculate_simplify("(x^2 - 1)/(x - 1)")
    assert result.output_text == "x + 1"


def test_differentiate_expression():
    result = calculate_diff("x^3 + sin(x)")
    assert result.output_text == "3*x**2 + cos(x)"


def test_integrate_expression():
    result = calculate_integrate("x^2", "x")
    assert result.output_text == "x**3/3 + C"


def test_solve_equation():
    result = calculate_solve("x^2 - 5*x + 6 = 0", "x")
    assert "x = 2" in result.output_text
    assert "x = 3" in result.output_text


def test_latex_preview_uses_codecogs():
    result = calculate_latex("alpha + 2*beta/gamma")
    url = build_latex_image_url(result.output_latex)
    assert url.startswith("https://latex.codecogs.com/gif.image?")
    assert r"\alpha" in unquote(url)
