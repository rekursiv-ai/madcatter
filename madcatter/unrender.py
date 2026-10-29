"""Convert mdcat's rendered output back into markdown.

A file ``mdcat -i`` rendered carries its markdown source, and the layout it was
rendered with, in invisible escape codes. ``unrender`` returns that source byte
for byte when rendering it again shows exactly the text the file shows; after
an edit, or without the codes, it reads the markdown back from what is shown:
heading levels, inline styles, links, lists, quotes, rules, code blocks and
tables. That reading loses whatever the render dropped. Text without escape
codes, such as markdown source, passes through unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import base64
import dataclasses
import itertools
import re

from madcatter.markdown import is_fence_delimiter


if TYPE_CHECKING:
    from collections.abc import Callable


_ESCAPE = re.compile(
    r"\x1b\[(?P<sgr>[0-9;]*)(?P<final>[@-~])"
    r"|\x1b\]8;[^;]*;(?P<link>[^\x07\x1b]*)(?:\x07|\x1b\\)"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    # A code cut off by truncation would otherwise show as text.
    r"|\x1b\][^\x07\x1b]*\x1b?$",
)
_MARK = re.compile(
    r"\x1b\]8;id=mdcat-source:w=(\d+):j=([01]):m=([01]):f=([01]);"
    r"data:text/markdown;base64,([A-Za-z0-9+/=]*)\x1b\\\x1b\]8;;\x1b\\",
)
# Rich's default theme gives each heading level its own style, most specific
# first so H4 (italic magenta) is not read as H5 (italic). A paragraph that is
# entirely *emphasis* renders exactly like H5, and is read as H5.
_HEADINGS = (
    frozenset({"bold", "underline"}),
    frozenset({"underline", "fg35"}),
    frozenset({"bold", "fg35"}),
    frozenset({"italic", "fg35"}),
    frozenset({"italic"}),
    frozenset({"dim"}),
)
_TABLE_STYLE = frozenset({"fg36"})


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Layout:
    """What decides a render's text, apart from its source.

    Attributes:
      width: Columns the text was wrapped to.
      justify: Whether paragraphs were fully justified.
      math: Whether LaTeX math was converted.
      frontmatter: Whether YAML frontmatter was kept.

    """

    width: int
    justify: bool
    math: bool
    frontmatter: bool


def unrender(text: str, *, render: Callable[[str, Layout], str]) -> str:
    """Convert mdcat's ANSI output back to markdown.

    Args:
      text: What mdcat printed or wrote; several files' output may be joined.
      render: Renders markdown as uncolored text under a layout, to check that
        a hidden source still matches the text shown.

    Returns:
      markdown: Each file's hidden source where it matches what is shown,
        otherwise the markdown that renders as the text shown, as far as it
        shows it; files are kept a blank line apart.

    """
    if "\x1b" not in text:
        return text
    runs = _runs(list(_MARK.finditer(text)))
    bounds = [*(run[0].start() for run in runs), len(text)]
    parts = [_visual(text[: bounds[0]])]
    for index, run in enumerate(runs):
        shown = text[run[-1].end() : bounds[index + 1]]
        parts.append(_restore(run, shown=shown, render=render))
    out = ""
    for part in parts:
        if out and part:
            out += "\n" * max(0, 2 - len(out) + len(out.rstrip("\n")))
        out += part
    return out


def mark_source(source: str, *, layout: Layout) -> str:
    """Return invisible escape codes that carry ``source`` for ``unrender``.

    Each code is an OSC 8 hyperlink opened and closed around no text, which
    terminals and ``less -R`` display as nothing.

    Args:
      source: Markdown source, exactly as read.
      layout: How the text that follows the codes was rendered.

    Returns:
      codes: One empty hyperlink per 1500-byte piece of ``source``, at least one.

    """
    data = source.encode()
    params = (
        f"w={layout.width}:j={layout.justify:d}:m={layout.math:d}"
        f":f={layout.frontmatter:d}"
    )
    # VTE ignores a hyperlink URI over 2083 bytes; 1500 bytes encode to 2000.
    return "".join(
        f"\x1b]8;id=mdcat-source:{params};data:text/markdown;base64,"
        + base64.b64encode(data[start : start + 1500]).decode("ascii")
        + "\x1b\\\x1b]8;;\x1b\\"
        for start in range(0, len(data) or 1, 1500)
    )


def _runs(marks: list[re.Match[str]]) -> list[list[re.Match[str]]]:
    """Group adjacent source codes: each group is one file's."""
    runs: list[list[re.Match[str]]] = []
    for mark in marks:
        if runs and runs[-1][-1].end() == mark.start():
            runs[-1].append(mark)
        else:
            runs.append([mark])
    return runs


def _restore(
    run: list[re.Match[str]],
    *,
    shown: str,
    render: Callable[[str, Layout], str],
) -> str:
    """Return a file's hidden source if it renders as ``shown``, else read ``shown``."""
    width, justify, math, frontmatter = run[0].group(1, 2, 3, 4)
    assert isinstance(width, str)
    layout = Layout(
        width=int(width),
        justify=justify == "1",
        math=math == "1",
        frontmatter=frontmatter == "1",
    )
    try:
        source = b"".join(
            base64.b64decode(mark.group(5), validate=True) for mark in run
        ).decode()
    # Corrupt base64 raises binascii.Error, and bytes that are not UTF-8 raise
    # UnicodeDecodeError; both are ValueErrors.
    except ValueError:
        return _visual(shown)
    if _shown_text(render(source, layout)) == _shown_text(shown):
        return source
    return _visual(shown)


def _shown_text(text: str) -> str:
    """Return the text a terminal would show for ``text``, trailing spaces cut."""
    return "\n".join(_plain(_spans(line)).rstrip() for line in text.split("\n"))


def _visual(text: str) -> str:
    """Read markdown back from what mdcat's output shows."""
    lines = [_spans(line) for line in text.split("\n")]
    out: list[str] = []
    lists: list[tuple[int, int]] = []
    fenced = False
    i = 0
    while i < len(lines):
        end = _code_end(lines, i) or _table_end(lines, i)
        if end:
            block = lines[i:end]
            out.extend(_code_block(block) if _is_code(lines[i]) else _table(block))
            lists.clear()
            i = end
            continue
        plain = _plain(lines[i])
        if fenced or is_fence_delimiter(plain):
            fenced ^= is_fence_delimiter(plain)
            out.append(plain)
        else:
            out.append(_line(lines[i], lists=lists))
        i += 1
    # Rich opens some blocks with a blank line; markdown never needs one first.
    return "\n".join(out).lstrip("\n")


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _Span:
    """Text printed under one style and link target."""

    text: str
    style: frozenset[str]
    link: str


def _spans(line: str) -> list[_Span]:
    """Split one output line into styled spans, dropping every escape code."""
    spans: list[_Span] = []
    style = frozenset[str]()
    link = ""
    end = 0
    for match in _ESCAPE.finditer(line):
        if match.start() > end:
            spans.append(_Span(text=line[end : match.start()], style=style, link=link))
        end = match.end()
        sgr, final, target = match.group("sgr", "final", "link")
        if final == "m":
            assert isinstance(sgr, str)
            style = _sgr(style, sgr)
        elif isinstance(target, str):
            link = target
    if end < len(line):
        spans.append(_Span(text=line[end:], style=style, link=link))
    return spans


def _sgr(style: frozenset[str], params: str) -> frozenset[str]:
    """Apply one SGR escape's parameters to ``style``."""
    attrs = {1: "bold", 2: "dim", 3: "italic", 4: "underline", 9: "strike"}
    codes = [int(code) if code else 0 for code in params.split(";")]
    current = set[str](style)
    i = 0
    while i < len(codes):
        code = codes[i]
        if code == 0:
            current.clear()
        elif code in attrs:
            current.add(attrs[code])
        elif 30 <= code <= 37 or 90 <= code <= 97:
            current.difference_update([s for s in current if s.startswith("fg")])
            current.add(f"fg{code}")
        elif 40 <= code <= 47 or 100 <= code <= 107 or code == 48:
            current.add("bg")
        # 38 and 48 carry a 256-color index or an RGB triple after them.
        if code in {38, 48}:
            i += 2 if i + 1 < len(codes) and codes[i + 1] == 5 else 4
        i += 1
    return frozenset(current)


def _plain(spans: list[_Span]) -> str:
    return "".join(span.text for span in spans)


def _is_code(spans: list[_Span]) -> bool:
    """Report whether a line is a code-block line: background on every span."""
    return (
        bool(spans)
        and spans[0].text.startswith(" ")
        and all("bg" in span.style for span in spans)
    )


def _code_end(lines: list[list[_Span]], start: int) -> int:
    """Return the end of the code-block run at ``start``, or 0 for none."""
    end = start
    while end < len(lines) and _is_code(lines[end]):
        end += 1
    return end if end > start else 0


def _code_block(lines: list[list[_Span]]) -> list[str]:
    """Fence a run of code-block lines, dropping Rich's padding rows."""
    texts = [_plain(line) for line in lines]
    if not texts[0].strip():
        texts = texts[1:]
    if texts and not texts[-1].strip():
        texts = texts[:-1]
    return ["```", *(text[1:].rstrip() for text in texts), "```"]


def _is_border(spans: list[_Span]) -> bool:
    """Report whether a line is a table's blank top or bottom border."""
    return (
        len(spans) == 1 and spans[0].style == _TABLE_STYLE and not spans[0].text.strip()
    )


def _is_divider(span: _Span) -> bool:
    return span.text == " " and span.style == _TABLE_STYLE


def _table_end(lines: list[list[_Span]], start: int) -> int:
    """Return the line after the table opening at ``start``, or 0 for none."""
    if not (
        start + 2 < len(lines)
        and _is_border(lines[start])
        and lines[start + 1]
        and _is_divider(lines[start + 1][0])
        and set(_plain(lines[start + 2]).strip()) == {"─"}
    ):
        return 0
    end = start + 3
    while end < len(lines) and not _is_border(lines[end]):
        end += 1
    return min(end + 1, len(lines))


def _table(lines: list[list[_Span]]) -> list[str]:
    """Convert a bordered table back to a pipe table."""
    rows = [line for line in lines[1:] if line and not _is_border(line)]
    header, body = _cells(rows[0]), [_cells(row) for row in rows[2:]]
    raws = [[_plain(cell) for cell in row] for row in [header, *body]]
    aligns = [
        _align([row[col] for row in raws if col < len(row)])
        for col in range(len(header))
    ]
    header_drop = _TABLE_STYLE | {"bold"}
    out = ["| " + " | ".join(_cell(cell, drop=header_drop) for cell in header) + " |"]
    out.append("|" + "|".join(aligns) + "|")
    out.extend(
        "| " + " | ".join(_cell(cell, drop=frozenset()) for cell in row) + " |"
        for row in body
    )
    return out


def _cells(spans: list[_Span]) -> list[list[_Span]]:
    """Split a table row at its column dividers."""
    return [
        list(group)
        for is_divider, group in itertools.groupby(spans, key=_is_divider)
        if not is_divider
    ]


def _cell(spans: list[_Span], *, drop: frozenset[str]) -> str:
    return _inline(spans, drop=drop).strip().replace("|", r"\|")


def _align(raws: list[str]) -> str:
    """Infer a column's alignment from where its cells' padding falls."""
    pads = [
        (len(raw) - len(raw.lstrip()), len(raw) - len(raw.rstrip())) for raw in raws
    ]
    if any(lead and trail for lead, trail in pads):
        return ":-:"
    if any(lead == 0 < trail for lead, trail in pads):
        return "---"
    return "--:" if any(lead for lead, _ in pads) else "---"


# ``lists`` holds the enclosing list items, innermost last, each as its rendered indent
# and its markdown indent; this line updates it.
def _line(spans: list[_Span], *, lists: list[tuple[int, int]]) -> str:
    """Convert one output line to markdown."""
    plain = _plain(spans)
    stripped = plain.strip()
    if len(stripped) >= 3 and set(stripped) <= set("-─━"):
        lists.clear()
        return "---"
    pos = 0
    while plain.startswith("▌", pos):
        pos += 1 + plain.startswith(" ", pos + 1)
    quotes = plain[:pos].count("▌")
    quote = "> " * quotes
    if not plain[pos:].strip():
        return quote.rstrip()
    lead, rest = _list_prefix(spans, plain=plain, pos=pos, lists=lists)
    drop = frozenset({"fg35"}) if quotes else frozenset[str]()
    if not (quotes or lists):
        level, drop = _heading(rest)
        lead = "#" * level + " " if level else lead
    return (quote + lead + _inline(rest, drop=drop)).rstrip()


def _list_prefix(
    spans: list[_Span],
    *,
    plain: str,
    pos: int,
    lists: list[tuple[int, int]],
) -> tuple[str, list[_Span]]:
    """Return a line's markdown list prefix and its spans after the rendered one."""
    found = re.compile(r"( *)(•|\d+\.)(?= |$) ?").match(plain, pos)
    column = (
        found.end(1) - pos if found else len(plain) - pos - len(plain[pos:].lstrip(" "))
    )
    while lists and sum(rendered for rendered, _ in lists) > column:
        lists.pop()
    rendered = sum(width for width, _ in lists)
    lead = " " * sum(width for _, width in lists)
    if found is None:
        return lead, _drop(spans, count=pos + rendered)
    marker = found.group(2)
    assert isinstance(marker, str)
    bullet = marker == "•"
    lists.append(
        (column - rendered + len(marker) + 1, 2 if bullet else len(marker) + 1),
    )
    prefix = "- " if bullet else marker + " "
    return lead + prefix, _drop(spans, count=found.end())


def _drop(spans: list[_Span], *, count: int) -> list[_Span]:
    """Remove the first ``count`` characters from ``spans``."""
    kept: list[_Span] = []
    for span in spans:
        if count >= len(span.text):
            count -= len(span.text)
            continue
        kept.append(dataclasses.replace(span, text=span.text[count:]))
        count = 0
    return kept


def _heading(spans: list[_Span]) -> tuple[int, frozenset[str]]:
    """Return the heading level whose style covers every span, and that style."""
    texts = [span for span in spans if span.text.strip() and not span.link]
    for level, attrs in enumerate(_HEADINGS, start=1):
        if texts and all(attrs <= span.style for span in texts):
            return level, attrs
    return 0, frozenset[str]()


def _inline(spans: list[_Span], *, drop: frozenset[str]) -> str:
    """Convert styled spans to inline markdown, ignoring the attributes ``drop``."""
    out: list[str] = []
    for link, group in itertools.groupby(spans, key=lambda span: span.link):
        # Rich underlines link text in blue; neither is markup.
        ignored = drop | {"underline", "fg34"} if link else drop
        body = _emphasis(list(group), drop=ignored)
        out.append(f"[{body}]({link})" if link else body)
    return "".join(out)


def _emphasis(spans: list[_Span], *, drop: frozenset[str]) -> str:
    """Wrap each run of one style in its markdown markers."""
    out: list[str] = []
    for style, group in itertools.groupby(spans, key=lambda span: span.style - drop):
        text = "".join(span.text for span in group)
        if "bg" in style:
            out.append(f"`{text}`")
            continue
        wrap = ("~~" if "strike" in style else "") + "*" * (
            ("bold" in style) * 2 + ("italic" in style)
        )
        core = text.strip()
        if not (core and wrap):
            out.append(text)
            continue
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()) :]
        out.append(lead + wrap + core + wrap[::-1] + trail)
    return "".join(out)
