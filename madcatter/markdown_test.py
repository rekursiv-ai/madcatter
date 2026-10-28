"""Tests for madcatter.markdown."""

from __future__ import annotations

import pytest

from madcatter import markdown
from madcatter.markdown import (
    code_lines,
    inside_fence,
    is_fence_delimiter,
    normalize_bullets,
    process_math_blocks,
    split_code_spans,
    strip_frontmatter,
)


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


def test_process_math_blocks_single_line_fence_span_survives():
    """A one-line ```code``` span is not a fence opener; content must survive."""
    text = "Intro,\n\n```throughput = min(a, b)```\n\nOutro.\n"
    result = process_math_blocks(text, enable_math=True)
    assert "throughput = min(a, b)" in result
    assert "Outro." in result


def test_process_math_blocks_unterminated_fence_survives():
    """An unclosed fence must still emit its content, not swallow the tail."""
    text = "Intro,\n\n```\nx = 1\ntail line\n"
    result = process_math_blocks(text, enable_math=True)
    assert "x = 1" in result
    assert "tail line" in result


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


def test_is_fence_delimiter_rejects_backticks_in_info():
    assert is_fence_delimiter("```language```") is False


def test_is_fence_delimiter_accepts_tilde_info():
    assert is_fence_delimiter("  ~~~language  ") is True


def test_inside_fence_reports_the_state_each_line_starts_in():
    lines = ["a", "```", "b", "```x```", "~~~", "c", "```"]
    assert inside_fence(lines) == [False, False, True, True, True, False, False]
    assert inside_fence([]) == []


def test_normalize_bullets_reads_rendered_bullets_as_list_markers():
    text = " • a\n    • b\n•c\na • b\n```\n• d\n```"
    assert normalize_bullets(text) == " - a\n    - b\n•c\na • b\n```\n• d\n```"


def test_process_math_blocks_default_enables_conversion():
    assert process_math_blocks("$x^2$") == "x²"


def test_process_math_blocks_preserves_fenced_block_exactly():
    text = "before\n```python\n$x^2$\n```\nafter"
    assert process_math_blocks(text) == text


def test_process_math_blocks_preserves_indented_code_before_following_math():
    text = "    $x^2$\nfollowing $y^2$"
    assert process_math_blocks(text) == "    $x^2$\nfollowing y²"


def test_process_math_blocks_preserves_unterminated_fence_exactly():
    text = "before\n~~~\n$x^2$\ntail"
    assert process_math_blocks(text) == text


def test_process_math_blocks_preserves_math_inside_inline_code():
    text = "`$x^2$` and $y^2$"
    assert process_math_blocks(text) == "`$x^2$` and y²"


def test_process_math_blocks_restores_backslashes_in_code_verbatim():
    text = "`\\1 \\g<0> \\n`\n```\nre.sub(r'\\d', r'\\1', s)\n```"
    assert process_math_blocks(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Cost $5 and `x` then $10.",
        "Price $5 `a_b` $7",
        "$$\na\n```\ncode\n```\nb\n$$",
        "$x `$` y^2$",
        "\t$x^2$\n",
        "> ```\n> $x^2$\n> ```\n",
    ],
)
def test_process_math_blocks_never_reads_math_across_or_inside_code(text: str):
    assert process_math_blocks(text) == text


@pytest.mark.parametrize(
    ("text", "pieces"),
    [
        ("a `b` c", [("a ", False), ("`b`", True), (" c", False)]),
        ("``x ` y`` z", [("``x ` y``", True), (" z", False)]),
        ("`a``b` `", [("`a``b`", True), (" `", False)]),
        ("\\`a` `b`", [("\\`a", False), ("` `", True), ("b`", False)]),
        ("`a\n\nb`", [("`a\n\nb`", False)]),
        ("x```", [("x```", False)]),
    ],
)
def test_split_code_spans_follows_commonmark_runs(
    text: str,
    pieces: list[tuple[str, bool]],
):
    assert split_code_spans(text) == pieces


def test_code_lines_marks_fenced_indented_and_quoted_code_only():
    text = "p\n```\nx\n```\n\n    y\n- a\n    - b\n> ```\n> z\n> ```"
    assert code_lines(text) == [
        False,
        True,
        True,
        True,
        False,
        True,
        False,
        False,
        True,
        True,
        True,
    ]


def test_process_math_blocks_skips_the_block_parse_without_math(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parses: list[str] = []
    real = markdown.code_lines

    def counting(text: str) -> list[bool]:
        parses.append(text)
        return real(text)

    monkeypatch.setattr(markdown, "code_lines", counting)
    plain = "Cost $5 and `x` then $10.\n```\nmore $3\n```\n"
    assert process_math_blocks(plain) == plain
    assert parses == []
    assert process_math_blocks("a $x^2$") == "a x²"
    assert parses == ["a $x^2$"]


def test_process_math_blocks_converts_math_in_a_nested_list_item():
    assert process_math_blocks("- a\n    - $x^2$\n") == "- a\n    - x²\n"


def test_process_math_blocks_reads_each_character_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-span rescan of the document made a 1.9 MB file take 8 s."""
    seen: list[int] = []
    convert = markdown._math_to_unicode

    def counting(text: str) -> str:
        seen.append(len(text))
        return convert(text)

    monkeypatch.setattr(markdown, "_math_to_unicode", counting)
    text = "`a` $x^2$ b\n" * 2_000 + "```\ncode\n```\n" + "`c` $y_i$\n" * 2_000
    process_math_blocks(text)
    assert sum(seen) <= len(text)


def test_strip_frontmatter_closes_at_first_possible_line():
    assert strip_frontmatter(["---", "---", "body"]) == ["body"]


if __name__ == "__main__":
    from madcatter.lib.testing.runner import test_main

    test_main(__file__)
