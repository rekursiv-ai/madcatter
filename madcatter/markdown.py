"""Markdown preprocessing utilities shared by mdcat and slackmdcat."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import functools
import itertools
import re

from markdown_it import MarkdownIt

from madcatter.latex import latex2unicode


if TYPE_CHECKING:
    from collections.abc import Callable


_DISPLAY_MATH: Final = re.compile(r"\$\$(.*?)\$\$", flags=re.DOTALL)
# ``[^\$\n]`` prevents pairing currency across lines (``$90 ... $10``); the
# required ``[\\^_{}]`` marker prevents same-line currency pairing
# (``$500M ... $2.5M``) and ensures the regex skips currency spans
# entirely so a later real-math ``$`` pair on the same line still matches.
_INLINE_MATH: Final = re.compile(r"\$([^\$\n]*[\\^_{}][^\$\n]*)\$")


def is_fence_delimiter(line: str) -> bool:
    """Report whether a line opens or closes a fenced code block.

    A single-line span such as ```` ```x = 1``` ```` is NOT a fence: CommonMark
    forbids backticks in a fence info string, so the span is inline code.
    Toggling fence state on it swallows the rest of the document.

    Args:
      line: One source line, with or without surrounding whitespace.

    Returns:
      is_delimiter: True when the line is a real fence open/close marker.

    """
    match = re.match(r"^(`{3,}|~{3,})(.*)$", line.strip())
    if match is None:
        return False
    return "`" not in match.group(2)


def inside_fence(lines: list[str]) -> list[bool]:
    """Report, per line, whether the fence delimiters above it leave it in code.

    One pass carries the state forward. Recounting the delimiters above each
    line instead made a 32,000-line document take over a minute.

    Args:
      lines: Source lines, in order.

    Returns:
      inside: One flag per line, True when an odd number of fence delimiters
        precede it. A delimiter line reports the state before it.

    """
    inside: list[bool] = []
    state = False
    for line in lines:
        inside.append(state)
        state ^= is_fence_delimiter(line)
    return inside


def normalize_bullets(text: str) -> str:
    """Read a leading ``•`` as a ``-`` list marker, outside code fences.

    mdcat renders list markers as ``•``, so this makes rendering its own
    output a fixed point.

    Args:
      text: Markdown source.

    Returns:
      normalized: ``text`` with each line-leading ``• `` rewritten to ``- ``.

    """
    lines = text.split("\n")
    return "\n".join(
        line if fenced else re.sub(r"^(\s*)•(?=\s)", r"\1-", line)
        for line, fenced in zip(lines, inside_fence(lines), strict=True)
    )


def process_math_blocks(markdown_body: str, enable_math: bool = True) -> str:
    """Convert LaTeX math in markdown to Unicode, leaving code blocks intact.

    Replaces ``$...$`` (inline) and ``$$...$$`` (block) with the Unicode
    rendering produced by ``latex2unicode``. Code blocks, as markdown parses
    them, and inline code spans are left as they are, and math is never read
    across them, so currency signs and underscores in code survive unchanged.

    Args:
      markdown_body: Raw markdown source.
      enable_math: When False, the body is returned unchanged.

    Returns:
      processed: Markdown with math expressions replaced by Unicode.

    """
    # Neither pattern matching the whole body means none matches any part of it,
    # so the block parse (0.3 s on 2 MB) can be skipped.
    if not enable_math or not (
        _DISPLAY_MATH.search(markdown_body) or _INLINE_MATH.search(markdown_body)
    ):
        return markdown_body
    return map_prose(markdown_body, _math_to_unicode)


def map_prose(markdown_body: str, convert: Callable[[str], str]) -> str:
    """Apply ``convert`` to the prose of ``markdown_body``, leaving code as is.

    Code blocks and inline code spans pass through unchanged, and ``convert``
    sees each stretch of prose between them once, so it never matches across
    code.

    Args:
      markdown_body: Markdown source.
      convert: Rewrites one stretch of prose.

    Returns:
      converted: ``markdown_body`` with every stretch of prose converted.

    """
    lines = markdown_body.split("\n")
    out: list[str] = []
    for in_code, group in itertools.groupby(
        zip(lines, code_lines(markdown_body), strict=True),
        key=lambda pair: pair[1],
    ):
        chunk = "\n".join(line for line, _ in group)
        out.append(
            chunk
            if in_code
            else "".join(
                piece if is_code else convert(piece)
                for piece, is_code in split_code_spans(chunk)
            ),
        )
    return "\n".join(out)


def code_lines(markdown_body: str) -> list[bool]:
    r"""Report, per line, whether markdown parses it as part of a code block.

    Fenced blocks (closed or not) and indented blocks count, wherever they
    nest; a list item's indented continuation does not.

    Args:
      markdown_body: Markdown source.

    Returns:
      in_code: One flag per ``markdown_body.split("\\n")`` line.

    """
    in_code = [False] * (markdown_body.count("\n") + 1)
    for token in _block_parser().parse(markdown_body):
        if token.type in {"fence", "code_block"} and token.map is not None:
            start, end = token.map
            in_code[start:end] = [True] * (end - start)
    return in_code


def split_code_spans(text: str) -> list[tuple[str, bool]]:
    """Split text into prose and inline code spans, by CommonMark's rule.

    A run of N backticks opens a span that the next run of exactly N closes,
    within one paragraph; an unclosed run is literal text.

    Args:
      text: Markdown text outside code blocks.

    Returns:
      pieces: ``(piece, is_code)`` pairs that concatenate back to ``text``.

    """
    pieces: list[tuple[str, bool]] = []
    # ``limit`` is the end of the paragraph holding ``pos``; spans never cross it.
    start = pos = limit = 0
    while (opener := text.find("`", pos)) >= 0:
        run_end = opener
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        pos = run_end
        if run_end > limit:
            blank = text.find("\n\n", run_end)
            limit = len(text) if blank < 0 else blank
        close = _closing_run(text, run_end, run_end - opener, limit)
        if close < 0 or _escaped(text, opener):
            continue
        if opener > start:
            pieces.append((text[start:opener], False))
        start = pos = close
        pieces.append((text[opener:close], True))
    if start < len(text):
        pieces.append((text[start:], False))
    return pieces


def strip_frontmatter(lines: list[str]) -> list[str]:
    """Drop a leading YAML frontmatter block delimited by ``---`` markers.

    Args:
      lines: Source lines, without trailing newlines.

    Returns:
      remaining: Lines after the closing ``---``, or the input if no
        frontmatter is present.

    """
    if not lines or lines[0].strip() != "---":
        return lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[i + 1 :]
    return lines


def _closing_run(text: str, pos: int, width: int, limit: int) -> int:
    """Return the end of the first run of exactly ``width`` backticks, or -1."""
    while (found := text.find("`" * width, pos, limit)) >= 0:
        end = found + width
        if end == len(text) or text[end] != "`":
            return end
        pos = end
        while pos < limit and text[pos] == "`":
            pos += 1
    return -1


def _escaped(text: str, index: int) -> bool:
    """Report whether an odd run of backslashes precedes ``text[index]``."""
    slashes = 0
    while slashes < index and text[index - slashes - 1] == "\\":
        slashes += 1
    return slashes % 2 == 1


def _math_to_unicode(text: str) -> str:
    """Convert ``$$...$$`` and ``$...$`` math in prose that holds no code."""
    text = _DISPLAY_MATH.sub(lambda m: f"\n{latex2unicode(m.group(1))}\n", text)
    return _INLINE_MATH.sub(lambda m: latex2unicode(m.group(1)), text)


@functools.cache
def _block_parser() -> MarkdownIt:
    # Block structure is all code_lines needs; inline parsing doubles the cost.
    return MarkdownIt("commonmark").disable("inline")
