#!/bin/sh
# ruff: noqa: EXE003, D300, T201 -- Polyglot shell/Python script; console renderer prints.
# fmt: off
'''' 2>/dev/null #
exec uv --quiet --project "$(dirname "$0")" run --frozen --no-sync python3 "$0" "$@"
Render Markdown to the console with Rich.

Custom markdown renderer that left-justifies headings instead of centering.
'''
# fmt: on

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Final, override
from urllib.parse import urlparse

import argparse
import collections
import difflib
import hashlib
import io
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

from madcatter.emoji import resolve as resolve_emoji
from madcatter.markdown import process_math_blocks, strip_frontmatter


# Unicode to ASCII translation for printable output
_UNICODE_TO_ASCII_CHARS = str.maketrans(
    {
        "\u2501": "-",
        "\u2500": "-",
        "\u2502": "|",
        "\u2503": "|",  # box drawing
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
        "\u2013": "-",  # bullet, middle dot, en-dash
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',  # curly quotes
        "\u00d7": "x",
        "\u00f7": "/",  # multiply, divide
    },
)
_UNICODE_TO_ASCII_STRS: Final = [
    ("…", "..."),
    ("—", "--"),
    ("±", "+/-"),
    ("→", "->"),
    ("←", "<-"),
    ("↔", "<->"),
    ("≤", "<="),
    ("≥", ">="),
    ("≠", "!="),
    ("≈", "~="),
    ("📑", "[TOC]"),
]


def to_ascii(text: str) -> str:
    """Convert Unicode text to ASCII."""
    text = text.translate(_UNICODE_TO_ASCII_CHARS)
    for uni, asc in _UNICODE_TO_ASCII_STRS:
        text = text.replace(uni, asc)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def strip_trailing_whitespace(text: str) -> str:
    """Strip trailing whitespace from each line."""
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


_EMOJI_RE = re.compile(r":([a-z0-9_+\-]+):")


def process_emoji(text: str) -> str:
    """Replace :shortcode: with Unicode emoji, skipping code blocks."""

    def _replace(match: re.Match[str]) -> str:
        resolved = resolve_emoji(match.group(1))
        return resolved if resolved is not None else match.group(0)

    lines = text.split("\n")
    result: list[str] = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            result.append(line)
        elif in_fence or line.startswith("    "):
            result.append(line)
        else:
            result.append(_EMOJI_RE.sub(_replace, line))
    return "\n".join(result)


# Style profiles
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
    """Extract headings from markdown with their levels."""
    headings: list[tuple[int, str]] = []
    in_code_block = False

    for line in markdown_body.split("\n"):
        # Track code block boundaries
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue

        # Skip lines inside code blocks
        if in_code_block:
            continue

        if match := re.match(r"^(#{1,6})\s+(.+)$", line):
            level = len(match.group(1))
            title = match.group(2).strip()
            headings.append((level, title))
    return headings


def render_toc(headings: list[tuple[int, str]], console: Console) -> None:
    """Render table of contents as a tree."""
    tree = Tree("📑 Table of Contents", guide_style="dim")
    stack: list[tuple[int, Tree]] = [(0, tree)]

    for level, title in headings:
        # Pop from stack until we find the parent level
        while stack and stack[-1][0] >= level:
            stack.pop()

        # Add node under current parent
        parent_tree = stack[-1][1] if stack else tree
        node = parent_tree.add(f"[bold]{title}[/bold]")
        stack.append((level, node))

    console.print(tree)
    console.print()


def extract_links(markdown_body: str) -> list[str]:
    """Extract all URLs from markdown."""
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
    """Check if URLs are reachable."""
    table = Table(title="Link Validation", show_header=True)
    table.add_column("URL", style="cyan")
    table.add_column("Status", style="green")

    for link in links:
        # Skip relative/anchor links
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
    """Extract code blocks from markdown."""
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
    """Render code blocks."""
    for i, (lang, code) in enumerate(code_blocks):
        if i > 0:
            console.print()
        title = f"Code Block {i + 1}" + (f" ({lang})" if lang else "")
        console.print(Panel(Syntax(code, lang or "text", theme="monokai"), title=title))


def filter_section(markdown_body: str, section_name: str) -> str:
    """Extract a specific section from markdown."""
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
                # Hit a same-or-higher level heading, end of section
                break
            elif in_section:
                section_lines.append(line)
        elif in_section:
            section_lines.append(line)

    return "\n".join(section_lines)


def render_diff(file1: str, file2: str, console: Console) -> None:
    """Render diff between two markdown files."""
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


def follow_file(
    path: str,
    console: Console,
    args: argparse.Namespace,
    poll: float = 0.3,
    anchor_window: int = 32,
) -> None:
    """Tail -F semantics for line-oriented Markdown streams.

    Tracks recent emitted line hashes as anchors. On each tick re-reads
    the file, finds the most recent anchor still present, and emits only
    the lines after it. If no anchor survives, prints a rule and re-emits
    the visible tail. Survives atomic rewrites (new inode).
    """
    anchors: collections.deque[bytes] = collections.deque(maxlen=anchor_window)
    first = True
    last_data = b""
    console.print(f"[dim]Following {path} (Ctrl+C to quit)...[/dim]\n")

    def _render_line(line: str) -> None:
        body = process_emoji(line)
        body = process_math_blocks(body, enable_math=args.math)
        console.print(
            Markdown(
                body,
                justify="full" if args.justify else "left",
                code_theme=args.code_theme,
                hyperlinks=args.hyperlinks,
                inline_code_lexer=args.inline_code_lexer,
            ),
        )

    try:
        while True:
            try:
                with Path(path).open("rb") as fh:
                    data = fh.read()
            except FileNotFoundError:
                time.sleep(poll)
                continue

            if data == last_data:
                time.sleep(poll)
                continue
            last_data = data

            lines = data.decode("utf-8", "replace").splitlines()
            if args.no_frontmatter:
                lines = strip_frontmatter(lines)

            if first:
                tail = lines[-args.follow_lines :] if args.follow_lines else lines
                first = False
            else:
                idx = _find_anchor_index(lines, anchors)
                if idx is None:
                    console.print(Rule("reopened", style="dim"))
                    tail = lines[-args.follow_lines :] if args.follow_lines else lines
                else:
                    tail = lines[idx + 1 :]

            for line in tail:
                if not line.strip():
                    continue
                _render_line(line)
                anchors.append(_line_hash(line))

            time.sleep(poll)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped following[/dim]")


def watch_file(
    path: str,
    render_func: Callable[[str, Console, argparse.Namespace], str],
    console: Console,
    args: argparse.Namespace,
) -> None:
    """Watch file for changes and re-render."""
    last_mtime = 0.0
    console.print(f"[dim]Watching {path} for changes (Ctrl+C to quit)...[/dim]\n")

    try:
        while True:
            try:
                current_mtime = Path(path).stat().st_mtime
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    console.clear()
                    console.print(
                        f"[dim]Updated at {time.strftime('%H:%M:%S')}[/dim]\n",
                    )
                    render_func(path, console, args)
            except FileNotFoundError:
                console.print(f"[red]File {path} not found[/red]")

            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watching[/dim]")


def export_html(markdown_body: str, output_path: str) -> None:
    """Export markdown as HTML."""
    md = MarkdownIt()
    html = md.render(markdown_body)

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


def render_markdown_file(path: str, console: Console, args: argparse.Namespace) -> str:
    """Read and render a markdown file, returning the body."""
    if path == "-":
        markdown_body = sys.stdin.read()
    else:
        with Path(path).open(encoding="utf-8") as markdown_file:
            markdown_body = markdown_file.read()

    # Strip YAML frontmatter if requested
    if args.no_frontmatter:
        markdown_body = "\n".join(strip_frontmatter(markdown_body.splitlines()))

    # Process emoji shortcodes and math blocks
    markdown_body = process_emoji(markdown_body)
    markdown_body = process_math_blocks(markdown_body, enable_math=args.math)

    # Apply section filter if specified
    if args.section:
        markdown_body = filter_section(markdown_body, args.section)
        if not markdown_body:
            console.print(f"[red]Section '{args.section}' not found[/red]")
            return ""

    # Handle various display modes
    if args.toc:
        headings = extract_headings(markdown_body)
        render_toc(headings, console)
        return markdown_body

    if args.links:
        links = extract_links(markdown_body)
        console.print(
            Panel(
                "\n".join(links) if links else "[dim]No links found[/dim]",
                title="Links",
            ),
        )
        return markdown_body

    if args.check_links:
        links = extract_links(markdown_body)
        check_links(links, console)
        return markdown_body

    if args.code_only:
        code_blocks = extract_code_blocks(markdown_body, args.code_lang)
        if code_blocks:
            render_code_blocks(code_blocks, console)
        else:
            console.print("[dim]No code blocks found[/dim]")
        return markdown_body

    # Regular markdown rendering
    markdown = Markdown(
        markdown_body,
        justify="full" if args.justify else "left",
        code_theme=args.code_theme,
        hyperlinks=args.hyperlinks,
        inline_code_lexer=args.inline_code_lexer,
    )

    if args.page:
        fileio = io.StringIO()
        page_console = Console(
            file=fileio,
            force_terminal=False if args.ascii else args.force_color,
            width=args.width,
        )
        page_console.print(markdown)
        output = fileio.getvalue()
        if args.ascii:
            output = to_ascii(output)
        if not args.pad:
            output = strip_trailing_whitespace(output)
        pydoc.pager(output)
    else:
        # Capture output to strip trailing whitespace (unless --pad specified)
        fileio = io.StringIO()
        capture_console = Console(
            file=fileio,
            force_terminal=console.is_terminal or args.force_color,
            width=args.pad or args.width,
        )
        capture_console.print(markdown)
        output = fileio.getvalue()
        if not args.pad:
            output = strip_trailing_whitespace(output)
        console.file.write(output)

    return markdown_body


def _parse_args(
    parser: argparse.ArgumentParser,
    argv: list[str] | None = None,
) -> tuple[argparse.Namespace, list[str]]:
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
    return parser.parse_known_args(argv)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n", 2)[2],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    args, remaining = _parse_args(parser)
    if remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")

    # --code-lang implies --code-only
    if args.code_lang:
        if args.toc or args.links or args.check_links:
            parser.error(
                "--code-lang cannot be used with --toc, --links, or --check-links",
            )
        args.code_only = True

    # Validate incompatible flags
    if args.page and args.watch:
        parser.error("--page and --watch cannot be used together")
    if args.follow and args.watch:
        parser.error("--follow and --watch are mutually exclusive")
    if args.follow and args.page:
        parser.error("--page and --follow cannot be used together")
    if args.follow and (args.toc or args.links or args.check_links or args.code_only):
        parser.error(
            "--follow cannot be combined with --toc/--links/--check-links/--code-only",
        )

    # Apply style profile
    if args.style:
        profile = STYLE_PROFILES[args.style]
        args.code_theme = profile["code_theme"]

    # Create console - capture to StringIO for --ascii mode
    ascii_buffer = io.StringIO() if args.ascii else None
    console = Console(
        file=ascii_buffer,
        force_terminal=False if args.ascii else args.force_color,
        width=args.width,
        record=True,
    )

    # Handle diff mode
    if args.diff:
        if not args.path or len(args.path) != 1:
            console.print("[red]Error: --diff requires exactly one file argument[/red]")
            sys.exit(1)
        render_diff(args.path[0], args.diff, console)
        return 0

    # Ensure we have at least one file
    if not args.path:
        args.path = ["-"]

    # Handle watch mode
    if args.watch:
        if len(args.path) != 1 or args.path[0] == "-":
            console.print("[red]Error: --watch requires exactly one file path[/red]")
            sys.exit(1)
        watch_file(args.path[0], render_markdown_file, console, args)
        return 0

    # Handle follow mode
    if args.follow:
        if len(args.path) != 1 or args.path[0] == "-":
            console.print("[red]Error: --follow requires exactly one file path[/red]")
            sys.exit(1)
        follow_file(args.path[0], console, args)
        return 0

    # Process files
    markdown_bodies: list[str] = []
    for i, path in enumerate(args.path):
        if i > 0 and args.separator:
            console.print(Rule(style="dim"))

        markdown_body = render_markdown_file(path, console, args)
        markdown_bodies.append(markdown_body)

    # Handle exports
    combined_body = "\n\n".join(markdown_bodies)

    if args.export_html:
        export_html(combined_body, args.export_html)
        console.print(f"[green]Exported HTML to {args.export_html}[/green]")

    if args.export_ansi:
        with Path(args.export_ansi).open("w", encoding="utf-8") as f:
            f.write(console.export_text())
        console.print(f"[green]Exported ANSI to {args.export_ansi}[/green]")

    # Output ASCII-converted text
    if ascii_buffer is not None:
        print(to_ascii(ascii_buffer.getvalue()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
# vim: ft=python
