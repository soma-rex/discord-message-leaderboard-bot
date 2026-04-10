"""
cogs/calculator.py - Symbolic calculator commands with LaTeX rendering
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands
from sympy import Eq, S, Symbol, latex, pi, pretty, simplify, solve
from sympy.calculus.util import continuous_domain
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)
from sympy.printing.str import sstr


TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)
LATEX_BASE_URL = "https://latex.codecogs.com/gif.image?\\dpi{200}%20"
DEFAULT_SYMBOLS = {
    name: Symbol(name)
    for name in (
        "a", "b", "c", "d", "e", "f", "g", "h",
        "i", "j", "k", "m", "n", "p", "q", "r",
        "s", "t", "u", "v", "w", "x", "y", "z",
        "alpha", "beta", "gamma", "theta", "lambda",
        "mu", "sigma", "tau", "phi", "omega",
    )
}
DEFAULT_SYMBOLS["pi"] = pi


class CalculatorError(ValueError):
    """Raised when the calculator cannot understand an expression."""


@dataclass(slots=True)
class CalculationResult:
    title: str
    input_text: str
    output_text: str
    input_latex: str
    output_latex: str
    extra_lines: tuple[str, ...] = ()


def build_latex_image_url(latex_expression: str) -> str:
    return LATEX_BASE_URL + quote(latex_expression, safe="")


def _parse_expression(expression: str):
    try:
        return parse_expr(
            expression,
            local_dict=DEFAULT_SYMBOLS.copy(),
            transformations=TRANSFORMATIONS,
            evaluate=True,
        )
    except Exception as exc:  # pragma: no cover - SymPy parser raises many types
        raise CalculatorError(f"Couldn't parse `{expression}`.") from exc


def _parse_equation(equation: str) -> Eq:
    if "=" not in equation:
        raise CalculatorError("Use an equals sign, like `x^2 - 4 = 0`.")
    left, right = equation.split("=", 1)
    return Eq(_parse_expression(left), _parse_expression(right))


def _pick_symbol(expr, variable: str | None) -> Symbol:
    if variable:
        return Symbol(variable)
    symbols = sorted(expr.free_symbols, key=lambda item: item.name)
    if not symbols:
        return Symbol("x")
    return symbols[0]


def _pick_symbol_from_items(items: Iterable, variable: str | None) -> Symbol:
    if variable:
        return Symbol(variable)
    free_symbols = set()
    for item in items:
        free_symbols.update(getattr(item, "free_symbols", set()))
    if not free_symbols:
        return Symbol("x")
    return sorted(free_symbols, key=lambda item: item.name)[0]


def make_embed(result: CalculationResult) -> discord.Embed:
    embed = discord.Embed(title=result.title, color=discord.Color.blurple())
    embed.add_field(name="Input", value=f"```text\n{result.input_text}\n```", inline=False)
    embed.add_field(name="Result", value=f"```text\n{result.output_text}\n```", inline=False)
    if result.extra_lines:
        embed.add_field(name="Details", value="\n".join(result.extra_lines), inline=False)
    embed.add_field(
        name="LaTeX Preview",
        value=(
            f"[Input Image]({build_latex_image_url(result.input_latex)})\n"
            f"[Result Image]({build_latex_image_url(result.output_latex)})"
        ),
        inline=False,
    )
    embed.set_image(url=build_latex_image_url(result.output_latex))
    embed.set_footer(text="Rendered with CodeCogs LaTeX")
    return embed


def calculate_evaluate(expression: str) -> CalculationResult:
    expr = _parse_expression(expression)
    result = expr.evalf() if not expr.free_symbols else simplify(expr)
    extra_lines = ()
    if expr.free_symbols:
        extra_lines = ("Symbols remain, so the result was simplified symbolically.",)
    return CalculationResult(
        title="Calculator",
        input_text=sstr(expr),
        output_text=sstr(result),
        input_latex=latex(expr),
        output_latex=latex(result),
        extra_lines=extra_lines,
    )


def calculate_simplify(expression: str) -> CalculationResult:
    expr = _parse_expression(expression)
    result = simplify(expr)
    return CalculationResult(
        title="Simplify",
        input_text=sstr(expr),
        output_text=sstr(result),
        input_latex=latex(expr),
        output_latex=latex(result),
    )


def calculate_diff(expression: str, variable: str | None = None) -> CalculationResult:
    expr = _parse_expression(expression)
    symbol = _pick_symbol(expr, variable)
    result = expr.diff(symbol)
    return CalculationResult(
        title="Differentiate",
        input_text=f"d/d{symbol} {sstr(expr)}",
        output_text=sstr(result),
        input_latex=latex(expr),
        output_latex=latex(result),
    )


def calculate_integrate(expression: str, variable: str | None = None) -> CalculationResult:
    expr = _parse_expression(expression)
    symbol = _pick_symbol(expr, variable)
    result = expr.integrate(symbol)
    return CalculationResult(
        title="Integrate",
        input_text=f"Integral of {sstr(expr)} d{symbol}",
        output_text=f"{sstr(result)} + C",
        input_latex=latex(expr),
        output_latex=latex(result) + " + C",
    )


def calculate_solve(equation: str, variable: str | None = None) -> CalculationResult:
    relation = _parse_equation(equation)
    symbol = _pick_symbol_from_items((relation.lhs, relation.rhs), variable)
    solutions = solve(relation, symbol)
    if not solutions:
        output_text = "No exact symbolic solution found."
        output_latex = latex(relation)
    else:
        output_text = "\n".join(f"{symbol} = {sstr(item)}" for item in solutions)
        if len(solutions) == 1:
            output_latex = latex(Eq(symbol, solutions[0]))
        else:
            output_latex = latex(symbol) + " \\in \\left\\{" + ", ".join(latex(item) for item in solutions) + "\\right\\}"
    return CalculationResult(
        title="Solve Equation",
        input_text=sstr(relation),
        output_text=output_text,
        input_latex=latex(relation),
        output_latex=output_latex,
    )


def calculate_domain(expression: str, variable: str | None = None) -> CalculationResult:
    expr = _parse_expression(expression)
    symbol = _pick_symbol(expr, variable)
    result = continuous_domain(expr, symbol, S.Reals)
    return CalculationResult(
        title="Domain",
        input_text=sstr(expr),
        output_text=sstr(result),
        input_latex=latex(expr),
        output_latex=latex(result),
    )


def calculate_latex(expression: str) -> CalculationResult:
    expr = _parse_expression(expression)
    rendered = latex(expr)
    return CalculationResult(
        title="LaTeX",
        input_text=sstr(expr),
        output_text=rendered,
        input_latex=rendered,
        output_latex=rendered,
        extra_lines=(f"```text\n{pretty(expr)}\n```",),
    )


class CalculatorCog(commands.Cog, name="Calculator"):
    """Symbolic calculator and LaTeX rendering commands."""

    calc_group = app_commands.Group(name="calc", description="Advanced calculator commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _run_calculation(self, interaction: discord.Interaction, action):
        try:
            result = action()
        except CalculatorError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except Exception as exc:
            await interaction.response.send_message(
                f"Calculation failed: {exc}",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=make_embed(result))

    @calc_group.command(name="eval", description="Evaluate or simplify a math expression")
    @app_commands.describe(expression="Expression like 2*sin(pi/4) + 3^2")
    async def evaluate(self, interaction: discord.Interaction, expression: str):
        await self._run_calculation(interaction, lambda: calculate_evaluate(expression))

    @calc_group.command(name="simplify", description="Simplify a symbolic expression")
    @app_commands.describe(expression="Expression like (x^2 - 1)/(x - 1)")
    async def simplify_cmd(self, interaction: discord.Interaction, expression: str):
        await self._run_calculation(interaction, lambda: calculate_simplify(expression))

    @calc_group.command(name="diff", description="Differentiate an expression")
    @app_commands.describe(
        expression="Expression like x^3 + sin(x)",
        variable="Differentiate with respect to this variable",
    )
    async def diff_cmd(self, interaction: discord.Interaction, expression: str, variable: str | None = None):
        await self._run_calculation(interaction, lambda: calculate_diff(expression, variable))

    @calc_group.command(name="integrate", description="Integrate an expression")
    @app_commands.describe(
        expression="Expression like x^2 + cos(x)",
        variable="Integrate with respect to this variable",
    )
    async def integrate_cmd(self, interaction: discord.Interaction, expression: str, variable: str | None = None):
        await self._run_calculation(interaction, lambda: calculate_integrate(expression, variable))

    @calc_group.command(name="solve", description="Solve an equation")
    @app_commands.describe(
        equation="Equation like x^2 - 5*x + 6 = 0",
        variable="Solve for this variable",
    )
    async def solve_cmd(self, interaction: discord.Interaction, equation: str, variable: str | None = None):
        await self._run_calculation(interaction, lambda: calculate_solve(equation, variable))

    @calc_group.command(name="domain", description="Find the real-number domain of an expression")
    @app_commands.describe(
        expression="Expression like sqrt(x - 2)/(x - 5)",
        variable="Use this variable for the domain",
    )
    async def domain_cmd(self, interaction: discord.Interaction, expression: str, variable: str | None = None):
        await self._run_calculation(interaction, lambda: calculate_domain(expression, variable))

    @calc_group.command(name="latex", description="Render an expression as LaTeX using CodeCogs")
    @app_commands.describe(expression="Expression like alpha + 2*beta/gamma")
    async def latex_cmd(self, interaction: discord.Interaction, expression: str):
        await self._run_calculation(interaction, lambda: calculate_latex(expression))


async def setup(bot: commands.Bot):
    await bot.add_cog(CalculatorCog(bot))
