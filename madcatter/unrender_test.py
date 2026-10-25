"""Tests for madcatter.unrender."""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING, Literal, cast

import argparse
import base64
import functools

from rich.console import Console

import pytest

from madcatter.mdcat import (
    Markdown,
    _parse_args,
    render_markdown_file,
    render_plain,
    rewritten,
    strip_trailing_whitespace,
)
from madcatter.unrender import Layout, mark_source, unrender


if TYPE_CHECKING:
    from pathlib import Path


_unrender = functools.partial(unrender, render=render_plain)

# mdcat's ANSI output for every block it can round-trip, as measured with
# TERM=xterm: headings, inline markup, lists, a quote, a rule, a code block.
_RENDERED = "\n".join(
    [
        "\x1b[1;4mH1\x1b[0m",
        "",
        "\x1b[4;35mH2\x1b[0m",
        "",
        "\x1b[1;35mH3\x1b[0m",
        "",
        "\x1b[3;35mH4\x1b[0m",
        "",
        "\x1b[3mH5\x1b[0m",
        "",
        "\x1b[2mH6\x1b[0m",
        "",
        (
            "Plain \x1b[1mbold\x1b[0m and \x1b[3mit\x1b[0m and \x1b[1;36;40mcode\x1b[0m"
            " and \x1b]8;id=1;http://x.y\x1b\\\x1b[4;34mlink\x1b[0m\x1b]8;;\x1b\\ end."
        ),
        "",
        "\x1b[1m • \x1b[0ma",
        "\x1b[1m • \x1b[0mb",
        "\x1b[1m   \x1b[0m\x1b[1m • \x1b[0mnested",
        "",
        "\x1b[36m 1. \x1b[0mone",
        "\x1b[36m 2. \x1b[0mtwo",
        "",
        "\x1b[35m▌ \x1b[0m\x1b[35mquote line\x1b[0m\x1b[35m      \x1b[0m",
        "",
        "\x1b[2m----------\x1b[0m",
        "",
        "\x1b[40m          \x1b[0m",
        (
            "\x1b[40m \x1b[0m\x1b[97;40mx\x1b[0m\x1b[97;40m \x1b[0m\x1b[91;40m=\x1b[0m"
            "\x1b[97;40m \x1b[0m\x1b[37;40m1\x1b[0m\x1b[40m    \x1b[0m"
        ),
        "\x1b[40m          \x1b[0m",
        "",
    ],
)

_MARKDOWN = (
    "# H1\n\n## H2\n\n### H3\n\n#### H4\n\n##### H5\n\n###### H6\n\n"
    "Plain **bold** and *it* and `code` and [link](http://x.y) end.\n\n"
    "- a\n- b\n  - nested\n\n"
    "1. one\n2. two\n\n"
    "> quote line\n\n"
    "---\n\n"
    "```\nx = 1\n```\n"
)

# Round-trips through a real render; adds what _RENDERED does not cover.
_ROUND_TRIP = (
    _MARKDOWN + "\n1. one\n2. two\n\n   para\n   - sub\n3. three\n\n"
    "| name | cell | n |\n|---|:-:|--:|\n| two words | `x` | 10 |\n| a | b | 2 |\n"
)

# Unstyled lines of ANSI output; the leading reset marks the text as rendered.
_RESET = "\x1b[0m"


# Each source loses something in the visible render: wrapping, nesting, escapes,
# styles that collide, or elements Rich does not draw.
_LOSSY = {
    "wrapped heading": "# A heading that is much longer than thirty columns\n",
    "wrapped code": "```py\nx = some_function(argument_one, argument_two)\n```\n",
    "code in list": "1. step\n\n   ```\n   make\n   ```\n",
    "code in quote": "> quote\n>\n> ```\n> x = 1\n> ```\n",
    "list in quote": "> - a\n>   - b\n",
    "escapes": "\\*not italic\\* and \\# x\n\n\\# not heading\n",
    "styled header": "| **a** **b** | c |\n|---|---|\n| 1 | 2 |\n",
    "italic paragraph": "*whole line italic*\n",
    "wrapped cell": "| a | b |\n|:--|---|\n| a long cell that must wrap | 2 |\n",
    "numbered prose": "2024. was a good year\n",
    "image and break": "![alt](http://x/i.png)\n\nline one  \nline two\n",
    "html block": "<div>hi</div>\n",
    "empty and loose items": "- \n- b\n\n- c\n",
    "setext and indented code": "Title\n=====\n\n    code\n",
    "crlf": "# T\r\n\r\n- a\r\n",
    "frontmatter": "---\ntitle: x\n---\n# H\n",
    "math and emoji": "$$x^2$$ :rocket:\n",
    "empty": "",
    "long": "word " * 400 + "\n",
}


def _in_place(tmp_path: Path, source: str, *args: str) -> str:
    """Return what ``mdcat -i`` writes for ``source``."""
    path = tmp_path / "doc.md"
    path.write_bytes(source.encode())
    flags, _ = _parse_args(argparse.ArgumentParser(), ["-i", "-w", "30", *args])
    return rewritten(str(path), flags)


@pytest.mark.parametrize("source", list(_LOSSY.values()), ids=list(_LOSSY))
def test_unrender_restores_in_place_files_exactly(
    source: str,
    tmp_path: Path,
) -> None:
    assert _unrender(_in_place(tmp_path, source)) == source


@pytest.mark.parametrize("args", [["--justify"], ["--pad", "50"], ["--no-math"]])
def test_unrender_restores_files_rendered_with_layout_flags(
    tmp_path: Path,
    args: list[str],
) -> None:
    source = "A paragraph long enough to wrap and justify. $x^2$\n"
    assert _unrender(_in_place(tmp_path, source, *args)) == source


def test_unrender_keeps_edits_made_to_an_in_place_file(tmp_path: Path) -> None:
    rendered = _in_place(tmp_path, "# Title\n\nold words\n")
    assert _unrender(rendered.replace("old", "new")) == "# Title\n\nnew words\n"


def test_unrender_trusts_what_is_shown_over_a_hidden_source() -> None:
    layout = Layout(width=80, justify=False, math=True, frontmatter=True)
    spoof = mark_source("Hidden\n", layout=layout) + "\x1b[1mShown\x1b[0m\n"
    assert _unrender(spoof) == "**Shown**\n"


def test_unrender_of_a_section_returns_only_that_section(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# A\n\napple\n\n# B\n\nbanana\n")
    flags, _ = _parse_args(argparse.ArgumentParser(), ["--section", "B"])
    stream = StringIO()
    render_markdown_file(str(path), Console(file=stream), flags)
    assert _unrender(stream.getvalue()) == "# B\n\nbanana\n"


def _damaged(text: str) -> dict[str, str]:
    """Return ``text``, an in-place render, with its hidden source damaged."""
    start = text.index("base64,") + len("base64,")
    piece = text[start : text.index("\x1b\\", start)]
    return {
        "corrupt base64": text.replace(piece, piece[:-1], 1),
        "invalid utf-8": text.replace(
            piece,
            base64.b64encode(b"\xff\xfe").decode(),
            1,
        ),
        "missing piece": text.replace(piece, base64.b64encode(b"x").decode(), 1),
    }


@pytest.mark.parametrize("damage", ["corrupt base64", "invalid utf-8", "missing piece"])
def test_unrender_reads_the_shown_text_when_the_hidden_source_is_damaged(
    tmp_path: Path,
    damage: str,
) -> None:
    rendered = _in_place(tmp_path, "# Title\n\n- **item**\n")
    assert _unrender(_damaged(rendered)[damage]) == "# Title\n\n- **item**\n"


def test_unrender_drops_a_hidden_source_cut_off_mid_code() -> None:
    layout = Layout(width=80, justify=False, math=True, frontmatter=True)
    marked = mark_source("Hidden\n", layout=layout)
    cut = "\x1b[1mx\x1b[0m\n" + marked[: marked.index("base64,") + 10]
    assert _unrender(cut) == "**x**\n"


def test_unrender_keeps_the_boundary_between_concatenated_files(
    tmp_path: Path,
) -> None:
    first = _in_place(tmp_path, "a")
    second = _in_place(tmp_path, "b\n")
    assert _unrender(first + second) == "a\n\nb\n"
    assert _unrender(_in_place(tmp_path, "a\n\n\n") + second) == "a\n\n\nb\n"
    assert _unrender("\x1b[1mlead\x1b[0m\n" + second) == "**lead**\n\nb\n"


def test_unrender_leaves_text_without_escape_codes_unchanged() -> None:
    markdown = "\n\nline  \nbreak\n\n----\n\n • a\n▌ q\n────\n"
    assert _unrender(markdown) == markdown
    assert _unrender(_unrender(markdown)) == markdown


def test_mark_source_splits_long_sources_and_round_trips_unicode() -> None:
    source = "é🚀\n" * 400
    layout = Layout(width=80, justify=False, math=True, frontmatter=True)
    marked = mark_source(source, layout=layout)
    assert marked.count("\x1b]8;;\x1b\\") == 2
    assert all(len(code) < 2083 for code in marked.split("\x1b\\"))
    assert _unrender(marked + render_plain(source, layout)) == source
    assert mark_source("", layout=layout).count("\x1b]8;;\x1b\\") == 1


def test_unrender_keeps_list_nesting_inside_unstyled_quotes() -> None:
    rendered = _RESET + "▌  • a\n▌     • b\n▌ text\n"
    assert _unrender(rendered) == "> - a\n>   - b\n> text\n"


def test_unrender_restores_every_ansi_block() -> None:
    assert _unrender(_RENDERED) == _MARKDOWN


def test_unrender_reads_256_and_truecolor_code_blocks() -> None:
    rendered = (
        "\x1b[48;2;39;40;34m      \x1b[0m\n"
        "\x1b[48;2;39;40;34m \x1b[0m\x1b[38;2;248;248;242;48;2;39;40;34mx\x1b[0m"
        "\x1b[38;5;231;48;5;235m = \x1b[0m\x1b[100my\x1b[0m\n"
        "\x1b[48;5;235m      \x1b[0m\n"
    )
    assert _unrender(rendered) == "```\nx = y\n```\n"


def test_unrender_keeps_blank_lines_inside_a_code_block() -> None:
    rendered = "\x1b[40m    \x1b[0m\n\x1b[40m a\x1b[0m\n\x1b[40m    \x1b[0m\n\x1b[40m b\x1b[0m\n"
    assert _unrender(rendered) == "```\na\n\nb\n```\n"


@pytest.mark.parametrize("color_system", ["standard", "256", "truecolor"])
def test_unrender_inverts_mdcat_rendering(color_system: str) -> None:
    stream = StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=cast(Literal["standard", "256", "truecolor"], color_system),
        width=40,
    )
    console.print(Markdown(_ROUND_TRIP))
    rendered = strip_trailing_whitespace(stream.getvalue())
    assert _unrender(rendered) == _ROUND_TRIP


def test_unrender_recovers_markers_from_unstyled_lines() -> None:
    rendered = (
        _RESET + " • a\n    • b\n• c\n▌ q\n▌ ▌ deep\n────\n 1. x\n 10. y\nplain\n"
    )
    assert (
        _unrender(rendered)
        == "- a\n  - b\n- c\n> q\n> > deep\n---\n1. x\n10. y\nplain\n"
    )


def test_unrender_rebuilds_a_table_with_alignment_and_escaped_pipes() -> None:
    rendered = "\n".join(
        [
            "\x1b[36m             \x1b[0m",
            (
                "\x1b[36m \x1b[0m\x1b[36mh\x1b[0m\x1b[1m   \x1b[0m\x1b[36m \x1b[0m"
                "\x1b[36mmid\x1b[0m\x1b[36m \x1b[0m\x1b[1m  \x1b[0m\x1b[36mr\x1b[0m"
                "\x1b[36m \x1b[0m"
            ),
            "\x1b[36m ──────────── \x1b[0m",
            "\x1b[36m \x1b[0ma|b\x1b[36m \x1b[0m x \x1b[36m \x1b[0m  1\x1b[36m \x1b[0m",
            (
                "\x1b[36m \x1b[0m\x1b[1mc\x1b[0m   \x1b[36m \x1b[0m   \x1b[36m \x1b[0m 22"
                "\x1b[36m \x1b[0m"
            ),
            "\x1b[36m             \x1b[0m",
            "after",
        ],
    )
    assert _unrender(rendered) == (
        "| h | mid | r |\n|---|:-:|--:|\n| a\\|b | x | 1 |\n| **c** |  | 22 |\nafter"
    )


def test_unrender_leaves_a_lone_cyan_line_alone() -> None:
    assert _unrender("a\n\x1b[36m    \x1b[0m\nx") == "a\n\nx"


def test_unrender_leaves_markdown_source_unchanged() -> None:
    source = "# T\n\n- a\n  - b\n\n1. one\n\n> q\n\n```py\nx = 1\n```\n"
    assert _unrender(source) == source


def test_unrender_passes_fenced_source_through_verbatim() -> None:
    rendered = _RESET + "```\n • kept\n ▌ kept\n```\n • a\n```\n----\n```\n▌ q"
    assert _unrender(rendered) == "```\n • kept\n ▌ kept\n```\n- a\n```\n----\n```\n> q"


def test_unrender_drops_only_leading_newlines() -> None:
    assert _unrender(_RESET + "\n\n  x\n") == "  x\n"
    assert _unrender(_RESET + "XX") == "XX"


def test_unrender_moves_spaces_outside_emphasis_and_merges_spans() -> None:
    rendered = (
        "a\x1b[1;3m both \x1b[0m\x1b[9mgone\x1b[0m"
        "\x1b[1m \x1b[0m\x1b[1mx\x1b[0m\x1b[1my\x1b[0m"
    )
    assert _unrender(rendered) == "a ***both*** ~~gone~~ **xy**"


def test_unrender_strips_heading_style_from_inline_spans() -> None:
    assert _unrender("\x1b[1;4mH \x1b[0m\x1b[1;4;36;40mx\x1b[0m") == "# H `x`"


def test_unrender_keeps_markup_inside_quotes_and_list_items() -> None:
    rendered = (
        "\x1b[35m▌ \x1b[0m\x1b[1;35mloud\x1b[0m\n"
        "\x1b[1m • \x1b[0m\x1b[1mitem\x1b[0m\n"
        "\x1b[35m▌ \x1b[0m\n"
    )
    assert _unrender(rendered) == "> **loud**\n- **item**\n>\n"


def test_unrender_drops_other_escapes_and_honors_bare_reset() -> None:
    rendered = "\x1b]0;title\x07\x1b[2K\x1b[1mx\x1b[my\x1b[5mz\x1b[0m"
    assert _unrender(rendered) == "**x**yz"


def test_unrender_reads_link_text_markup() -> None:
    rendered = "\x1b]8;id=2;u\x07\x1b[1;4;34mb\x1b[0m\x1b[4;34m c\x1b[0m\x1b]8;;\x07"
    assert _unrender(rendered) == "[**b** c](u)"


if __name__ == "__main__":
    from madcatter.lib.testing.runner import test_main

    test_main(__file__)
