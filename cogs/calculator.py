"""
cogs/calculator.py - Interactive symbolic calculator
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
    output_text: str
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
    except Exception as exc:
        raise CalculatorError(f"Couldn't parse `{expression}`.") from exc


def _parse_equation(equation: str) -> Eq:
    if "=" not in equation:
        raise CalculatorError("Use an equals sign for solving, like `x^2 - 4 = 0`.")
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


def calculate_evaluate(expression: str, variable: str | None = None) -> CalculationResult:
    del variable
    expr = _parse_expression(expression)
    result = expr.evalf() if not expr.free_symbols else simplify(expr)
    extra_lines = ()
    if expr.free_symbols:
        extra_lines = ("Symbols remain, so the result was simplified symbolically.",)
    return CalculationResult(
        title="Evaluate",
        output_text=sstr(result),
        output_latex=latex(result),
        extra_lines=extra_lines,
    )


def calculate_simplify(expression: str, variable: str | None = None) -> CalculationResult:
    del variable
    expr = _parse_expression(expression)
    result = simplify(expr)
    return CalculationResult(
        title="Simplify",
        output_text=sstr(result),
        output_latex=latex(result),
    )


def calculate_diff(expression: str, variable: str | None = None) -> CalculationResult:
    expr = _parse_expression(expression)
    symbol = _pick_symbol(expr, variable)
    result = expr.diff(symbol)
    return CalculationResult(
        title=f"Differentiate by {symbol}",
        output_text=sstr(result),
        output_latex=latex(result),
    )


def calculate_integrate(expression: str, variable: str | None = None) -> CalculationResult:
    expr = _parse_expression(expression)
    symbol = _pick_symbol(expr, variable)
    result = expr.integrate(symbol)
    return CalculationResult(
        title=f"Integrate by {symbol}",
        output_text=f"{sstr(result)} + C",
        output_latex=latex(result) + " + C",
    )


def calculate_solve(expression: str, variable: str | None = None) -> CalculationResult:
    relation = _parse_equation(expression)
    symbol = _pick_symbol_from_items((relation.lhs, relation.rhs), variable)
    solutions = solve(relation, symbol)
    if not solutions:
        return CalculationResult(
            title=f"Solve for {symbol}",
            output_text="No exact symbolic solution found.",
            output_latex=latex(relation),
        )
    output_text = "\n".join(f"{symbol} = {sstr(item)}" for item in solutions)
    if len(solutions) == 1:
        output_latex = latex(Eq(symbol, solutions[0]))
    else:
        output_latex = latex(symbol) + " \\in \\left\\{" + ", ".join(latex(item) for item in solutions) + "\\right\\}"
    return CalculationResult(
        title=f"Solve for {symbol}",
        output_text=output_text,
        output_latex=output_latex,
    )


def calculate_domain(expression: str, variable: str | None = None) -> CalculationResult:
    expr = _parse_expression(expression)
    symbol = _pick_symbol(expr, variable)
    result = continuous_domain(expr, symbol, S.Reals)
    return CalculationResult(
        title=f"Domain in {symbol}",
        output_text=sstr(result),
        output_latex=latex(result),
    )


def calculate_latex(expression: str, variable: str | None = None) -> CalculationResult:
    del variable
    expr = _parse_expression(expression)
    rendered = latex(expr)
    return CalculationResult(
        title="LaTeX",
        output_text=rendered,
        output_latex=rendered,
        extra_lines=(f"```text\n{pretty(expr)}\n```",),
    )


CALCULATOR_ACTIONS: dict[str, tuple[str, callable]] = {
    "evaluate": ("Evaluate", calculate_evaluate),
    "simplify": ("Simplify", calculate_simplify),
    "differentiate": ("Differentiate", calculate_diff),
    "integrate": ("Integrate", calculate_integrate),
    "solve": ("Solve", calculate_solve),
    "domain": ("Domain", calculate_domain),
    "latex": ("LaTeX", calculate_latex),
}


def build_session_container(
    expression: str,
    variable: str | None,
    action_key: str | None = None,
    result: CalculationResult | None = None,
    error_text: str | None = None,
) -> discord.ui.Container:
    container = discord.ui.Container(accent_color=discord.Color.blurple())
    container.add_item(discord.ui.TextDisplay("## Calculator"))
    container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**Original**\n```text\n{expression}\n```")))
    container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**Variable**\n{variable or 'Auto'}")))

    if action_key is None:
        container.add_item(discord.ui.Section(discord.ui.TextDisplay("**Operation**\nChoose a button below.")))
        container.add_item(discord.ui.Section(discord.ui.TextDisplay("**Result**\nNo calculation run yet.")))
        return container

    label = CALCULATOR_ACTIONS[action_key][0]
    container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**Operation**\n{label}")))
    if error_text is not None:
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**Result**\n{error_text}")))
        return container

    assert result is not None
    container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**Result**\n```text\n{result.output_text}\n```")))
    if result.extra_lines:
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(f"**Details**\n" + "\n".join(result.extra_lines))))
    
    container.add_item(discord.ui.TextDisplay("**LaTeX Preview**"))
    gallery = discord.ui.MediaGallery()
    gallery.add_item(media=build_latex_image_url(result.output_latex))
    container.add_item(gallery)
    
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay("Your original equation stays unchanged. Use another button to try a different operation."))
    return container


class CalcSessionView(discord.ui.LayoutView):
    def __init__(self, owner_id: int, expression: str, variable: str | None, container: discord.ui.Container):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.expression = expression
        self.variable = variable
        self.container = container
        self.refresh_components()

    def refresh_components(self):
        # We need to preserve buttons, but update the container
        # Actually, buttons are decorators, so they are added to the class.
        # LayoutView.clear_items() removes them.
        # So we should re-add them if they were removed.
        # But wait, decorators add them to the view instance on init.
        pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the command user can use these calculator buttons.", ephemeral=True)
            return False
        return True

    async def _run_action(self, interaction: discord.Interaction, action_key: str):
        _, action = CALCULATOR_ACTIONS[action_key]
        try:
            result = action(self.expression, self.variable)
        except CalculatorError as exc:
            self.container = build_session_container(self.expression, self.variable, action_key, error_text=str(exc))
        except Exception as exc:
            self.container = build_session_container(self.expression, self.variable, action_key, error_text=f"Calculation failed: {exc}")
        else:
            self.container = build_session_container(self.expression, self.variable, action_key, result=result)
        
        # Re-add container
        self.clear_items()
        self.add_item(self.container)
        # Re-add buttons (this is a bit annoying with standard discord.py View decorators)
        # But wait, LayoutView works differently?
        # Actually, if we use decorators, we should just let them be.
        # Clear items removes them though.
        
        # Let's try a different approach: keep the buttons and just replace the container item.
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Evaluate", style=discord.ButtonStyle.primary, row=0)
    async def evaluate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_action(interaction, "evaluate")

    @discord.ui.button(label="Simplify", style=discord.ButtonStyle.secondary, row=0)
    async def simplify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_action(interaction, "simplify")

    @discord.ui.button(label="Differentiate", style=discord.ButtonStyle.secondary, row=0)
    async def differentiate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_action(interaction, "differentiate")

    @discord.ui.button(label="Integrate", style=discord.ButtonStyle.secondary, row=0)
    async def integrate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_action(interaction, "integrate")

    @discord.ui.button(label="Solve", style=discord.ButtonStyle.secondary, row=1)
    async def solve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_action(interaction, "solve")

    @discord.ui.button(label="Domain", style=discord.ButtonStyle.secondary, row=1)
    async def domain_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_action(interaction, "domain")

    @discord.ui.button(label="LaTeX", style=discord.ButtonStyle.secondary, row=1)
    async def latex_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_action(interaction, "latex")


class CalculatorCog(commands.Cog, name="Calculator"):
    """Single-command symbolic calculator."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="calc", description="Open an interactive calculator session for one equation")
    @app_commands.describe(
        expression="Expression or equation like x^2 - 5*x + 6 = 0",
        variable="Optional variable to use for diff, integrate, solve, or domain",
    )
    async def calc(self, interaction: discord.Interaction, expression: str, variable: str | None = None):
        expr = expression.strip()
        var = variable.strip() if variable else None
        container = build_session_container(expr, var)
        view = CalcSessionView(interaction.user.id, expr, var, container)
        view.add_item(container)
        await interaction.response.send_message(view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(CalculatorCog(bot))
