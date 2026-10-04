"""Markdown preprocessing utilities shared by mdcat and slackmdcat."""

from __future__ import annotations

import re
import secrets

from madcatter.latex import latex2unicode


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


def process_math_blocks(markdown_body: str, enable_math: bool = True) -> str:
    """Convert LaTeX math in markdown to Unicode, leaving code blocks intact.

    Replaces ``$...$`` (inline) and ``$$...$$`` (block) with the Unicode
    rendering produced by ``latex2unicode``. Fenced code blocks, indented
    code blocks, and inline backtick spans are protected so currency
    signs and underscores inside them survive unchanged.

    Args:
      markdown_body: Raw markdown source.
      enable_math: When False, the body is returned unchanged.

    Returns:
      processed: Markdown with math expressions replaced by Unicode.

    """
    if not enable_math:
        return markdown_body
    # Per-call random nonce makes placeholders collision-resistant: literal
    # "<<<CODE_BLOCK_0>>>" text in the source can no longer be mistaken for a
    # protection sentinel (issue CORE-005).
    nonce = secrets.token_hex(8)
    protected_blocks: list[str] = []

    def _placeholder(index: int) -> str:
        return f"\x00CODE_BLOCK_{nonce}_{index}\x00"

    lines = markdown_body.split("\n")
    result_lines: list[str] = []
    current_code_block: list[str] = markdown_body.splitlines()[:0]
    current_code_block.extend(())
    for line in lines:
        if is_fence_delimiter(line):
            if current_code_block:
                current_code_block.append(line)
                result_lines.append(_placeholder(len(protected_blocks)))
                protected_blocks.append("\n".join(current_code_block))
                current_code_block.clear()
            else:
                current_code_block = [line]
            continue
        if current_code_block:
            current_code_block.append(line)
            continue
        if line.startswith("    "):
            result_lines.append(_placeholder(len(protected_blocks)))
            protected_blocks.append(line)
            continue
        result_lines.append(line)
    if current_code_block:
        # Unterminated fence: emit the buffer rather than discarding the tail.
        result_lines.append(_placeholder(len(protected_blocks)))
        protected_blocks.append("\n".join(current_code_block))
    text = "\n".join(result_lines)

    def _protect_inline_code(match: re.Match[str]) -> str:
        placeholder = _placeholder(len(protected_blocks))
        protected_blocks.append(match.group(0))
        return placeholder

    text = re.sub(r"`[^`\n]+`", _protect_inline_code, text)
    text = re.sub(
        r"\$\$(.*?)\$\$",
        lambda m: f"\n{latex2unicode(m.group(1))}\n",
        text,
        flags=re.DOTALL,
    )
    # ``[^\$\n]`` prevents pairing currency across lines (``$90 ... $10``); the
    # required ``[\\^_{}]`` marker prevents same-line currency pairing
    # (``$500M ... $2.5M``) and ensures the regex skips currency spans
    # entirely so a later real-math ``$`` pair on the same line still matches.
    text = re.sub(
        r"\$([^\$\n]*[\\^_{}][^\$\n]*)\$",
        lambda m: latex2unicode(m.group(1)),
        text,
    )
    for i, block in enumerate(protected_blocks):
        text = text.replace(_placeholder(i), block)
    return text


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
