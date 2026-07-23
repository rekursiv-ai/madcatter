"""Generate the two README panels: raw markdown vs the ``mdcat`` render.

Panel A (``cat.svg``) shows ``sample.md`` as ``cat`` would dump it -- raw text,
no interpretation. Panel B (``mdcat.svg``) shows the same file through
madcatter's real rendering path: the :class:`madcatter.mdcat.Markdown` class fed
by ``process_emoji`` and :func:`madcatter.markdown.process_math_blocks`, exactly
the pipeline ``render_markdown_file`` uses. Reusing the shipping code (rather
than reimplementing it) keeps the screenshot from drifting away from what
``mdcat sample.md`` actually prints.

Run from the worktree root::

    uv run python docs/assets/make_screenshots.py
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.text import Text

from madcatter.markdown import process_math_blocks
from madcatter.mdcat import Markdown, process_emoji


_HERE = Path(__file__).parent
_SAMPLE = _HERE / "sample.md"
_WIDTH = 48
_CODE_THEME = "monokai"


def _raw_panel(source: str) -> Console:
    """Return a console holding the file text as ``cat`` would emit it."""
    console = Console(record=True, width=_WIDTH)
    console.print(Text(source, style="default"))
    return console


def _rendered_panel(source: str) -> Console:
    """Return a console holding the file through madcatter's ``mdcat`` pipeline."""
    body = process_emoji(source)
    body = process_math_blocks(body, enable_math=True)
    console = Console(record=True, width=_WIDTH)
    console.print(Markdown(body, justify="left", code_theme=_CODE_THEME))
    return console


def main() -> None:
    """Write ``cat.svg`` and ``mdcat.svg`` next to this script."""
    source = _SAMPLE.read_text(encoding="utf-8")
    _raw_panel(source).save_svg(str(_HERE / "cat.svg"), title="cat sample.md")
    _rendered_panel(source).save_svg(str(_HERE / "mdcat.svg"), title="mdcat sample.md")


if __name__ == "__main__":
    main()
