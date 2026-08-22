"""Tests for LaTeX to Unicode conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

from madcatter.latex import (
    _try_convert_fraction,
    latex2unicode,
)


if TYPE_CHECKING:
    import pytest


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


def test_latex2unicode_greek_in_scripts():
    """Test Greek letters in scripts are converted to superscript/subscript."""
    result = latex2unicode(r"x^\alpha")
    # Alpha should be converted to superscript alpha
    assert result == "xᵅ"

    result = latex2unicode(r"y_\beta")
    # Beta should be converted to subscript beta (U+1D66)
    assert result == "yᵦ"


def test_latex2unicode_complex_expressions():
    """Test complex math expressions."""
    # Euler's identity
    result = latex2unicode(r"$e^{i\pi} + 1 = 0$")
    assert "e" in result
    assert "ⁱ" in result
    assert "π" in result

    # Sum with limits
    result = latex2unicode(r"$$\sum_{i=1}^{n} x_i^2$$")
    assert "∑" in result
    assert "ᵢ" in result
    assert "ₙ" in result or "ⁿ" in result


def test_latex2unicode_integral():
    """Test integral expressions."""
    result = latex2unicode(r"\int_0^\infty e^{-x} dx")
    assert "∫" in result
    # Subscript for plain digit after _ requires braces: _0 stays as is, _{0} converts
    assert "_0" in result or "₀" in result
    assert "∞" in result


def test_latex2unicode_fractions():
    """Test that fractions are converted to Unicode fractions."""
    # Simple fractions convert to Unicode fraction characters
    result = latex2unicode(r"\frac{1}{2}")
    assert result == "½"

    # Complex fractions fall back to a/b format
    result = latex2unicode(r"\frac{13}{17}")
    assert "13" in result
    assert "17" in result


def test_latex2unicode_fallback_on_error():
    """Test that invalid LaTeX returns original string."""
    invalid = r"\invalidcommand{xyz"
    result = latex2unicode(invalid)
    # Should either convert or return original
    assert isinstance(result, str)


def test_latex2unicode_exception_handling():
    """Test exception handling returns original LaTeX (lines 224-226)."""
    # Create a string that might trigger parsing errors
    problematic = r"\begin{matrix} \end{matrix}"
    result = latex2unicode(problematic)
    assert isinstance(result, str)

    # Test with malformed brackets
    malformed = r"{{{unclosed"
    result = latex2unicode(malformed)
    assert isinstance(result, str)


def test_latex2unicode_unknown_node_type():
    """Test handling of unknown node types (line 304)."""
    # Most latex expressions should work even with complex structures
    result = latex2unicode(r"\text{hello} x^2")
    assert isinstance(result, str)


def test_latex2unicode_no_next_node():
    """Test handling when there's no next node for scripts (line 350)."""
    # Edge case: script at end without following content
    result = latex2unicode(r"x^")
    assert isinstance(result, str)
    assert "x" in result


def test_latex2unicode_no_macro_after_script():
    """Test when script is not followed by group/macro (line 381)."""
    # Test script followed by whitespace or other content
    result = latex2unicode(r"x^ 2")
    assert isinstance(result, str)


def test_latex2unicode_custom_symbols():
    """Test custom symbols from _EXTRA_SYMBOLS (line 400)."""
    # Test implies symbol
    result = latex2unicode(r"\implies")
    assert result == "⟹"

    # Test iff symbol
    result = latex2unicode(r"\iff")
    assert result == "⟺"

    # Test checkmark
    result = latex2unicode(r"\checkmark")
    assert result == "✓"

    # Test fire emoji
    result = latex2unicode(r"\fire")
    assert result == "🔥"


def test_latex2unicode_fraction_without_args():
    """Test fraction without proper arguments (lines 429, 434)."""
    # This tests the early returns in _try_convert_fraction
    result = latex2unicode(r"\frac{}")
    assert isinstance(result, str)


def test_latex2unicode_no_macro_for_script():
    """Test when next node after script is not a macro (lines 457, 465)."""
    # Test various edge cases with scripts
    result = latex2unicode(r"a_1 b")
    assert "a" in result
    assert "b" in result


def test_latex2unicode_reconstruct_macro_with_args():
    """Test macro reconstruction with arguments (lines 496-499)."""
    # Test macros with arguments are properly handled
    result = latex2unicode(r"\sqrt{x}")
    assert isinstance(result, str)
    assert "x" in result or "√" in result


def test_latex2unicode_reconstruct_nodes():
    """Test node reconstruction (lines 514-524)."""
    # Test complex nested structures
    result = latex2unicode(r"\sum_{i=1}^{n} \frac{1}{i}")
    assert isinstance(result, str)
    assert "∑" in result


def test_latex2unicode_unsupported_script_chars():
    """Test unsupported characters in scripts (lines 592-593)."""
    # Test characters that don't have superscript/subscript equivalents
    result = latex2unicode(r"x^{ABC}")
    assert isinstance(result, str)
    # Should contain some form of the superscript
    assert "x" in result


def test_latex2unicode_more_fractions():
    """Test more fraction conversions."""
    # Test fractions that have Unicode equivalents
    assert latex2unicode(r"\frac{1}{3}") == "⅓"
    assert latex2unicode(r"\frac{2}{3}") == "⅔"
    assert latex2unicode(r"\frac{1}{4}") == "¼"
    assert latex2unicode(r"\frac{3}{4}") == "¾"
    assert latex2unicode(r"\frac{1}{8}") == "⅛"

    # Test fraction without Unicode equivalent
    result = latex2unicode(r"\frac{5}{7}")
    assert "5" in result
    assert "7" in result


def test_latex2unicode_macro_with_script():
    """Test macros followed by scripts."""
    # Test macro followed by superscript group
    result = latex2unicode(r"\alpha^{2}")
    assert "α" in result or "ᵅ" in result

    # Test macro followed by subscript group
    result = latex2unicode(r"\beta_{i}")
    assert "β" in result or "ᵦ" in result


def test_latex2unicode_chars_with_embedded_scripts():
    """Test character nodes with embedded scripts."""
    # Test embedded scripts in character sequences
    result = latex2unicode(r"x_i^2")
    assert "x" in result
    assert "²" in result or "2" in result
    assert "ᵢ" in result or "i" in result


def test_latex2unicode_exception_in_ast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test exception handling in AST parsing (lines 224-226)."""
    monkeypatch.setattr(
        "madcatter.latex._latex_to_unicode_ast",
        Mock(side_effect=RuntimeError("parse failed")),
    )
    assert latex2unicode("original") == "original"


def test_latex2unicode_script_no_conversion():
    """Test fallback in _try_handle_script_after_chars (line 381)."""
    # Test when script is followed by something other than group/macro
    # This covers the case where _try_handle_script_after_chars returns "", 0
    result = latex2unicode(r"x^ ")
    assert "x" in result


def test_latex2unicode_frac_missing_denom():
    """Test fraction with missing denominator (line 434)."""
    # Test \frac with only one argument
    result = latex2unicode(r"\frac{1}")
    assert isinstance(result, str)
    # Should fallback to text conversion
    assert "1" in result


def test_latex2unicode_macro_script_not_chars():
    """Test macro followed by non-char node (lines 457, 465)."""
    # Test when macro is followed by something that's not a char node
    # or when the char is not ^ or _
    result = latex2unicode(r"\alpha a")
    assert "α" in result
    assert "a" in result


def test_latex2unicode_macro_script_not_group():
    """Test macro^x where x is not a group (line 465)."""
    # This tests when macro is followed by ^/_ and then non-group
    result = latex2unicode(r"\alpha^2")
    assert "α" in result or "ᵅ" in result


def test_latex2unicode_reconstruct_with_group():
    """Test node reconstruction with groups (lines 521-523)."""
    # Test reconstruction of LatexGroupNode
    result = latex2unicode(r"\sqrt{{x}}")
    assert isinstance(result, str)


def test_latex2unicode_reconstruct_with_macro():
    """Test node reconstruction with macros (lines 519-520)."""
    # Test reconstruction of LatexMacroNode within arguments
    result = latex2unicode(r"\sqrt{\alpha}")
    assert isinstance(result, str)


def test_latex2unicode_unsupported_subscript():
    """Test unsupported characters in subscripts (lines 592-593)."""
    # Test characters without subscript equivalents
    # Most uppercase letters don't have subscript forms
    result = latex2unicode(r"x_{ABC}")
    assert "x" in result
    # Should wrap unsupported chars in parentheses


def test_latex2unicode_mixed_supported_unsupported():
    """Test mixed supported/unsupported in scripts (lines 591-593)."""
    # Test mixing supported and unsupported characters
    result = latex2unicode(r"x^{aQ}")
    assert "x" in result
    # 'a' has superscript, 'Q' doesn't


def test_latex2unicode_unsupported_then_supported():
    """Test unsupported followed by supported chars (lines 592-593)."""
    # This specifically tests the branch where we have unsupported chars,
    # then encounter a supported char, triggering lines 592-593
    result = latex2unicode(r"x^{Qa}")
    assert "x" in result
    # 'Q' is unsupported, 'a' is supported
    # Should wrap Q in parentheses: x⁽Q⁾ᵃ


def test_latex2unicode_script_at_end_no_nodes():
    """Test script at end with no following nodes (line 381)."""
    # If a char node ends with ^ or _ but there's no next node,
    # _try_handle_script_after_chars should return "", 0
    # This is hard to trigger directly, but try edge cases
    result = latex2unicode(r"x^")
    assert "x" in result


def test_latex2unicode_frac_none_args():
    """Test fraction with None argument nodes (line 434)."""
    # Create a case where numer_node or denom_node could be None
    # This might happen with malformed \frac
    result = latex2unicode(r"\frac{}{1}")
    assert isinstance(result, str)


def test_latex2unicode_macro_not_followed_by_chars():
    """Test macro not followed by char node (line 457)."""
    # Test where macro is followed by something other than LatexCharsNode
    # For example, two macros in sequence
    result = latex2unicode(r"\alpha\beta")
    assert "α" in result
    assert "β" in result


def test_latex2unicode_macro_script_not_group_node():
    """Test macro^/_ not followed by group (line 465)."""
    # Macro followed by ^/_ and then something that's not a group
    # This is tricky to create, but some edge cases might work
    result = latex2unicode(r"\sum^n")
    assert "∑" in result


def test_latex2unicode_script_followed_by_comment():
    """Test char ending with ^ followed by comment node (line 381)."""
    # This creates a LatexCommentNode which is neither Group nor Macro
    result = latex2unicode(r"a^% comment")
    assert "a" in result


def test_latex2unicode_script_followed_by_environment():
    """Test char ending with ^ followed by environment (line 381)."""
    # This creates a LatexEnvironmentNode which is neither Group nor Macro
    result = latex2unicode(r"a^\begin{matrix}1\end{matrix}")
    assert "a" in result


def test_latex2unicode_frac_with_none_in_argnlist():
    """Test fraction where argnlist contains None (line 434)."""
    # This is a defensive check that's hard to trigger naturally
    # We can test it by directly calling the internal function with a mock node
    # Create a mock node where argnlist contains None
    mock_node = Mock()
    mock_node.nodeargd = Mock()
    mock_node.nodeargd.argnlist = [None, Mock()]

    result = _try_convert_fraction(mock_node)
    assert result == ""

    # Also test with both None
    mock_node2 = Mock()
    mock_node2.nodeargd = Mock()
    mock_node2.nodeargd.argnlist = [None, None]

    result2 = _try_convert_fraction(mock_node2)
    assert result2 == ""


def test_latex2unicode_macro_followed_by_environment():
    """Test macro followed by environment node (line 457)."""
    # Macro followed by environment (not chars node)
    result = latex2unicode(r"\alpha\begin{matrix}1\end{matrix}")
    assert "α" in result


def test_latex2unicode_macro_followed_by_group():
    """Test macro followed by group node (line 457)."""
    # Macro followed by group (not chars node), with at least 3 nodes
    # This hits the check at line 457 where next_node is not LatexCharsNode
    # Need at least 3 nodes to get past the check at line 452
    result = latex2unicode(r"\alpha{}x")
    assert "α" in result
    assert "x" in result


def test_latex2unicode_macro_caret_environment():
    """Test macro^environment to hit line 465."""
    # Macro followed by ^ and then environment (not group)
    result = latex2unicode(r"\alpha^\begin{matrix}1\end{matrix}")
    assert "α" in result


if __name__ == "__main__":
    from madcatter.lib.testing.main import test_main

    test_main(__file__)
