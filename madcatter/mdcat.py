"""Render Markdown to the console with Rich.

Custom markdown renderer that left-justifies headings instead of centering.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Final, NoReturn, Protocol, cast, override
from urllib.parse import urlparse

import argparse
import collections
import difflib
import hashlib
import io
import os
import pydoc
import re
import sys
import time
import unicodedata

from markdown_it import MarkdownIt
from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import (
    Heading,
    Markdown as MarkdownBase,
    MarkdownElement,
)
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

import requests

from madcatter.emoji import resolve
from madcatter.markdown import (
    is_fence_delimiter,
    process_math_blocks,
    strip_frontmatter,
)


class _Flags(Protocol):
    path: list[str]
    force_color: bool | None
    ascii: bool
    code_theme: str
    inline_code_lexer: str | None
    hyperlinks: bool
    width: int | None
    pad: int | None
    justify: bool
    page: bool
    separator: bool
    toc: bool
    links: bool
    check_links: bool
    code_only: bool
    code_lang: str | None
    style: str | None
    export_html: str | None
    export_ansi: str | None
    watch: bool
    follow: bool
    follow_lines: int
    no_frontmatter: bool
    section: str | None
    diff: str | None
    math: bool


# Unicode to ASCII translation for printable output.
_UNICODE_TO_ASCII_CHARS = str.maketrans(
    {
        "\u2501": "-",
        "\u2500": "-",
        "\u2502": "|",
        "\u2503": "|",  # Box drawing.
        "\u250c": "+",
        "\u2510": "+",
        "\u2514": "+",
        "\u2518": "+",
        "\u251c": "+",
        "\u2524": "+",
        "\u252c": "+",
        "\u2534": "+",
        "\u253c": "+",
        "\u2022": "*",
        "\u00b7": ".",
        "\u2013": "-",  # Bullet, middle dot, en-dash.
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',  # Curly quotes.
        "\u00d7": "x",
        "\u00f7": "/",  # Multiply, divide.
    },
)


def to_ascii(text: str) -> str:
    """Convert Unicode text to ASCII.

    Args:
      text: Unicode string to transform.

    Returns:
      result: ASCII-safe string with box-drawing, quotes, and math substituted.

    """
    text = text.translate(_UNICODE_TO_ASCII_CHARS)
    for uni, asc in (
        ("…", "..."),
        ("--", "--"),
        ("±", "+/-"),
        ("→", "->"),
        ("←", "<-"),
        ("↔", "<->"),
        ("≤", "<="),
        ("≥", ">="),
        ("≠", "!="),
        ("≈", "~="),
        ("📑", "[TOC]"),
    ):
        text = text.replace(uni, asc)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def strip_trailing_whitespace(text: str) -> str:
    """Strip trailing whitespace from each line.

    Args:
      text: Text.

    Returns:
      result: The str.

    """
    return "\n".join(line.rstrip() for line in text.split("\n"))


class LeftJustifiedHeading(Heading):
    """Heading element that left-justifies instead of centering."""

    @override
    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        """Render heading with left justification."""
        yield from console.render(self.text, options=options.update(justify="left"))


class Markdown(MarkdownBase):
    """Markdown renderer with left-justified headings."""

    elements: ClassVar[dict[str, type[MarkdownElement]]] = {
        **MarkdownBase.elements,
        "heading_open": LeftJustifiedHeading,
    }


def process_emoji(text: str) -> str:
    """Replace :shortcode: with Unicode emoji, skipping code blocks.

    Args:
      text: Markdown text to process.

    Returns:
      result: Markdown with :shortcode: expanded to emoji outside fenced code.

    """

    def _replace(match: re.Match[str]) -> str:
        resolved = resolve(match.group(1))
        return resolved if resolved is not None else match.group(0)

    lines = text.split("\n")
    result: list[str] = []
    in_fence = False
    for line in lines:
        if is_fence_delimiter(line):
            in_fence = not in_fence
            result.append(line)
        elif in_fence or line.startswith("    "):
            result.append(line)
        else:
            result.append(re.sub(r":([a-z0-9_+\-]+):", _replace, line))
    return "\n".join(result)


# Style profiles.
STYLE_PROFILES: Final = {
    "dark": {
        "code_theme": "monokai",
        "background": "black",
    },
    "light": {
        "code_theme": "default",
        "background": "white",
    },
    "dracula": {
        "code_theme": "dracula",
        "background": "black",
    },
    "solarized": {
        "code_theme": "solarized-dark",
        "background": "black",
    },
}


def extract_headings(markdown_body: str) -> list[tuple[int, str]]:
    """Extract headings from markdown with their levels.

    Args:
      markdown_body: Markdown text to parse.

    Returns:
      headings: (level, title) pairs, 1-6 for H1-H6, extracted from code-block-aware scan.

    """
    headings: list[tuple[int, str]] = []
    in_code_block = False

    for line in markdown_body.split("\n"):
        # Track code block boundaries.
        if is_fence_delimiter(line):
            in_code_block = not in_code_block
            continue

        # Skip lines inside code blocks.
        if in_code_block:
            continue

        if match := re.match(r"^(#{1,6})\s+(.+)$", line):
            level = len(match.group(1))
            title = match.group(2).strip()
            headings.append((level, title))
    return headings


def render_toc(headings: list[tuple[int, str]], console: Console) -> None:
    """Render table of contents as a tree.

    Args:
      headings: (level, title) pairs to display.
      console: Rich Console to write the tree to.

    """
    tree = Tree("📑 Table of Contents", guide_style="dim")
    stack: list[tuple[int, Tree]] = [(0, tree)]

    for level, title in headings:
        # Pop from stack until we find the parent level.
        while stack and stack[-1][0] >= level:
            stack.pop()

        # Add node under current parent.
        parent_tree = stack[-1][1] if stack else tree
        node = parent_tree.add(f"[bold]{title}[/bold]")
        stack.append((level, node))

    console.print(tree)
    console.print()


def extract_links(markdown_body: str) -> list[str]:
    """Extract all URLs from markdown.

    Args:
      markdown_body: Markdown text to parse.

    Returns:
      links: Unique href and src URLs found in links and images.

    """
    md = MarkdownIt()
    tokens = md.parse(markdown_body)

    links: list[str] = []
    for token in tokens:
        if token.type == "link_open":
            href = token.attrGet("href")
            if href and isinstance(href, str):
                links.append(href)
        elif token.type == "image":
            src = token.attrGet("src")
            if src and isinstance(src, str):
                links.append(src)

    return links


def check_links(links: list[str], console: Console) -> None:
    """Check if URLs are reachable.

    Args:
      links: URL strings to validate via HTTP HEAD.
      console: Rich Console to write results to.

    """
    table = Table(title="Link Validation", show_header=True)
    table.add_column("URL", style="cyan")
    table.add_column("Status", style="green")

    for link in links:
        # Skip relative/anchor links.
        parsed = urlparse(link)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            table.add_row(link, "[dim]skipped (not http/s)[/dim]")
            continue

        try:
            response = requests.head(link, timeout=5, allow_redirects=True)
            if response.status_code < 400:
                table.add_row(link, f"[green]✓ {response.status_code}[/green]")
            else:
                table.add_row(link, f"[red]✗ {response.status_code}[/red]")
        except requests.RequestException as e:
            table.add_row(link, f"[red]✗ {type(e).__name__}[/red]")

    console.print(table)


def extract_code_blocks(
    markdown_body: str,
    language_filter: str | None = None,
) -> list[tuple[str | None, str]]:
    """Extract code blocks from markdown.

    Args:
      markdown_body: Markdown text to parse.
      language_filter: If given, return only blocks with this language tag.

    Returns:
      code_blocks: (language, code) tuples for fenced blocks matching the filter.

    """
    md = MarkdownIt()
    tokens = md.parse(markdown_body)

    code_blocks: list[tuple[str | None, str]] = []
    for token in tokens:
        if token.type == "fence":
            lang = token.info.strip() if token.info else None
            code = token.content

            if language_filter is None or lang == language_filter:
                code_blocks.append((lang, code))

    return code_blocks


def render_code_blocks(
    code_blocks: list[tuple[str | None, str]],
    console: Console,
) -> None:
    """Render code blocks.

    Args:
      code_blocks: Code blocks.
      console: Console.

    """
    for i, (lang, code) in enumerate(code_blocks):
        if i > 0:
            console.print()
        title = f"Code Block {i + 1}" + (f" ({lang})" if lang else "")
        console.print(Panel(Syntax(code, lang or "text", theme="monokai"), title=title))


def filter_section(markdown_body: str, section_name: str) -> str:
    """Extract a specific section from markdown.

    Args:
      markdown_body: Markdown text to parse.
      section_name: Heading text to match (case-insensitive).

    Returns:
      result: Lines from the matched heading down to the next same-or-higher level.

    """
    lines = markdown_body.split("\n")
    section_lines: list[str] = []
    in_section = False
    section_level = 0

    for line in lines:
        if match := re.match(r"^(#{1,6})\s+(.+)$", line):
            level = len(match.group(1))
            title = match.group(2).strip()

            if title.lower() == section_name.lower():
                in_section = True
                section_level = level
                section_lines.append(line)
            elif in_section and level <= section_level:
                # Hit a same-or-higher level heading, end of section.
                break
            elif in_section:
                section_lines.append(line)
        elif in_section:
            section_lines.append(line)

    return "\n".join(section_lines)


def render_diff(file1: str, file2: str, console: Console) -> None:
    """Render diff between two markdown files.

    Args:
      file1: Path to the first file.
      file2: Path to the second file.
      console: Rich Console to write colored diff to.

    """
    with (
        Path(file1).open(encoding="utf-8") as f1,
        Path(file2).open(encoding="utf-8") as f2,
    ):
        lines1 = f1.readlines()
        lines2 = f2.readlines()

    diff = difflib.unified_diff(lines1, lines2, fromfile=file1, tofile=file2)

    for diff_line in diff:
        stripped = diff_line.rstrip()
        if stripped.startswith(("+++", "---")):
            console.print(stripped, style="bold cyan")
        elif stripped.startswith("@@"):
            console.print(stripped, style="bold magenta")
        elif stripped.startswith("+"):
            console.print(stripped, style="green")
        elif stripped.startswith("-"):
            console.print(stripped, style="red")
        else:
            console.print(stripped, style="dim")


def follow_file(
    path: str,
    console: Console,
    flags: _Flags,
    poll: float = 0.3,
    anchor_window: int = 32,
) -> None:
    """Tail -F semantics for line-oriented Markdown streams.

    Tracks recent emitted line hashes as anchors. On each tick re-reads
    the file, finds the most recent anchor still present, and emits only
    the lines after it. If no anchor survives, prints a rule and re-emits
    the visible tail. Survives atomic rewrites (new inode).

    Args:
      path: File path to monitor; "-" not supported.
      console: Rich Console to write appended lines to.
      flags: Parsed rendering flags (no_frontmatter, follow_lines, etc).
      poll: Sleep interval in seconds between file reads.
      anchor_window: Max recent lines to track as checksums; buffers 32 hashes by default.

    """
    anchors: collections.deque[bytes] = collections.deque(maxlen=anchor_window)
    first = True
    last_data = b""
    console.print(f"[dim]Following {path} (Ctrl+C to quit)...[/dim]\n")

    try:
        while True:
            data = _read_or_none(path)
            if data is None:
                time.sleep(poll)
                continue

            if data == last_data:
                time.sleep(poll)
                continue
            last_data = data

            lines = data.decode("utf-8", "replace").splitlines()
            if flags.no_frontmatter:
                lines = strip_frontmatter(lines)

            if first:
                tail = lines[-flags.follow_lines :] if flags.follow_lines else lines
                first = False
            else:
                idx = _find_anchor_index(lines, anchors)
                if idx is None:
                    console.print(Rule("reopened", style="dim"))
                    tail = lines[-flags.follow_lines :] if flags.follow_lines else lines
                else:
                    tail = lines[idx + 1 :]

            for line in tail:
                if not line.strip():
                    continue
                _render_line(console, flags, line)
                anchors.append(_line_hash(line))

            time.sleep(poll)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped following[/dim]")


def watch_file(
    path: str,
    render_func: Callable[[str, Console, _Flags], str],
    console: Console,
    flags: _Flags,
) -> None:
    """Watch file for changes and re-render.

    Args:
      path: File path to monitor; must exist.
      render_func: Callable(path, console, flags) -> str that renders the file.
      console: Rich Console to clear and rewrite on each change.
      flags: Parsed rendering flags.

    """
    last_mtime = 0.0
    console.print(f"[dim]Watching {path} for changes (Ctrl+C to quit)...[/dim]\n")

    try:
        while True:
            current_mtime = _mtime_or_none(path)
            if current_mtime is None:
                console.print(f"[red]File {path} not found[/red]")
            elif current_mtime != last_mtime:
                last_mtime = current_mtime
                console.clear()
                console.print(
                    f"[dim]Updated at {time.strftime('%H:%M:%S')}[/dim]\n",
                )
                render_func(path, console, flags)

            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watching[/dim]")


def export_html(markdown_body: str, output_path: str) -> None:
    """Export markdown as HTML.

    Args:
      markdown_body: Markdown text to convert.
      output_path: File path to write the rendered HTML document to.

    """
    md = MarkdownIt()
    html = cast(str, md.render(markdown_body))

    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }}
        code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
        pre {{ background: #f4f4f4; padding: 16px; border-radius: 6px; overflow-x: auto; }}
        pre code {{ background: none; padding: 0; }}
    </style>
</head>
<body>
{html}
</body>
</html>
"""

    with Path(output_path).open("w", encoding="utf-8") as f:
        f.write(html_template)


def render_markdown_file(path: str, console: Console, flags: _Flags) -> str:
    """Read and render a markdown file, returning the body.

    Args:
      path: File path or "-" for stdin.
      console: Rich Console to write rendered output to.
      flags: Parsed display mode flags (toc, links, section, etc).

    Returns:
      markdown_body: Processed markdown string before rendering.

    """
    if path == "-":
        markdown_body = sys.stdin.read()
    else:
        with Path(path).open(encoding="utf-8") as markdown_file:
            markdown_body = markdown_file.read()

    # Strip YAML frontmatter if requested.
    if flags.no_frontmatter:
        markdown_body = "\n".join(strip_frontmatter(markdown_body.splitlines()))

    # Process emoji shortcodes and math blocks.
    markdown_body = process_emoji(markdown_body)
    markdown_body = process_math_blocks(markdown_body, enable_math=flags.math)

    # Apply section filter if specified.
    if flags.section:
        markdown_body = filter_section(markdown_body, flags.section)
        if not markdown_body:
            console.print(f"[red]Section '{flags.section}' not found[/red]")
            return ""

    # Handle various display modes.
    if flags.toc:
        headings = extract_headings(markdown_body)
        render_toc(headings, console)
        return markdown_body

    if flags.links:
        links = extract_links(markdown_body)
        console.print(
            Panel(
                "\n".join(links) if links else "[dim]No links found[/dim]",
                title="Links",
            ),
        )
        return markdown_body

    if flags.check_links:
        links = extract_links(markdown_body)
        check_links(links, console)
        return markdown_body

    if flags.code_only:
        code_blocks = extract_code_blocks(markdown_body, flags.code_lang)
        if code_blocks:
            render_code_blocks(code_blocks, console)
        else:
            console.print("[dim]No code blocks found[/dim]")
        return markdown_body

    # Regular markdown rendering.
    markdown = Markdown(
        markdown_body,
        justify="full" if flags.justify else "left",
        code_theme=flags.code_theme,
        hyperlinks=flags.hyperlinks,
        inline_code_lexer=flags.inline_code_lexer,
    )

    if flags.page:
        fileio = io.StringIO()
        page_console = Console(
            file=fileio,
            force_terminal=False if flags.ascii else flags.force_color,
            width=flags.width,
        )
        page_console.print(markdown)
        output = fileio.getvalue()
        if flags.ascii:
            output = to_ascii(output)
        if not flags.pad:
            output = strip_trailing_whitespace(output)
        pydoc.pager(output)
    else:
        # Capture output to strip trailing whitespace (unless --pad specified)
        fileio = io.StringIO()
        capture_console = Console(
            file=fileio,
            force_terminal=console.is_terminal or flags.force_color,
            width=flags.pad or flags.width,
        )
        capture_console.print(markdown)
        output = fileio.getvalue()
        if not flags.pad:
            output = strip_trailing_whitespace(output)
        console.file.write(output)

    return markdown_body


def main() -> int:
    """Entry point; exit quietly if a pipe reader (e.g. `less`) quits early."""
    try:
        return _main()
    except BrokenPipeError:
        _exit_on_broken_pipe()


def _main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    flags, remaining = _parse_args(parser)
    if remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")

    # --code-lang implies --code-only.
    if flags.code_lang:
        if flags.toc or flags.links or flags.check_links:
            parser.error(
                "--code-lang cannot be used with --toc, --links, or --check-links",
            )
        flags.code_only = True

    # Validate incompatible flags.
    if flags.page and flags.watch:
        parser.error("--page and --watch cannot be used together")
    if flags.follow and flags.watch:
        parser.error("--follow and --watch are mutually exclusive")
    if flags.follow and flags.page:
        parser.error("--page and --follow cannot be used together")
    if flags.follow and (
        flags.toc or flags.links or flags.check_links or flags.code_only
    ):
        parser.error(
            "--follow cannot be combined with --toc/--links/--check-links/--code-only",
        )

    # Apply style profile.
    if flags.style:
        profile = STYLE_PROFILES[flags.style]
        flags.code_theme = profile["code_theme"]

    # Create console - capture to StringIO for --ascii mode.
    ascii_buffer = io.StringIO() if flags.ascii else None
    console = Console(
        file=ascii_buffer,
        force_terminal=False if flags.ascii else flags.force_color,
        width=flags.width,
        record=True,
    )

    # Handle diff mode.
    if flags.diff:
        if not flags.path or len(flags.path) != 1:
            console.print("[red]Error: --diff requires exactly one file argument[/red]")
            sys.exit(1)
        render_diff(flags.path[0], flags.diff, console)
        return 0

    # Ensure we have at least one file.
    if not flags.path:
        flags.path = ["-"]

    # Handle watch mode.
    if flags.watch:
        if len(flags.path) != 1 or flags.path[0] == "-":
            console.print("[red]Error: --watch requires exactly one file path[/red]")
            sys.exit(1)
        watch_file(flags.path[0], render_markdown_file, console, flags)
        return 0

    # Handle follow mode.
    if flags.follow:
        if len(flags.path) != 1 or flags.path[0] == "-":
            console.print("[red]Error: --follow requires exactly one file path[/red]")
            sys.exit(1)
        follow_file(flags.path[0], console, flags)
        return 0

    # Process files.
    markdown_bodies: list[str] = []
    for i, path in enumerate(flags.path):
        if i > 0 and flags.separator:
            console.print(Rule(style="dim"))

        markdown_body = render_markdown_file(path, console, flags)
        markdown_bodies.append(markdown_body)

    # Handle exports.
    combined_body = "\n\n".join(markdown_bodies)

    if flags.export_html:
        export_html(combined_body, flags.export_html)
        console.print(f"[green]Exported HTML to {flags.export_html}[/green]")

    if flags.export_ansi:
        with Path(flags.export_ansi).open("w", encoding="utf-8") as f:
            f.write(console.export_text())
        console.print(f"[green]Exported ANSI to {flags.export_ansi}[/green]")

    # Output ASCII-converted text.
    if ascii_buffer is not None:
        print(to_ascii(ascii_buffer.getvalue()), end="")  # noqa: T201 -- ASCII mode is the command's final console output.
    return 0


def _line_hash(line: str) -> bytes:
    return hashlib.blake2b(line.encode("utf-8"), digest_size=16).digest()


def _find_anchor_index(
    lines: list[str],
    anchors: collections.deque[bytes],
) -> int | None:
    """Return the highest index in ``lines`` whose hash is in ``anchors``."""
    if not anchors:
        return None
    anchor_set = set(anchors)
    for i in range(len(lines) - 1, -1, -1):
        if _line_hash(lines[i]) in anchor_set:
            return i
    return None


def _render_line(console: Console, flags: _Flags, line: str) -> None:
    """Print one markdown line with the CLI's rendering options."""
    body = process_emoji(line)
    body = process_math_blocks(body, enable_math=flags.math)
    console.print(
        Markdown(
            body,
            justify="full" if flags.justify else "left",
            code_theme=flags.code_theme,
            hyperlinks=flags.hyperlinks,
            inline_code_lexer=flags.inline_code_lexer,
        ),
    )


def _read_or_none(path: str) -> bytes | None:
    """Read the file's bytes; None while it does not exist yet."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


def _mtime_or_none(path: str) -> float | None:
    """Read the file's mtime; None while it does not exist."""
    try:
        return Path(path).stat().st_mtime
    except FileNotFoundError:
        return None


# Redirect the remaining stdout to /dev/null so the interpreter's final flush at
# shutdown does not re-raise BrokenPipeError. See.
# https://docs.python.org/3/library/signal.html#note-on-sigpipe.
def _exit_on_broken_pipe() -> NoReturn:
    """Exit(0) cleanly after a downstream reader closed the pipe."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    raise SystemExit(0)


def _parse_args(
    parser: argparse.ArgumentParser,
    argv: list[str] | None = None,
) -> tuple[_Flags, list[str]]:
    """Add mdcat flags to ``parser`` and parse."""
    parser.add_argument(
        "path",
        metavar="PATH",
        nargs="*",
        help="path(s) to markdown file(s), or - for stdin",
    )
    color_group = parser.add_mutually_exclusive_group()
    color_group.add_argument(
        "-c",
        "--force-color",
        dest="force_color",
        action="store_true",
        default=None,
        help="force color for non-terminals",
    )
    color_group.add_argument(
        "--ascii",
        dest="ascii",
        action="store_true",
        help="ASCII-only output (no ANSI codes, no Unicode)",
    )
    parser.add_argument(
        "-t",
        "--code-theme",
        dest="code_theme",
        default="monokai",
        help="pygments code theme",
    )
    parser.add_argument(
        "-i",
        "--inline-code-lexer",
        dest="inline_code_lexer",
        default=None,
        help="inline_code_lexer",
    )
    parser.add_argument(
        "-y",
        "--hyperlinks",
        dest="hyperlinks",
        action="store_true",
        default=True,
        help="enable hyperlinks",
    )
    parser.add_argument(
        "-w",
        "--width",
        type=int,
        dest="width",
        default=None,
        help="width of output (default will auto-detect)",
    )
    parser.add_argument(
        "--pad",
        type=int,
        dest="pad",
        default=None,
        metavar="WIDTH",
        help="pad lines to WIDTH (default: no padding, strip trailing whitespace)",
    )
    parser.add_argument(
        "-j",
        "--justify",
        dest="justify",
        action="store_true",
        help="enable full text justify",
    )
    parser.add_argument(
        "-p",
        "--page",
        dest="page",
        action="store_true",
        help="use pager to scroll output",
    )
    parser.add_argument(
        "--separator",
        dest="separator",
        action="store_true",
        help="add separator between multiple files",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--toc",
        dest="toc",
        action="store_true",
        help="show table of contents",
    )
    mode_group.add_argument(
        "--links",
        dest="links",
        action="store_true",
        help="extract and list all links",
    )
    mode_group.add_argument(
        "--check-links",
        dest="check_links",
        action="store_true",
        help="validate all links are reachable",
    )
    mode_group.add_argument(
        "--code-only",
        dest="code_only",
        action="store_true",
        help="show only code blocks",
    )
    parser.add_argument(
        "--code-lang",
        dest="code_lang",
        default=None,
        help="filter code blocks by language",
    )
    parser.add_argument(
        "--style",
        dest="style",
        choices=list(STYLE_PROFILES.keys()),
        help="use predefined style profile",
    )
    parser.add_argument(
        "--export-html",
        dest="export_html",
        metavar="OUTPUT",
        help="export as HTML to file",
    )
    parser.add_argument(
        "--export-ansi",
        dest="export_ansi",
        metavar="OUTPUT",
        help="export ANSI colored output to file",
    )
    parser.add_argument(
        "--watch",
        dest="watch",
        action="store_true",
        help="watch file for changes and re-render",
    )
    parser.add_argument(
        "-f",
        "-F",
        "--follow",
        dest="follow",
        action="store_true",
        help="follow file tail-F-style: emit only new lines, survive rewrites",
    )
    parser.add_argument(
        "-n",
        "--follow-lines",
        dest="follow_lines",
        type=int,
        default=0,
        metavar="N",
        help="with --follow: show last N lines on first attach/reopen (0 = all)",
    )
    parser.add_argument(
        "--no-frontmatter",
        dest="no_frontmatter",
        action="store_true",
        help="strip leading YAML frontmatter (--- ... ---) before rendering",
    )
    parser.add_argument(
        "--section",
        dest="section",
        metavar="HEADING",
        help="show only specific section by heading name",
    )
    parser.add_argument(
        "--diff",
        dest="diff",
        metavar="FILE2",
        help="show diff with another markdown file",
    )
    parser.add_argument(
        "--no-math",
        "--nomath",
        dest="math",
        action="store_false",
        default=True,
        help="disable math rendering (default: enabled)",
    )
    parsed, remaining = parser.parse_known_args(argv)
    return cast(_Flags, parsed), remaining
