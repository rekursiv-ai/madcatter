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


@pytest.mark.parametrize(
    ("text", "fragments"),
    [
        ("First $x^2$ and second $y_i$.", ("x²", "yᵢ")),
        ("See `agent_spawn.py` and $x^2$ here.", ("`agent_spawn.py`", "x²")),
        (
            "Cost $7-10.\nSee `self._events` for details.\nBudget $0.42.",
            ("`self._events`",),
        ),
        ("```\n$x^2$ stays literal\n```\nbut $y^2$ converts.", ("$x^2$", "y²")),
        ("Cost $500M; equation $x^2$.", ("$500M", "x²")),
        (
            "Literal <<<CODE_BLOCK_0>>> text.\n```\nx = 1\n```\nand $y^2$ here.",
            ("<<<CODE_BLOCK_0>>>", "x = 1", "y²"),
        ),
        (
            "Intro,\n\n```throughput = min(a, b)```\n\nOutro.\n",
            ("throughput = min(a, b)", "Outro."),
        ),
        ("Intro,\n\n```\nx = 1\ntail line\n", ("x = 1", "tail line")),
    ],
)
def test_process_math_blocks_preserves_fragments(
    text: str,
    fragments: tuple[str, ...],
) -> None:
    result = process_math_blocks(text, enable_math=True)
    for fragment in fragments:
        assert fragment in result


@pytest.mark.parametrize(
    "text",
    [
        "Cost was $90 and refund was\n$10 back.",
        "Series A target ~$500M (shares ~$2.5M).",
    ],
)
def test_process_math_blocks_preserves_currency(text: str) -> None:
    assert process_math_blocks(text, enable_math=True) == text


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["---", "title: hi", "---", "body"], ["body"]),
        (["body", "more"], ["body", "more"]),
        ([], []),
        (
            ["---", "title: hi", "still in frontmatter"],
            ["---", "title: hi", "still in frontmatter"],
        ),
        (["---", "---", "body"], ["body"]),
    ],
)
def test_strip_frontmatter(lines: list[str], expected: list[str]) -> None:
    assert strip_frontmatter(lines) == expected


def test_is_fence_delimiter_rejects_backticks_in_info():
    assert is_fence_delimiter("```language```") is False


def test_is_fence_delimiter_accepts_tilde_info():
    assert is_fence_delimiter("  ~~~language  ") is True


def test_inside_fence_reports_the_state_each_line_starts_in():
    lines = ["a", "```", "b", "```x```", "~~~", "c", "```"]
    flags = [False, False, True, True, True, False, False]
    assert inside_fence(lines) == list(zip(lines, flags, strict=True))
    assert inside_fence([]) == []


def test_normalize_bullets_reads_rendered_bullets_as_list_markers():
    text = " • a\n    • b\n•c\na • b\n```\n• d\n```"
    assert normalize_bullets(text) == " - a\n    - b\n•c\na • b\n```\n• d\n```"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$x^2$", "x²"),
        (
            "before\n```python\n$x^2$\n```\nafter",
            "before\n```python\n$x^2$\n```\nafter",
        ),
        ("    $x^2$\nfollowing $y^2$", "    $x^2$\nfollowing y²"),
        ("before\n~~~\n$x^2$\ntail", "before\n~~~\n$x^2$\ntail"),
        ("`$x^2$` and $y^2$", "`$x^2$` and y²"),
        (
            "`\\1 \\g<0> \\n`\n```\nre.sub(r'\\d', r'\\1', s)\n```",
            "`\\1 \\g<0> \\n`\n```\nre.sub(r'\\d', r'\\1', s)\n```",
        ),
        ("- a\n    - $x^2$\n", "- a\n    - x²\n"),
    ],
)
def test_process_math_blocks_default_exact_output(text: str, expected: str) -> None:
    assert process_math_blocks(text) == expected


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
        ("`\n\n`", [("`\n\n`", False)]),
        ("x```", [("x```", False)]),
        # A longer run that ends the text does not close a shorter opener.
        ("`a ``", [("`a ``", False)]),
        ("`a`", [("`a`", True)]),
        # Only the paragraph holding the opener bounds its span.
        ("a\n\nb `c` d", [("a\n\nb ", False), ("`c`", True), (" d", False)]),
        ("`a\n\nb` c\n\nd", [("`a\n\nb` c\n\nd", False)]),
        # An even run of backslashes escapes nothing; an odd one escapes the opener.
        ("\\\\`a`", [("\\\\", False), ("`a`", True)]),
        ("\\\\\\`a`", [("\\\\\\`a`", False)]),
        ("\\`a`\\", [("\\`a`\\", False)]),
    ],
)
def test_split_code_spans_follows_commonmark_runs(
    text: str,
    pieces: list[tuple[str, bool]],
):
    assert split_code_spans(text) == pieces


def test_code_lines_marks_fenced_indented_and_quoted_code_only():
    text = "p\n```\nx\n```\n\n    y\n- a\n    - b\n> ```\n> z\n> ```"
    flags = [False, True, True, True, False, True, False, False, True, True, True]
    assert code_lines(text) == list(zip(text.split("\n"), flags, strict=True))


def test_process_math_blocks_skips_the_block_parse_without_math(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parses: list[str] = []
    real = markdown.code_lines

    def counting(text: str) -> list[tuple[str, bool]]:
        parses.append(text)
        return real(text)

    monkeypatch.setattr(markdown, "code_lines", counting)
    plain = "Cost $5 and `x` then $10.\n```\nmore $3\n```\n"
    assert process_math_blocks(plain) == plain
    assert parses == []
    assert process_math_blocks("a $x^2$") == "a x²"
    assert parses == ["a $x^2$"]


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
    text = "`a` $x^2$ b\n" * 8 + "```\ncode\n```\n" + "`c` $y_i$\n" * 8
    assert process_math_blocks(text) == (
        "`a` x² b\n" * 8 + "```\ncode\n```\n" + "`c` yᵢ\n" * 8
    )
    assert seen
    assert sum(seen) <= len(text)


if __name__ == "__main__":
    from madcatter.lib.testing.runner import test_main

    test_main(__file__)
