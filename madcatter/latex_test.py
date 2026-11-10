"""Tests for LaTeX to Unicode conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import functools
import re

from pylatexenc import latex2text, latexwalker
from pylatexenc.latex2text import LatexNodes2Text
from pylatexenc.latexwalker import LatexCharsNode, LatexGroupNode, LatexMacroNode
from pylatexenc.macrospec._argparsers import ParsedMacroArgs

import pytest

from madcatter import latex
from madcatter.latex import (
    _try_convert_fraction,
    latex2unicode,
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from pylatexenc.macrospec import LatexContextDb


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\int", "∫"),
        (r"\sum", "∑"),
        (r"\alpha", "α"),
        (r"\beta", "β"),
        (r"\pi", "π"),
        (r"$x^2$", "x²"),
        (r"$$\sum_{i=1}^n$$", "∑ᵢ₌₁ⁿ"),
        (r"\[x_i\]", "xᵢ"),
        (r"\(e^x\)", "eˣ"),
        (r"e^x", "eˣ"),
        (r"x^2", "x²"),
        (r"x^{n+1}", "xⁿ⁺¹"),
        (r"x^{2n}", "x²ⁿ"),
        (r"x_i", "xᵢ"),
        (r"a_{ij}", "aᵢⱼ"),
        (r"x_{i=1}", "xᵢ₌₁"),
        (r"a_{n+1}", "aₙ₊₁"),
        (r"x_i^2", "xᵢ²"),
        (r"\sum_{i=1}^n x_i^2", "∑ᵢ₌₁ⁿ xᵢ²"),
        (r"a_i^j", "aᵢʲ"),
        (r"x^\alpha", "xᵅ"),
        (r"y_\beta", "yᵦ"),
        (r"\invalidcommand{xyz", "xyz"),
        (r"\begin{matrix} \end{matrix}", ""),
        (r"{{{unclosed", "unclosed"),
        (r"\text{hello} x^2", "hello x²"),
        (r"x^ 2", "x^ 2"),
        (r"\implies", "⟹"),
        (r"\iff", "⟺"),
        (r"\checkmark", "✓"),
        (r"\fire", "🔥"),
        (r"\sqrt{{x}}", "√(x)"),
        (r"\sqrt{\alpha}", "√(α)"),
        (r"\frac{}{1}", "/1"),
    ],
)
def test_latex2unicode_exact_expressions(source: str, expected: str) -> None:
    assert latex2unicode(source) == expected


@pytest.mark.parametrize(
    ("source", "fragments"),
    [
        (r"x^", ("x",)),
        (r"a_1 b", ("a", "b")),
        (r"\sum_{i=1}^{n} \frac{1}{i}", ("∑",)),
        (r"x^{ABC}", ("x",)),
        (r"x^ ", ("x",)),
        (r"\frac{1}", ("1",)),
        (r"\alpha a", ("α", "a")),
        (r"x_{ABC}", ("x",)),
        (r"x^{aQ}", ("x",)),
        (r"x^{Qa}", ("x",)),
        (r"\alpha\beta", ("α", "β")),
        (r"\sum^n", ("∑",)),
        (r"a^% comment", ("a",)),
        (r"a^\begin{matrix}1\end{matrix}", ("a",)),
        (r"\alpha\begin{matrix}1\end{matrix}", ("α",)),
        (r"\alpha{}x", ("α", "x")),
        (r"\alpha^\begin{matrix}1\end{matrix}", ("α",)),
    ],
)
def test_latex2unicode_preserves_fragments(
    source: str,
    fragments: tuple[str, ...],
) -> None:
    result = latex2unicode(source)
    for fragment in fragments:
        assert fragment in result


def test_latex2unicode_scripts_before_trailing_group():
    r"""Embedded scripts convert even when a trailing braced group follows.

    Regresses a bug where a chars run ending in ``_`` (attaching to the next
    ``{...}`` group) had its base appended raw, dropping every embedded
    subscript before it -- e.g. the factor between ``\prod_t`` and a
    following ``p(e_{t+1}...)`` rendered ``x_t`` literally.
    """
    assert (
        latex2unicode(r"$\prod_t q(x_t|e_t) p(e_{t+1}|e_t,x_t)$")
        == "∏ₜ q(xₜ|eₜ) p(eₜ₊₁|eₜ,xₜ)"
    )


def test_latex2unicode_complex_expressions():
    """Test complex math expressions."""
    # Euler's identity.
    result = latex2unicode(r"$e^{i\pi} + 1 = 0$")
    assert "e" in result
    assert "ⁱ" in result
    assert "π" in result

    # Sum with limits.
    result = latex2unicode(r"$$\sum_{i=1}^{n} x_i^2$$")
    assert "∑" in result
    assert "ᵢ" in result
    assert "ₙ" in result or "ⁿ" in result


def test_latex2unicode_integral():
    """Test integral expressions."""
    result = latex2unicode(r"\int_0^\infty e^{-x} dx")
    assert "∫" in result
    # Subscript for plain digit after _ requires braces: _0 stays as is, _{0} converts.
    assert "_0" in result or "₀" in result
    assert "∞" in result


def test_latex2unicode_fractions():
    """Test that fractions are converted to Unicode fractions."""
    # Simple fractions convert to Unicode fraction characters.
    result = latex2unicode(r"\frac{1}{2}")
    assert result == "½"

    # Complex fractions fall back to a/b format.
    result = latex2unicode(r"\frac{13}{17}")
    assert "13" in result
    assert "17" in result


def test_a_custom_symbol_keeps_what_follows_it() -> None:
    # A control word eats the space after it, as in TeX.
    assert latex2unicode(r"a \implies b") == "a ⟹b"


@pytest.mark.parametrize(
    ("latex", "text"),
    [(r"\frac{}", "/"), (r"\frac{a}", "/a"), (r"\frac", "/"), (r"\frac{a}{}", "a/")],
)
def test_latex2unicode_fraction_with_missing_args_renders_them_empty(
    latex: str,
    text: str,
):
    assert latex2unicode(latex) == text


def test_latex2unicode_reconstruct_macro_with_args():
    """Test macro reconstruction with arguments."""
    # Test macros with arguments are properly handled.
    result = latex2unicode(r"\sqrt{x}")
    assert "x" in result or "√" in result


def test_latex2unicode_more_fractions():
    """Test more fraction conversions."""
    # Test fractions that have Unicode equivalents.
    assert latex2unicode(r"\frac{1}{3}") == "⅓"
    assert latex2unicode(r"\frac{2}{3}") == "⅔"
    assert latex2unicode(r"\frac{1}{4}") == "¼"
    assert latex2unicode(r"\frac{3}{4}") == "¾"
    assert latex2unicode(r"\frac{1}{8}") == "⅛"

    # Test fraction without Unicode equivalent.
    result = latex2unicode(r"\frac{5}{7}")
    assert "5" in result
    assert "7" in result


def test_latex2unicode_macro_with_script():
    """Test macros followed by scripts."""
    # Test macro followed by superscript group.
    result = latex2unicode(r"\alpha^{2}")
    assert "α" in result or "ᵅ" in result

    # Test macro followed by subscript group.
    result = latex2unicode(r"\beta_{i}")
    assert "β" in result or "ᵦ" in result


def test_latex2unicode_exception_in_ast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test exception handling in AST parsing."""
    monkeypatch.setattr(
        "madcatter.latex._latex_to_unicode_ast",
        Mock(side_effect=RuntimeError("parse failed")),
    )
    assert latex2unicode("original") == "original"


def test_latex2unicode_macro_script_not_group():
    """Test macro^x where x is not a group."""
    # This tests when macro is followed by ^/_ and then non-group.
    result = latex2unicode(r"\alpha^2")
    assert "α" in result or "ᵅ" in result


@pytest.mark.parametrize(
    ("argnlist", "text"),
    [
        (None, "/"),
        ([], "/"),
        ([LatexGroupNode(nodelist=[LatexCharsNode(chars="a")])], "a/"),
        ([None, LatexGroupNode(nodelist=[LatexCharsNode(chars="b")])], "/b"),
    ],
)
def test_try_convert_fraction_renders_missing_parts_empty(
    argnlist: list[LatexGroupNode | None] | None,
    text: str,
) -> None:
    node = LatexMacroNode(macroname="frac")
    node.nodeargd = None if argnlist is None else ParsedMacroArgs(argnlist=argnlist)
    assert _try_convert_fraction(node) == text


def test_convert_to_script_preserves_unsupported_runs_exactly():
    assert latex._convert_to_script("QZaQY", {"a": "ᵃ"}, "⁽", "⁾") == "⁽QZ⁾ᵃ⁽QY⁾"


def test_convert_to_script_handles_only_supported_content():
    assert (
        latex._convert_to_script("abc", {"a": "ᵃ", "b": "ᵇ", "c": "ᶜ"}, "⁽", "⁾")
        == "ᵃᵇᶜ"
    )


def test_convert_script_regexes_cover_unbraced_and_braced_ranges():
    assert latex._convert_scripts("^A") == "ᴬ"
    assert latex._convert_scripts("_A") == "₍A₎"
    assert latex._convert_scripts("_{β}") == "ᵦ"
    assert latex._convert_scripts("^∪") == "⁽∪⁾"


def test_convert_script_match_uses_braced_capture():
    super_match = re.match(r"\^(?:\{([^}]+)\}|([a-z]+))", "^{ab}")
    sub_match = re.match(r"_(?:\{([^}]+)\}|([a-z]+))", "_{ij}")
    unsupported_sub_match = re.match(r"_(?:\{([^}]+)\}|([a-z]+))", "_{Q}")
    assert super_match is not None
    assert sub_match is not None
    assert unsupported_sub_match is not None
    assert latex._convert_superscript_match(super_match) == "ᵃᵇ"
    assert latex._convert_subscript_match(sub_match) == "ᵢⱼ"
    assert latex._convert_subscript_match(unsupported_sub_match) == "₍Q₎"


def test_process_chars_node_reports_embedded_script_skip():
    converter = LatexNodes2Text()
    node = LatexCharsNode(chars="x_i")
    processed, skip = latex._process_chars_node(node, [node], 0, converter)
    assert processed == "xᵢ"
    assert skip == 1


def test_nodes_to_unicode_skips_unknown_node():
    nodes, _, _ = latexwalker.LatexWalker("x% comment\ny").get_latex_nodes()
    assert latex._nodes_to_unicode(nodes) == "xy"


def test_try_handle_script_after_chars_handles_group_and_macro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_nodes, _, _ = latexwalker.LatexWalker("x^{ab}").get_latex_nodes()
    converter = LatexNodes2Text()
    group_result = latex._try_handle_script_after_chars("x^", group_nodes, 0, converter)
    assert group_result == "xᵃᵇ"

    macro_nodes, _, _ = latexwalker.LatexWalker(r"x^\alpha").get_latex_nodes()
    macro_result = latex._try_handle_script_after_chars("x^", macro_nodes, 0, converter)
    assert macro_result == "xᵅ"
    macro_nodes, _, _ = latexwalker.LatexWalker(r"x^\alpha").get_latex_nodes()
    calls: list[tuple[str, str]] = []

    def fake_convert(
        content: str,
        mapping: dict[str, str],
        open_paren: str,
        close_paren: str,
    ) -> str:
        del content, mapping
        calls.append((open_paren, close_paren))
        return "sentinel"

    monkeypatch.setattr(latex, "_convert_to_script", fake_convert)
    macro_result = latex._try_handle_script_after_chars("x^", macro_nodes, 0, converter)
    assert macro_result == "xsentinel"
    assert calls == [("⁽", "⁾")]


def test_try_handle_script_after_chars_rejects_missing_or_plain_next_node():
    converter = LatexNodes2Text()
    node = LatexCharsNode(chars="x^")
    assert latex._try_handle_script_after_chars("x^", [node], 0, converter) is None
    plain = LatexCharsNode(chars="2")
    assert (
        latex._try_handle_script_after_chars("x^", [node, plain], 0, converter) is None
    )


def test_process_chars_node_consumes_the_script_node_it_applies():
    nodes, _, _ = latexwalker.LatexWalker("x^{ab} y").get_latex_nodes()
    processed, skip = latex._process_chars_node(
        cast(LatexCharsNode, nodes[0]),
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert (processed, skip) == ("xᵃᵇ", 2)


def test_try_handle_script_after_chars_converts_embedded_base_and_unsupported():
    nodes, _, _ = latexwalker.LatexWalker("x_i^{aQ}").get_latex_nodes()
    converter = LatexNodes2Text()
    result = latex._try_handle_script_after_chars("x_i^", nodes, 0, converter)
    assert result == "xᵢᵃ⁽Q⁾"

    nodes, _, _ = latexwalker.LatexWalker("x^i_{a}").get_latex_nodes()
    result = latex._try_handle_script_after_chars("x^i_", nodes, 0, converter)
    assert result == "xⁱₐ"

    nodes, _, _ = latexwalker.LatexWalker("x^i_{a}").get_latex_nodes()
    result = latex._try_handle_script_after_chars("x^i_^", nodes, 0, converter)
    assert result == "xⁱ_ᵃ"

    nodes, _, _ = latexwalker.LatexWalker("x_{aQ}").get_latex_nodes()
    result = latex._try_handle_script_after_chars("x_", nodes, 0, converter)
    assert result == "xₐ₍Q₎"


def test_try_handle_script_after_macro_handles_group_and_boundaries():
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^{ab}").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) == "αᵃᵇ"
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^{aQ}").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) == "αᵃ⁽Q⁾"
    assert latex._try_handle_script_after_macro("α", nodes, 2) is None


def test_reconstruct_nodes_latex_preserves_nested_macro_and_group():
    nodes, _, _ = latexwalker.LatexWalker(r"\sqrt{\alpha}").get_latex_nodes()
    assert latex._reconstruct_nodes_latex(nodes) == r"\sqrt{\alpha}"
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha\beta").get_latex_nodes()
    assert latex._reconstruct_nodes_latex(nodes) == r"\alpha\beta"


def test_process_macro_node_returns_exact_skip_for_symbols_and_fractions():
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha x").get_latex_nodes()
    processed, skip = latex._process_macro_node(
        cast(LatexMacroNode, nodes[0]),
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert (processed, skip) == ("α", 1)

    nodes, _, _ = latexwalker.LatexWalker(r"\frac{1}{2} x").get_latex_nodes()
    processed, skip = latex._process_macro_node(
        cast(LatexMacroNode, nodes[0]),
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert (processed, skip) == ("½", 1)

    nodes, _, _ = latexwalker.LatexWalker(r"\beta^{ab} x").get_latex_nodes()
    processed, skip = latex._process_macro_node(
        cast(LatexMacroNode, nodes[0]),
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert (processed, skip) == ("βᵃᵇ", 3)


def test_try_handle_script_after_macro_covers_subscript_and_rejections():
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha_{aQ}").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) == "αₐ₍Q₎"

    nodes, _, _ = latexwalker.LatexWalker(r"\alpha{}x").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) is None
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^2x").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) is None
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) is None


def test_latex2unicode_reuses_default_latex_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    latex2unicode(r"x_i^2 + \alpha^{ab} + \frac{1}{2}")
    builds: list[str] = []
    monkeypatch.setattr(
        latexwalker,
        "get_default_latex_context_db",
        functools.partial(
            _record_build,
            "latexwalker",
            latexwalker.get_default_latex_context_db,
            builds,
        ),
    )
    monkeypatch.setattr(
        latex2text,
        "get_default_latex_context_db",
        functools.partial(
            _record_build,
            "latex2text",
            latex2text.get_default_latex_context_db,
            builds,
        ),
    )
    assert latex2unicode(r"x_i^2 + \alpha^{ab} + \frac{1}{2}") == "xᵢ² + αᵃᵇ + ½"
    assert builds == []


def _record_build(
    name: str,
    build: Callable[[], LatexContextDb],
    builds: list[str],
) -> LatexContextDb:
    builds.append(name)
    return build()


def test_latex2unicode_delimiters_require_both_sides():
    assert latex2unicode("$x") == ""
    assert latex2unicode("x$") == "x"
    assert latex2unicode("$$x") == ""
    assert latex2unicode("x$$") == "x"
    assert latex2unicode(r"\[x") == ""
    assert latex2unicode(r"x\]") == "x"
    assert latex2unicode(r"\(x") == ""
    assert latex2unicode(r"x\)") == "x"


if __name__ == "__main__":
    from madcatter.lib.testing.runner import test_main

    test_main(__file__)
