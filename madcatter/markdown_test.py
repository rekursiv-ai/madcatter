"""Tests for madcatter.markdown."""

from __future__ import annotations

import pytest

from madcatter.markdown import process_math_blocks, strip_frontmatter


def test_process_math_blocks_inline():
    text = "The equation $e^{i\\pi} + 1 = 0$ is beautiful."
    result = process_math_blocks(text, enable_math=True)
    assert "eⁱ⁽π⁾" in result or "eⁱπ" in result
    assert "$" not in result


def test_process_math_blocks_block():
    text = "Some text.\n\n$$\n\\sum_{i=1}^n x_i^2\n$$\n\nMore text.\n"
    result = process_math_blocks(text, enable_math=True)
    assert "∑ᵢ₌₁ⁿ xᵢ²" in result
    assert "$$" not in result


def test_process_math_blocks_disabled():
    text = "Math: $x^2 + y^2$"
    assert process_math_blocks(text, enable_math=False) == text


def test_process_math_blocks_multiple_inline():
    text = "First $x^2$ and second $y_i$."
    result = process_math_blocks(text, enable_math=True)
    assert "x²" in result
    assert "yᵢ" in result


def test_process_math_blocks_currency_not_treated_as_math():
    """Currency $N on different lines must not pair as math delimiters."""
    text = "Cost was $90 and refund was\n$10 back."
    assert process_math_blocks(text, enable_math=True) == text


def test_process_math_blocks_inline_code_protected():
    """Backtick code spans must survive math processing unchanged."""
    text = "See `agent_spawn.py` and $x^2$ here."
    result = process_math_blocks(text, enable_math=True)
    assert "`agent_spawn.py`" in result
    assert "x²" in result


def test_process_math_blocks_inline_code_with_currency():
    """Inline code with underscores between currency signs stays intact."""
    text = "Cost $7-10.\nSee `self._events` for details.\nBudget $0.42."
    result = process_math_blocks(text, enable_math=True)
    assert "`self._events`" in result


def test_process_math_blocks_fenced_code_protected():
    text = "```\n$x^2$ stays literal\n```\nbut $y^2$ converts."
    result = process_math_blocks(text, enable_math=True)
    assert "$x^2$" in result
    assert "y²" in result


def test_process_math_blocks_same_line_currency_not_paired():
    """Same-line ``$N ... $M`` currency pairs must not be treated as math."""
    text = "Series A target ~$500M (shares ~$2.5M)."
    assert process_math_blocks(text, enable_math=True) == text


def test_process_math_blocks_currency_then_real_math():
    text = "Cost $500M; equation $x^2$."
    result = process_math_blocks(text, enable_math=True)
    assert "$500M" in result
    assert "x²" in result


def test_process_math_blocks_literal_placeholder_survives():
    """Literal placeholder text in source must not collide with sentinels."""
    text = "Literal <<<CODE_BLOCK_0>>> text.\n```\nx = 1\n```\nand $y^2$ here."
    result = process_math_blocks(text, enable_math=True)
    assert "<<<CODE_BLOCK_0>>>" in result
    assert "x = 1" in result
    assert "y²" in result


def test_strip_frontmatter_present():
    lines = ["---", "title: hi", "---", "body"]
    assert strip_frontmatter(lines) == ["body"]


def test_strip_frontmatter_absent():
    lines = ["body", "more"]
    assert strip_frontmatter(lines) == lines


def test_strip_frontmatter_empty():
    assert strip_frontmatter([]) == []


def test_strip_frontmatter_unterminated():
    lines = ["---", "title: hi", "still in frontmatter"]
    assert strip_frontmatter(lines) == lines


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
