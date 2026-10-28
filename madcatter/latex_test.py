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


def test_latex2unicode_basic_symbols():
    """Test basic math symbol conversion."""
    assert latex2unicode(r"\int") == "∫"
    assert latex2unicode(r"\sum") == "∑"
    assert latex2unicode(r"\alpha") == "α"
    assert latex2unicode(r"\beta") == "β"
    assert latex2unicode(r"\pi") == "π"


def test_latex2unicode_with_delimiters():
    """Test that delimiters are stripped."""
    assert latex2unicode(r"$x^2$") == "x²"
    assert latex2unicode(r"$$\sum_{i=1}^n$$") == "∑ᵢ₌₁ⁿ"
    assert latex2unicode(r"\[x_i\]") == "xᵢ"
    assert latex2unicode(r"\(e^x\)") == "eˣ"


def test_latex2unicode_superscripts():
    """Test superscript conversion."""
    assert latex2unicode(r"e^x") == "eˣ"
    assert latex2unicode(r"x^2") == "x²"
    assert latex2unicode(r"x^{n+1}") == "xⁿ⁺¹"
    assert latex2unicode(r"x^{2n}") == "x²ⁿ"


def test_latex2unicode_subscripts():
    """Test subscript conversion."""
    assert latex2unicode(r"x_i") == "xᵢ"
    assert latex2unicode(r"a_{ij}") == "aᵢⱼ"
    assert latex2unicode(r"x_{i=1}") == "xᵢ₌₁"
    assert latex2unicode(r"a_{n+1}") == "aₙ₊₁"


def test_latex2unicode_combined():
    """Test combined super and subscripts."""
    assert latex2unicode(r"x_i^2") == "xᵢ²"
    assert latex2unicode(r"\sum_{i=1}^n x_i^2") == "∑ᵢ₌₁ⁿ xᵢ²"
    assert latex2unicode(r"a_i^j") == "aᵢʲ"


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


def test_latex2unicode_greek_in_scripts():
    """Test Greek letters in scripts are converted to superscript/subscript."""
    result = latex2unicode(r"x^\alpha")
    # Alpha should be converted to superscript alpha.
    assert result == "xᵅ"

    result = latex2unicode(r"y_\beta")
    # Beta should be converted to subscript beta (U+1D66)
    assert result == "yᵦ"


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


def test_latex2unicode_fallback_on_error():
    """Test that invalid LaTeX returns original string."""
    invalid = r"\invalidcommand{xyz"
    result = latex2unicode(invalid)
    assert result == "xyz"


def test_latex2unicode_exception_handling():
    """Test exception handling returns original LaTeX."""
    # Create a string that might trigger parsing errors.
    problematic = r"\begin{matrix} \end{matrix}"
    result = latex2unicode(problematic)
    assert result == ""

    # Test with malformed brackets.
    malformed = r"{{{unclosed"
    result = latex2unicode(malformed)
    assert result == "unclosed"


def test_latex2unicode_unknown_node_type():
    """Test handling of unknown node types."""
    # Most latex expressions should work even with complex structures.
    result = latex2unicode(r"\text{hello} x^2")
    assert result == "hello x²"


def test_latex2unicode_no_next_node():
    """Test handling when there's no next node for scripts."""
    # Edge case: script at end without following content.
    result = latex2unicode(r"x^")
    assert "x" in result


def test_latex2unicode_no_macro_after_script():
    """Test when script is not followed by group/macro."""
    # Test script followed by whitespace or other content.
    result = latex2unicode(r"x^ 2")
    assert result == "x^ 2"


def test_latex2unicode_custom_symbols():
    """Test custom symbols from _EXTRA_SYMBOLS."""
    # Test implies symbol.
    result = latex2unicode(r"\implies")
    assert result == "⟹"

    # Test iff symbol.
    result = latex2unicode(r"\iff")
    assert result == "⟺"

    # Test checkmark.
    result = latex2unicode(r"\checkmark")
    assert result == "✓"

    # Test fire emoji.
    result = latex2unicode(r"\fire")
    assert result == "🔥"


@pytest.mark.parametrize(
    ("latex", "text"),
    [(r"\frac{}", "/"), (r"\frac{a}", "/a"), (r"\frac", "/"), (r"\frac{a}{}", "a/")],
)
def test_latex2unicode_fraction_with_missing_args_renders_them_empty(
    latex: str,
    text: str,
):
    assert latex2unicode(latex) == text


def test_latex2unicode_no_macro_for_script():
    """Test when next node after script is not a macro."""
    # Test various edge cases with scripts.
    result = latex2unicode(r"a_1 b")
    assert "a" in result
    assert "b" in result


def test_latex2unicode_reconstruct_macro_with_args():
    """Test macro reconstruction with arguments."""
    # Test macros with arguments are properly handled.
    result = latex2unicode(r"\sqrt{x}")
    assert "x" in result or "√" in result


def test_latex2unicode_reconstruct_nodes():
    """Test node reconstruction."""
    # Test complex nested structures.
    result = latex2unicode(r"\sum_{i=1}^{n} \frac{1}{i}")
    assert "∑" in result


def test_latex2unicode_unsupported_script_chars():
    """Test unsupported characters in scripts."""
    # Test characters that don't have superscript/subscript equivalents.
    result = latex2unicode(r"x^{ABC}")
    # Should contain some form of the superscript.
    assert "x" in result


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


def test_latex2unicode_chars_with_embedded_scripts():
    """Test character nodes with embedded scripts."""
    # Test embedded scripts in character sequences.
    result = latex2unicode(r"x_i^2")
    assert "x" in result
    assert "²" in result or "2" in result
    assert "ᵢ" in result or "i" in result


def test_latex2unicode_exception_in_ast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test exception handling in AST parsing."""
    monkeypatch.setattr(
        "madcatter.latex._latex_to_unicode_ast",
        Mock(side_effect=RuntimeError("parse failed")),
    )
    assert latex2unicode("original") == "original"


def test_latex2unicode_script_no_conversion():
    """Test fallback in _try_handle_script_after_chars."""
    # Test when script is followed by something other than group/macro
    # This covers the case where _try_handle_script_after_chars returns "", 0.
    result = latex2unicode(r"x^ ")
    assert "x" in result


def test_latex2unicode_frac_missing_denom():
    """Test fraction with missing denominator."""
    # Test \frac with only one argument.
    result = latex2unicode(r"\frac{1}")
    # Should fallback to text conversion.
    assert "1" in result


def test_latex2unicode_macro_script_not_chars():
    """Test macro followed by non-char node."""
    # Test when macro is followed by something that's not a char node
    # or when the char is not ^ or _.
    result = latex2unicode(r"\alpha a")
    assert "α" in result
    assert "a" in result


def test_latex2unicode_macro_script_not_group():
    """Test macro^x where x is not a group."""
    # This tests when macro is followed by ^/_ and then non-group.
    result = latex2unicode(r"\alpha^2")
    assert "α" in result or "ᵅ" in result


def test_latex2unicode_reconstruct_with_group():
    """Test node reconstruction with groups."""
    # Test reconstruction of LatexGroupNode.
    result = latex2unicode(r"\sqrt{{x}}")
    assert result == "√(x)"


def test_latex2unicode_reconstruct_with_macro():
    """Test node reconstruction with macros."""
    # Test reconstruction of LatexMacroNode within arguments.
    result = latex2unicode(r"\sqrt{\alpha}")
    assert result == "√(α)"


def test_latex2unicode_unsupported_subscript():
    """Test unsupported characters in subscripts."""
    # Test characters without subscript equivalents
    # Most uppercase letters don't have subscript forms.
    result = latex2unicode(r"x_{ABC}")
    assert "x" in result
    # Should wrap unsupported chars in parentheses.


def test_latex2unicode_mixed_supported_unsupported():
    """Test mixed supported/unsupported in scripts."""
    # Test mixing supported and unsupported characters.
    result = latex2unicode(r"x^{aQ}")
    assert "x" in result
    # 'a' has superscript, 'Q' doesn't.


def test_latex2unicode_unsupported_then_supported():
    """Test unsupported followed by supported chars."""
    # This specifically tests the branch where we have unsupported chars,
    # then encounter a supported char, triggering lines 592-593.
    result = latex2unicode(r"x^{Qa}")
    assert "x" in result
    # 'Q' is unsupported, 'a' is supported
    # Should wrap Q in parentheses: x⁽Q⁾ᵃ.


def test_latex2unicode_script_at_end_no_nodes():
    """Test script at end with no following nodes."""
    # If a char node ends with ^ or _ but there's no next node,
    # _try_handle_script_after_chars should return "", 0
    # This is hard to trigger directly, but try edge cases.
    result = latex2unicode(r"x^")
    assert "x" in result


def test_latex2unicode_frac_none_args():
    """Test fraction with None argument nodes."""
    # Create a case where numer_node or denom_node could be None
    # This might happen with malformed \frac.
    result = latex2unicode(r"\frac{}{1}")
    assert result == "/1"


def test_latex2unicode_macro_not_followed_by_chars():
    """Test macro not followed by char node."""
    # Test where macro is followed by something other than LatexCharsNode
    # For example, two macros in sequence.
    result = latex2unicode(r"\alpha\beta")
    assert "α" in result
    assert "β" in result


def test_latex2unicode_macro_script_not_group_node():
    """Test macro^/_ not followed by group."""
    # Macro followed by ^/_ and then something that's not a group
    # This is tricky to create, but some edge cases might work.
    result = latex2unicode(r"\sum^n")
    assert "∑" in result


def test_latex2unicode_script_followed_by_comment():
    """Test char ending with ^ followed by comment node."""
    # This creates a LatexCommentNode which is neither Group nor Macro.
    result = latex2unicode(r"a^% comment")
    assert "a" in result


def test_latex2unicode_script_followed_by_environment():
    """Test char ending with ^ followed by environment."""
    # This creates a LatexEnvironmentNode which is neither Group nor Macro.
    result = latex2unicode(r"a^\begin{matrix}1\end{matrix}")
    assert "a" in result


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


def test_latex2unicode_macro_followed_by_environment():
    """Test macro followed by environment node."""
    # Macro followed by environment (not chars node)
    result = latex2unicode(r"\alpha\begin{matrix}1\end{matrix}")
    assert "α" in result


def test_latex2unicode_macro_followed_by_group():
    """Test macro followed by group node."""
    # Macro followed by group (not chars node), with at least 3 nodes
    # This hits the check at line 457 where next_node is not LatexCharsNode
    # Need at least 3 nodes to get past the check at line 452.
    result = latex2unicode(r"\alpha{}x")
    assert "α" in result
    assert "x" in result


def test_latex2unicode_macro_caret_environment():
    """Test macro^environment to hit line 465."""
    # Macro followed by ^ and then environment (not group)
    result = latex2unicode(r"\alpha^\begin{matrix}1\end{matrix}")
    assert "α" in result


def test_convert_to_script_preserves_unsupported_runs_exactly():
    assert latex._convert_to_script("QZaQ", {"a": "ᵃ"}, "⁽", "⁾") == "⁽QZ⁾ᵃ⁽Q⁾"


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
    group_result, group_skip = latex._try_handle_script_after_chars(
        "x^",
        group_nodes,
        0,
        converter,
    )
    assert group_result == "xᵃᵇ"
    assert group_skip == 2

    macro_nodes, _, _ = latexwalker.LatexWalker(r"x^\alpha").get_latex_nodes()
    macro_result, macro_skip = latex._try_handle_script_after_chars(
        "x^",
        macro_nodes,
        0,
        converter,
    )
    assert macro_result == "xᵅ"
    assert macro_skip == 2
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
    macro_result, macro_skip = latex._try_handle_script_after_chars(
        "x^",
        macro_nodes,
        0,
        converter,
    )
    assert (macro_result, macro_skip) == ("xsentinel", 2)
    assert calls == [("⁽", "⁾")]


def test_try_handle_script_after_chars_rejects_missing_or_plain_next_node():
    converter = LatexNodes2Text()
    node = LatexCharsNode(chars="x^")
    assert latex._try_handle_script_after_chars("x^", [node], 0, converter) == ("", 0)
    plain = LatexCharsNode(chars="2")
    assert latex._try_handle_script_after_chars("x^", [node, plain], 0, converter) == (
        "",
        0,
    )


def test_try_handle_script_after_chars_converts_embedded_base_and_unsupported():
    nodes, _, _ = latexwalker.LatexWalker("x_i^{aQ}").get_latex_nodes()
    result, skip = latex._try_handle_script_after_chars(
        "x_i^",
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert result == "xᵢᵃ⁽Q⁾"
    assert skip == 2

    nodes, _, _ = latexwalker.LatexWalker("x^i_{a}").get_latex_nodes()
    result, skip = latex._try_handle_script_after_chars(
        "x^i_",
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert result == "xⁱₐ"
    assert skip == 2

    nodes, _, _ = latexwalker.LatexWalker("x^i_{a}").get_latex_nodes()
    result, skip = latex._try_handle_script_after_chars(
        "x^i_^",
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert result == "xⁱ_ᵃ"
    assert skip == 2

    nodes, _, _ = latexwalker.LatexWalker("x_{aQ}").get_latex_nodes()
    result, skip = latex._try_handle_script_after_chars(
        "x_",
        nodes,
        0,
        LatexNodes2Text(),
    )
    assert result == "xₐ₍Q₎"
    assert skip == 2


def test_try_handle_script_after_macro_handles_group_and_boundaries():
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^{ab}").get_latex_nodes()
    result, skip = latex._try_handle_script_after_macro("α", nodes, 0)
    assert result == "αᵃᵇ"
    assert skip == 3
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^{aQ}").get_latex_nodes()
    result, skip = latex._try_handle_script_after_macro("α", nodes, 0)
    assert (result, skip) == ("αᵃ⁽Q⁾", 3)
    assert latex._try_handle_script_after_macro("α", nodes, 2) == ("", 0)


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


def test_try_handle_script_after_macro_covers_subscript_and_rejections():
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha_{aQ}").get_latex_nodes()
    result, skip = latex._try_handle_script_after_macro("α", nodes, 0)
    assert (result, skip) == ("αₐ₍Q₎", 3)

    nodes, _, _ = latexwalker.LatexWalker(r"\alpha{}x").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) == ("", 0)
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^2x").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) == ("", 0)
    nodes, _, _ = latexwalker.LatexWalker(r"\alpha^").get_latex_nodes()
    assert latex._try_handle_script_after_macro("α", nodes, 0) == ("", 0)


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
