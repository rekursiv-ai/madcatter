"""Markdown preprocessing utilities shared by mdcat and slackmdcat."""

from __future__ import annotations

import re
import secrets

from madcatter.latex import latex2unicode


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
    in_fenced_block = False
    current_code_block: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            if in_fenced_block:
                current_code_block.append(line)
                result_lines.append(_placeholder(len(protected_blocks)))
                protected_blocks.append("\n".join(current_code_block))
                current_code_block = []
                in_fenced_block = False
            else:
                in_fenced_block = True
                current_code_block = [line]
            continue
        if in_fenced_block:
            current_code_block.append(line)
            continue
        if line.startswith("    "):
            result_lines.append(_placeholder(len(protected_blocks)))
            protected_blocks.append(line)
            continue
        result_lines.append(line)
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
