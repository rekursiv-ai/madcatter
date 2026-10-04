"""Tests for mdcat-specific helpers (emoji shortcodes)."""

from __future__ import annotations

from io import StringIO, TextIOBase
from pathlib import Path
from typing import TYPE_CHECKING, override

import argparse
import collections
import os
import pydoc
import sys
import time

from rich.console import Console
from rich.rule import Rule

import pytest
import requests

from madcatter import markdown, mdcat
from madcatter.mdcat import extract_headings, main, process_emoji, to_ascii


if TYPE_CHECKING:
    from collections.abc import Callable


def test_to_ascii_spells_dashes_ellipses_and_arrows_in_ascii():
    # Escaped, as in to_ascii's table: houselint's emdash fix rewrites a literal
    # em dash to `--`, which once turned the table's entry into a no-op, and
    # `--ascii` then dropped every em dash.
    assert to_ascii("wait\u2026 a \u2014 b \u2192 c") == "wait... a -- b -> c"


def test_process_emoji_basic():
    assert process_emoji(":rocket:") == "🚀"
    assert process_emoji(":fire: and :heart:") == "🔥 and ❤️"


def test_process_emoji_unknown_passthrough():
    assert process_emoji(":not_a_real_emoji:") == ":not_a_real_emoji:"


def test_process_emoji_skips_fenced_code():
    text = "```\n:rocket:\n```"
    assert process_emoji(text) == text


def test_process_emoji_skips_indented_code():
    assert process_emoji("    :rocket:") == "    :rocket:"


def test_process_emoji_mixed():
    text = "Hello :wave:\n```\n:fire:\n```\n:thumbsup: done"
    result = process_emoji(text)
    assert "👋" in result
    assert ":fire:" in result
    assert "👍" in result


def test_process_emoji_unknown_in_url_passthrough():
    text = "Visit https://example.com/:path:/thing"
    assert process_emoji(text) == text


def test_process_emoji_adjacent_colons():
    assert process_emoji("::rocket::") == ":🚀:"


def test_process_emoji_single_line_fence_span_does_not_open_fence():
    """A one-line ```code``` span must not suppress emoji on later lines."""
    text = "```x = min(a, b)```\n\nDone :rocket:"
    assert "🚀" in process_emoji(text)


def test_extract_headings_after_single_line_fence_span():
    """A one-line ```code``` span must not hide subsequent headings."""
    text = "```x = min(a, b)```\n\n# Title\n"
    assert extract_headings(text) == [(1, "Title")]


@pytest.mark.parametrize("scan", [process_emoji, extract_headings])
def test_fence_tracking_reads_each_line_at_most_twice(
    scan: Callable[[str], object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recounting the fences above every line made a 32,000-line file take minutes."""
    calls: list[str] = []
    is_fence_delimiter = markdown.is_fence_delimiter

    def counting(line: str) -> bool:
        calls.append(line)
        return is_fence_delimiter(line)

    monkeypatch.setattr(markdown, "is_fence_delimiter", counting)
    monkeypatch.setattr(mdcat, "is_fence_delimiter", counting)
    text = "```\ncode :x:\n```\n# Title :rocket:\n" * 100
    scan(text)
    assert len(calls) <= 2 * len(text.split("\n"))


class _BrokenPipeStdout:
    """Stand-in for stdout after the pipe reader (e.g. `less`) quit early."""

    def write(self, data: str) -> int:
        del data
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self) -> None:
        raise BrokenPipeError(32, "Broken pipe")

    def fileno(self) -> int:
        return 1

    def isatty(self) -> bool:
        return False


def test_to_ascii_and_strip_trailing_whitespace() -> None:
    assert mdcat.to_ascii("┌─┐ • … ± → ≤ 📑") == "+-+ * ... +/- -> <= [TOC]"
    assert mdcat.strip_trailing_whitespace("a  \nb\t") == "a\nb"


def test_extract_headings_and_links(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "# One\n## Two"
    assert extract_headings(body) == [(1, "One"), (2, "Two")]

    class _Token:
        def __init__(self, token_type: str, href: str) -> None:
            self.type = token_type
            self._href = href

        def attr_get(self, name: str) -> str | None:
            return self._href if name in ("href", "src") else None

    type.__setattr__(_Token, "attrGet", _Token.attr_get)

    class _Markdown:
        def parse(self, text: str) -> list[_Token]:
            del text
            return [
                _Token("link_open", "https://example.com"),
                _Token("image", "/img.png"),
            ]

    monkeypatch.setattr(mdcat, "MarkdownIt", _Markdown)
    assert mdcat.extract_links(body) == ["https://example.com", "/img.png"]


def test_extract_code_blocks_and_filter() -> None:
    body = "```python\nprint(1)\n```\n```text\nplain\n```"
    assert mdcat.extract_code_blocks(body) == [
        ("python", "print(1)\n"),
        ("text", "plain\n"),
    ]
    assert mdcat.extract_code_blocks(body, "python") == [("python", "print(1)\n")]
    assert mdcat.filter_section("# A\na\n## B\nb\n# C\nc", "b") == "## B\nb"


def test_render_toc_and_code_blocks() -> None:
    console = Console(file=StringIO(), force_terminal=False, record=True)
    mdcat.render_toc([(1, "A"), (2, "B")], console)
    mdcat.render_code_blocks([("python", "print(1)\n"), (None, "text")], console)
    output = console.export_text()
    assert "Table of Contents" in output
    assert "Code Block 1 (python)" in output
    assert "Code Block 2" in output


def test_check_links_reports_skip_success_failure_and_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    def head(link: str, **kwargs: object) -> _Response:
        del kwargs
        if link.endswith("ok"):
            return _Response(200)
        if link.endswith("bad"):
            return _Response(404)
        raise requests.RequestException("down")

    monkeypatch.setattr(requests, "head", head)
    console = Console(file=StringIO(), force_terminal=False, record=True)
    mdcat.check_links(
        ["#anchor", "https://x/ok", "https://x/bad", "https://x/down"],
        console,
    )
    output = console.export_text()
    assert "skipped (not http/s)" in output
    assert "✓ 200" in output
    assert "✗ 404" in output
    assert "✗ RequestException" in output


def test_diff_export_and_file_helpers(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("same\nold\n")
    second.write_text("same\nnew\n")
    console = Console(file=StringIO(), force_terminal=False, record=True)
    mdcat.render_diff(str(first), str(second), console)
    assert "-old" in console.export_text()
    assert mdcat._read_or_none(str(first)) == b"same\nold\n"
    assert mdcat._read_or_none(str(tmp_path / "missing")) is None
    assert mdcat._mtime_or_none(str(first)) is not None
    assert mdcat._mtime_or_none(str(tmp_path / "missing")) is None
    assert mdcat._line_hash("line") == mdcat._line_hash("line")
    assert mdcat._line_hash("line") != mdcat._line_hash("other")
    anchors = collections.deque([mdcat._line_hash("old")], maxlen=2)
    assert mdcat._find_anchor_index(["x", "old", "y"], anchors) == 1
    assert mdcat._find_anchor_index(["x"], collections.deque()) is None

    output = tmp_path / "out.html"
    mdcat.export_html("# Heading\n\nbody", str(output))
    html = output.read_text()
    assert "<!DOCTYPE html>" in html
    assert "<h1>Heading</h1>" in html


def test_parse_args_defaults_and_options() -> None:
    parser = argparse.ArgumentParser()
    flags, remaining = mdcat._parse_args(
        parser,
        ["--ascii", "--code-lang", "python", "x.md"],
    )
    assert remaining == []
    assert flags.ascii is True
    assert flags.code_lang == "python"
    assert flags.path == ["x.md"]

    cases = [
        (["--force-color"], "force_color", True),
        (["--code-theme", "dracula"], "code_theme", "dracula"),
        (["--inline-code-lexer", "python"], "inline_code_lexer", "python"),
        (["--width", "80"], "width", 80),
        (["--pad", "90"], "pad", 90),
        (["--justify"], "justify", True),
        (["--page"], "page", True),
        (["--separator"], "separator", True),
        (["--toc"], "toc", True),
        (["--links"], "links", True),
        (["--check-links"], "check_links", True),
        (["--code-only"], "code_only", True),
        (["--style", "light"], "style", "light"),
        (["--export-html", "out.html"], "export_html", "out.html"),
        (["--export-ansi", "out.ansi"], "export_ansi", "out.ansi"),
        (["--watch"], "watch", True),
        (["--follow"], "follow", True),
        (["--follow-lines", "3"], "follow_lines", 3),
        (["--no-frontmatter"], "no_frontmatter", True),
        (["--section", "Intro"], "section", "Intro"),
        (["--diff", "other.md"], "diff", "other.md"),
        (["--no-math"], "math", False),
    ]
    for argv, name, expected in cases:
        parser = argparse.ArgumentParser()
        parsed, remaining = mdcat._parse_args(parser, argv)
        assert remaining == []
        assert getattr(parsed, name) == expected


def test_render_line_and_render_markdown_modes(tmp_path: Path) -> None:
    parser = argparse.ArgumentParser()
    flags, _ = mdcat._parse_args(parser, ["--no-math", "--no-frontmatter"])
    path = tmp_path / "doc.md"
    path.write_text("---\ntitle: x\n---\n# Heading\n\nbody $x^2$\n")
    console = Console(file=StringIO(), force_terminal=False, record=True)
    body = mdcat.render_markdown_file(str(path), console, flags)
    assert body == "# Heading\n\nbody $x^2$"
    mdcat._render_line(console, flags, "line :rocket:")
    assert "line" in console.export_text()


def test_follow_file_emits_initial_tail_and_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = argparse.ArgumentParser()
    flags, _ = mdcat._parse_args(parser, ["--follow-lines", "1"])
    path = tmp_path / "follow.md"
    path.write_text("first\nsecond\n")
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, record=True)

    def read_line(path: str) -> bytes:
        del path
        return b"first\nsecond\n"

    def stop_sleep(delay: float) -> None:
        del delay
        raise KeyboardInterrupt

    monkeypatch.setattr(mdcat, "_read_or_none", read_line)
    monkeypatch.setattr(time, "sleep", stop_sleep)
    mdcat.follow_file(str(path), console, flags, poll=0)
    output = console.export_text()
    assert "Following" in output
    assert "second" in output
    assert "first" not in output
    assert stream.getvalue().splitlines()[-1] == "Stopped following"


def test_watch_file_renders_change_and_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = argparse.ArgumentParser()
    flags, _ = mdcat._parse_args(parser, [])
    path = tmp_path / "watch.md"
    path.write_text("line\n")
    console = Console(file=StringIO(), force_terminal=False, record=True)
    rendered: list[str] = []

    def mtime(path_name: str) -> float:
        del path_name
        return 1.0

    def stop_sleep(delay: float) -> None:
        del delay
        raise KeyboardInterrupt

    def render(path_name: str, console_arg: Console, flags_arg: object) -> str:
        del console_arg, flags_arg
        rendered.append(path_name)
        return ""

    monkeypatch.setattr(mdcat, "_mtime_or_none", mtime)
    monkeypatch.setattr(time, "sleep", stop_sleep)
    mdcat.watch_file(str(path), render, console, flags)
    assert rendered == [str(path)]
    assert "Stopped watching" in console.export_text()


def test_main_modes_and_exports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = tmp_path / "doc.md"
    md.write_text("# Heading\n\n```python\nprint(1)\n```\n[link](url)\n")
    html = tmp_path / "doc.html"
    ansi = tmp_path / "doc.ansi"

    monkeypatch.setattr(sys, "argv", ["mdcat", "--toc", str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--code-only", str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--links", str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--section", "Heading", str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--ascii", str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--separator", str(md), str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--diff", str(md), str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--export-html", str(html), str(md)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["mdcat", "--export-ansi", str(ansi), str(md)])
    assert main() == 0
    assert "Heading" in html.read_text()
    assert ansi.exists()


def test_main_broken_pipe_exits_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader closing the pipe early must exit(0), not leak BrokenPipeError."""
    md = tmp_path / "x.md"
    md.write_text("# Title\n\nbody\n")
    monkeypatch.setattr(sys, "argv", ["mdcat", "-c", str(md)])
    monkeypatch.setattr(sys, "stdout", _BrokenPipeStdout())

    # Stub the fd redirect so the test does not clobber pytest's captured stdout.
    def _noop(*_args: object) -> int:
        return -1

    monkeypatch.setattr("os.dup2", _noop)
    monkeypatch.setattr("os.open", _noop)

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


class TestOwnedCoreMappings:
    def test_to_ascii_converts_every_explicit_mapping(self) -> None:
        source = "… -- ± → ← ↔ ≤ ≥ ≠ ≈ 📑"
        assert mdcat.to_ascii(source) == "... -- +/- -> <- <-> <= >= != ~= [TOC]"

    def test_to_ascii_uses_decomposition_and_ignores_unmapped_symbols(self) -> None:
        assert mdcat.to_ascii("café Ω") == "cafe "

    def test_strip_trailing_whitespace_preserves_blank_lines(self) -> None:
        assert mdcat.strip_trailing_whitespace(" a  \n\n b\t\n") == " a\n\n b\n"


class TestOwnedParsing:
    def test_process_emoji_resolves_each_shortcode_characteristically(self) -> None:
        assert mdcat.process_emoji(":+1: :coffee: :woman_technologist:") == (
            "👍 ☕ 👩‍💻"
        )

    def test_extract_headings_ignores_fence_and_continues_after_it(self) -> None:
        body = "# before\n```\n# hidden\n```\n###### after\n"
        assert mdcat.extract_headings(body) == [(1, "before"), (6, "after")]

    def test_extract_headings_requires_heading_whitespace(self) -> None:
        assert mdcat.extract_headings("#no\n#### yes\n####### too deep") == [
            (4, "yes"),
        ]

    def test_extract_links_rejects_empty_and_nonstring_attributes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Token:
            def __init__(self, token_type: str, value: object) -> None:
                self.type = token_type
                self.value = value

            def attr_get(self, name: str) -> object:
                del name
                return self.value

        type.__setattr__(Token, "attrGet", Token.attr_get)

        class Parser:
            def parse(self, text: str) -> list[Token]:
                del text
                return [
                    Token("link_open", ""),
                    Token("link_open", 4),
                    Token("image", ""),
                    Token("image", 5),
                    Token("link_open", "ok"),
                    Token("image", "pic"),
                ]

        monkeypatch.setattr(mdcat, "MarkdownIt", Parser)
        assert mdcat.extract_links("ignored") == ["ok", "pic"]

    def test_extract_code_blocks_handles_empty_info_and_filters_exactly(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Token:
            def __init__(self, info: str | None, content: str) -> None:
                self.type = "fence"
                self.info = info
                self.content = content

        class Parser:
            def parse(self, text: str) -> list[Token]:
                del text
                return [Token(None, "plain"), Token(" python ", "py")]

        monkeypatch.setattr(mdcat, "MarkdownIt", Parser)
        assert mdcat.extract_code_blocks("ignored") == [
            (None, "plain"),
            ("python", "py"),
        ]
        assert mdcat.extract_code_blocks("ignored", "python") == [("python", "py")]

    def test_filter_section_stops_at_same_level_and_keeps_subsections(self) -> None:
        body = "# Intro\na\n## Target\nb\n### Child\nc\n## Next\nd"
        assert mdcat.filter_section(body, "target") == "## Target\nb\n### Child\nc"


class TestOwnedRendering:
    def test_render_toc_builds_nested_and_sibling_nodes(self) -> None:
        console = Console(file=StringIO(), force_terminal=False, record=True)
        mdcat.render_toc([(1, "A"), (2, "B"), (1, "C")], console)
        output = console.export_text()
        assert "A" in output
        assert "B" in output
        assert "C" in output

    def test_render_code_blocks_renders_titles_and_spacing(self) -> None:
        console = Console(file=StringIO(), force_terminal=False, record=True)
        mdcat.render_code_blocks([(None, "one"), ("python", "two")], console)
        output = console.export_text()
        assert "Code Block 1" in output
        assert "Code Block 2 (python)" in output
        assert "one" in output
        assert "two" in output

    def test_check_links_renders_headers_and_all_status_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Response:
            status_code = 500

        def head(*args: object, **kwargs: object) -> Response:
            del args, kwargs
            return Response()

        monkeypatch.setattr(requests, "head", head)
        console = Console(file=StringIO(), force_terminal=False, record=True)
        mdcat.check_links(["mailto:x", "https://example.test"], console)
        output = console.export_text()
        assert "Link Validation" in output
        assert "URL" in output
        assert "Status" in output
        assert "mailto:x" in output
        assert "500" in output

    def test_render_diff_emits_each_diff_kind(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("same\nold\n")
        second.write_text("same\nnew\nadded\n")
        console = Console(
            file=StringIO(),
            force_terminal=False,
            record=True,
            width=10_000,
        )
        mdcat.render_diff(str(first), str(second), console)
        output = console.export_text()
        assert "first" in output
        assert "second" in output
        assert "@@" in output
        assert " same" in output
        assert "-old" in output
        assert "+new" in output
        assert "+added" in output


class TestMadcatterTailAndCliB:
    def test_hash_and_anchor_boundaries(self) -> None:
        digest = mdcat._line_hash("x")
        assert len(digest) == 16
        assert digest == mdcat._line_hash("x")
        assert (
            mdcat._find_anchor_index(["first", "last"], collections.deque([digest]))
            is None
        )
        last = mdcat._line_hash("last")
        assert (
            mdcat._find_anchor_index(["first", "last"], collections.deque([last])) == 1
        )

    def test_broken_pipe_redirects_devnull(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[tuple[object, ...]] = []

        def open_devnull(*args: object) -> int:
            calls.append(args)
            return 9

        def redirect(*args: object) -> None:
            calls.append(args)

        monkeypatch.setattr(os, "open", open_devnull)
        monkeypatch.setattr(os, "dup2", redirect)
        monkeypatch.setattr(sys.stdout, "fileno", lambda: 7)
        with pytest.raises(SystemExit) as exc:
            mdcat._exit_on_broken_pipe()
        assert exc.value.code == 0
        assert calls == [(os.devnull, os.O_WRONLY), (9, 7)]

    def test_follow_reopen_tail_and_empty_lines(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--follow-lines", "2"])
        stream = StringIO()
        console = Console(file=stream, force_terminal=True, record=True, width=200)
        values = iter([b"old\nanchor\n", b"new1\nnew2\nnew3\n", b"new1\nnew2\nnew3\n"])
        rules: list[tuple[str, dict[str, object]]] = []
        rendered: list[str] = []

        class FakeRule:
            def __init__(self, text: str, **kwargs: object) -> None:
                rules.append((text, kwargs))

        monkeypatch.setattr(mdcat, "Rule", FakeRule)
        sleeps = 0

        def read(path: str) -> bytes:
            del path
            return next(values)

        def render_line(console: Console, flags: object, line: str) -> None:
            del console, flags
            rendered.append(line)

        monkeypatch.setattr(mdcat, "_read_or_none", read)
        monkeypatch.setattr(mdcat, "_render_line", render_line)

        def sleep(delay: float) -> None:
            del delay
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", sleep)
        mdcat.follow_file("x", console, flags, poll=0.25, anchor_window=1)
        assert rendered == ["old", "anchor", "new2", "new3"]
        assert rules == [("reopened", {"style": "dim"})]
        assert "\x1b[2m" in stream.getvalue()
        assert "Stopped following" in stream.getvalue()

    def test_watch_missing_then_update_passes_exact_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        console = Console(file=StringIO(), force_terminal=False, record=True)
        mtimes = iter([None, 0.0, 1.0])
        seen: list[tuple[str, Console, object]] = []
        sleeps = 0

        def mtime(path: str) -> float | None:
            del path
            return next(mtimes)

        def strftime(fmt: str) -> str:
            del fmt
            return "12:34:56"

        monkeypatch.setattr(mdcat, "_mtime_or_none", mtime)
        monkeypatch.setattr(time, "strftime", strftime)

        def render(path: str, actual_console: Console, actual_flags: object) -> str:
            seen.append((path, actual_console, actual_flags))
            return "body"

        def sleep(delay: float) -> None:
            del delay
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", sleep)
        mdcat.watch_file("x.md", render, console, flags)
        assert seen == [("x.md", console, flags)]
        output = console.export_text()
        assert "File x.md not found" in output
        assert "Updated at 12:34:56" in output
        assert "Stopped watching" in output

    def test_export_html_writes_complete_document(self, tmp_path: Path) -> None:
        output = tmp_path / "out.html"
        mdcat.export_html("# H\n\n`code`", str(output))
        text = output.read_text()
        assert text.startswith("<!DOCTYPE html>\n<html>\n")
        assert '<meta charset="utf-8">' in text
        assert "<h1>H</h1>" in text
        assert "<code>code</code>" in text
        assert text.endswith("</html>\n")

    def test_render_stdin_section_and_empty_modes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--section", "Missing"],
        )
        monkeypatch.setattr(sys, "stdin", StringIO("# H\nbody"))
        console = Console(file=StringIO(), force_terminal=False, record=True)
        assert mdcat.render_markdown_file("-", console, flags) == ""
        assert "Section 'Missing' not found" in console.export_text()

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--links"])
        monkeypatch.setattr(sys, "stdin", StringIO("# H\nbody"))

        def extract_links(body: str) -> list[str]:
            del body
            return []

        monkeypatch.setattr(mdcat, "extract_links", extract_links)
        assert mdcat.render_markdown_file("-", console, flags) == "# H\nbody"
        assert "No links found" in console.export_text()

    def test_render_page_and_regular_forward_options(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "x.md"
        path.write_text("hello  \n")
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--page", "--ascii", "--pad", "40", "--justify"],
        )
        paged: list[str] = []
        monkeypatch.setattr(pydoc, "pager", paged.append)
        assert (
            mdcat.render_markdown_file(str(path), Console(file=StringIO()), flags)
            == "hello  \n"
        )
        assert paged
        assert "hello" in paged[0]

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--pad", "40"])
        output = StringIO()
        mdcat.render_markdown_file(str(path), Console(file=output), flags)
        assert "hello" in output.getvalue()

    def test_line_render_processes_emoji_and_math(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--no-math"])
        calls: list[tuple[str, bool]] = []

        def process_math(body: str, enable_math: bool) -> str:
            calls.append((body, enable_math))
            return body

        monkeypatch.setattr(mdcat, "process_math_blocks", process_math)
        console = Console(file=StringIO(), force_terminal=False, record=True)
        mdcat._render_line(console, flags, ":rocket:")
        assert calls == [("🚀", False)]
        assert "🚀" in console.export_text()

    def test_parse_args_defaults_and_aliases_are_exact(self) -> None:
        flags, remaining = mdcat._parse_args(argparse.ArgumentParser(), [])
        assert remaining == []
        assert flags.path == []
        assert flags.force_color is None
        assert flags.ascii is False
        assert flags.code_theme == "monokai"
        assert flags.hyperlinks is True
        assert flags.width is None
        assert flags.pad is None
        assert flags.justify is False
        assert flags.page is False
        assert flags.separator is False
        assert flags.toc is False
        assert flags.links is False
        assert flags.check_links is False
        assert flags.code_only is False
        assert flags.watch is False
        assert flags.follow is False
        assert flags.follow_lines == 0
        assert flags.no_frontmatter is False
        assert flags.math is True
        assert mdcat._parse_args(argparse.ArgumentParser(), ["-F"])[0].follow is True
        assert (
            mdcat._parse_args(argparse.ArgumentParser(), ["--nomath"])[0].math is False
        )
        assert (
            mdcat._parse_args(argparse.ArgumentParser(), ["-t", "x"])[0].code_theme
            == "x"
        )
        assert (
            mdcat._parse_args(argparse.ArgumentParser(), ["-i", "x"])[
                0
            ].inline_code_lexer
            == "x"
        )
        assert mdcat._parse_args(argparse.ArgumentParser(), ["-w", "7"])[0].width == 7
        assert (
            mdcat._parse_args(argparse.ArgumentParser(), ["-n", "2"])[0].follow_lines
            == 2
        )
        assert mdcat._parse_args(argparse.ArgumentParser(), ["-f"])[0].follow is True
        with pytest.raises(SystemExit):
            mdcat._parse_args(argparse.ArgumentParser(), ["--style", "unknown"])


class TestOwnedMutationBoundaries:
    def test_check_links_preserves_table_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[tuple[str, object]] = []

        class Table:
            def __init__(self, **kwargs: object) -> None:
                calls.append(("init", kwargs))

            def add_column(self, *args: str, **kwargs: object) -> None:
                calls.append(("column", (args, kwargs)))

            def add_row(self, *args: str) -> None:
                calls.append(("row", args))

        monkeypatch.setattr(mdcat, "Table", Table)
        console = Console(file=StringIO(), force_terminal=False, width=200)
        mdcat.check_links(["#anchor"], console)
        assert calls[0] == ("init", {"title": "Link Validation", "show_header": True})
        assert calls[1] == ("column", (("URL",), {"style": "cyan"}))
        assert calls[2] == ("column", (("Status",), {"style": "green"}))
        assert calls[3] == (
            "row",
            ("#anchor", "[dim]skipped (not http/s)[/dim]"),
        )

    def test_render_toc_preserves_tree_parent_rules(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nodes: list[tuple[str, object]] = []

        class Node:
            def add(self, label: str) -> Node:
                child = Node()
                nodes.append((label, self))
                return child

        class Tree(Node):
            def __init__(self, label: str, **kwargs: object) -> None:
                nodes.append((label, kwargs))

        monkeypatch.setattr(mdcat, "Tree", Tree)
        mdcat.render_toc(
            [(1, "A"), (2, "B"), (1, "C")],
            Console(file=StringIO(), force_terminal=False, width=200),
        )
        assert nodes[0] == ("📑 Table of Contents", {"guide_style": "dim"})
        assert [label for label, _ in nodes if label.startswith("[bold]")] == [
            "[bold]A[/bold]",
            "[bold]B[/bold]",
            "[bold]C[/bold]",
        ]
        parents = {
            label: parent for label, parent in nodes if label.startswith("[bold]")
        }
        assert parents["[bold]B[/bold]"] is not parents["[bold]C[/bold]"]

    def test_render_code_blocks_forwards_language_and_titles(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[tuple[str, object]] = []
        panel_titles: list[str] = []

        class Syntax:
            def __init__(self, code: str, language: str, **kwargs: object) -> None:
                calls.append(("syntax", (code, language, kwargs)))

        class Panel:
            def __init__(self, value: object, **kwargs: object) -> None:
                del value
                panel_titles.append(str(kwargs["title"]))

        monkeypatch.setattr(mdcat, "Syntax", Syntax)
        monkeypatch.setattr(mdcat, "Panel", Panel)
        mdcat.render_code_blocks(
            [(None, "one"), ("python", "two")],
            Console(file=StringIO(), force_terminal=False, width=200),
        )
        assert ("syntax", ("one", "text", {"theme": "monokai"})) in calls
        assert ("syntax", ("two", "python", {"theme": "monokai"})) in calls
        assert panel_titles == ["Code Block 1", "Code Block 2 (python)"]

    def test_render_diff_forwards_each_style(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("old\n")
        second.write_text("new\n")
        stream = StringIO()
        console = Console(file=stream, force_terminal=True, width=200)
        mdcat.render_diff(str(first), str(second), console)
        output = stream.getvalue()
        assert "---" in output
        assert "\x1b[1;36m" in output
        assert "+++" in output
        assert "\x1b[1;36m" in output
        assert "@@" in output
        assert "\x1b[1;35m" in output
        assert "-old" in output
        assert "\x1b[31m" in output
        assert "+new" in output
        assert "\x1b[32m" in output


class TestMadcatterMainB:
    def test_main_delegates_and_handles_broken_pipe(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mdcat, "_main", lambda: 17)
        assert mdcat.main() == 17
        monkeypatch.setattr(
            mdcat,
            "_main",
            lambda: (_ for _ in ()).throw(BrokenPipeError),
        )
        exited: list[bool] = []
        monkeypatch.setattr(mdcat, "_exit_on_broken_pipe", lambda: exited.append(True))
        assert mdcat.main() is None
        assert exited == [True]

    def test_main_dispatches_watch_follow_and_diff(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc.md"
        path.write_text("# H\n")
        calls: list[str] = []

        def watch(
            path_name: str,
            render: object,
            console: object,
            flags: object,
        ) -> None:
            del path_name, render, console, flags
            calls.append("watch")

        def follow(path_name: str, console: object, flags: object) -> None:
            del path_name, console, flags
            calls.append("follow")

        monkeypatch.setattr(mdcat, "watch_file", watch)
        monkeypatch.setattr(mdcat, "follow_file", follow)
        monkeypatch.setattr(sys, "argv", ["mdcat", "--watch", str(path)])
        assert mdcat._main() == 0
        monkeypatch.setattr(sys, "argv", ["mdcat", "--follow", str(path)])
        assert mdcat._main() == 0
        assert calls == ["watch", "follow"]

    def test_main_rejects_incompatible_flags(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for args in [
            ["--page", "--watch"],
            ["--follow", "--watch"],
            ["--page", "--follow"],
            ["--follow", "--toc"],
        ]:
            monkeypatch.setattr(sys, "argv", ["mdcat", *args])
            with pytest.raises(SystemExit) as exc:
                mdcat._main()
            assert exc.value.code == 2

    def test_parse_args_all_values(self) -> None:
        flags, remaining = mdcat._parse_args(
            argparse.ArgumentParser(),
            [
                "--width",
                "79",
                "--pad",
                "81",
                "--follow-lines",
                "2",
                "--code-theme",
                "x",
                "--inline-code-lexer",
                "y",
                "--style",
                "light",
                "--export-html",
                "h",
                "--export-ansi",
                "a",
                "--section",
                "S",
                "--diff",
                "d",
                "file.md",
            ],
        )
        assert remaining == []
        assert (flags.width, flags.pad, flags.follow_lines) == (79, 81, 2)
        assert (flags.code_theme, flags.inline_code_lexer, flags.style) == (
            "x",
            "y",
            "light",
        )
        assert (flags.export_html, flags.export_ansi, flags.section, flags.diff) == (
            "h",
            "a",
            "S",
            "d",
        )
        assert flags.path == ["file.md"]


class TestOwnedMutationEdges:
    def test_check_links_distinguishes_schemes_and_statuses(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rows: list[tuple[str, str]] = []

        class Table:
            def __init__(self, **kwargs: object) -> None:
                del kwargs

            def add_column(self, *args: str, **kwargs: object) -> None:
                del args, kwargs

            def add_row(self, link: str, status: str) -> None:
                rows.append((link, status))

        class Response:
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

        def head(link: str, **kwargs: object) -> Response:
            del kwargs
            if link == "http://ok":
                return Response(200)
            raise requests.RequestException("down")

        monkeypatch.setattr(mdcat, "Table", Table)
        monkeypatch.setattr(requests, "head", head)
        mdcat.check_links(
            ["mailto:x", "http://ok", "https://bad"],
            Console(file=StringIO(), force_terminal=False, width=200),
        )
        assert rows == [
            ("mailto:x", "[dim]skipped (not http/s)[/dim]"),
            ("http://ok", "[green]✓ 200[/green]"),
            ("https://bad", "[red]✗ RequestException[/red]"),
        ]

    def test_render_diff_preserves_context_style(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("same\nold\n")
        second.write_text("same\nnew\n")
        stream = StringIO()
        console = Console(file=stream, force_terminal=True, width=200)
        mdcat.render_diff(str(first), str(second), console)
        assert " same" in stream.getvalue()
        assert "\x1b[2m" in stream.getvalue()


class TestMadcatterMainB2:
    def test_render_line_passes_all_options(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--justify", "--code-theme", "dracula", "--inline-code-lexer", "python"],
        )
        captured: list[tuple[str, dict[str, object]]] = []

        class FakeMarkdown:
            def __init__(self, body: str, **kwargs: object) -> None:
                captured.append((body, kwargs))

        def process(body: str, enable_math: bool) -> str:
            del enable_math
            return body

        monkeypatch.setattr(mdcat, "Markdown", FakeMarkdown)
        monkeypatch.setattr(mdcat, "process_math_blocks", process)
        mdcat._render_line(Console(file=StringIO()), flags, ":rocket:")
        assert captured == [
            (
                "🚀",
                {
                    "justify": "full",
                    "code_theme": "dracula",
                    "hyperlinks": True,
                    "inline_code_lexer": "python",
                },
            ),
        ]
        default_flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        mdcat._render_line(Console(file=StringIO()), default_flags, "plain")
        assert captured[-1][1]["justify"] == "left"

    def test_export_html_uses_renderer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class FakeMarkdownIt:
            def render(self, body: str) -> str:
                assert body == "source"
                return "<p>rendered</p>"

        monkeypatch.setattr(mdcat, "MarkdownIt", FakeMarkdownIt)
        output = tmp_path / "x.html"
        mdcat.export_html("source", str(output))
        text = output.read_text()
        assert "<p>rendered</p>" in text
        assert "source" not in text


class TestOwnedLinkRequestContract:
    def test_check_links_forwards_timeout_redirects_and_400_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rows: list[tuple[str, str]] = []
        requests_seen: list[tuple[str, object, object]] = []

        class Table:
            def __init__(self, **kwargs: object) -> None:
                del kwargs

            def add_column(self, *args: str, **kwargs: object) -> None:
                del args, kwargs

            def add_row(self, link: str, status: str) -> None:
                rows.append((link, status))

        class Response:
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

        def head(link: str, *, timeout: object, allow_redirects: object) -> Response:
            requests_seen.append((link, timeout, allow_redirects))
            return Response(399 if link.endswith("ok") else 400)

        monkeypatch.setattr(mdcat, "Table", Table)
        monkeypatch.setattr(requests, "head", head)
        mdcat.check_links(
            ["https://ok", "https://boundary"],
            Console(file=StringIO(), force_terminal=False, width=200),
        )
        assert requests_seen == [("https://ok", 5, True), ("https://boundary", 5, True)]
        assert rows == [
            ("https://ok", "[green]✓ 399[/green]"),
            ("https://boundary", "[red]✗ 400[/red]"),
        ]


class TestOwnedCodeRenderingContract:
    def test_render_code_blocks_distinguishes_first_spacing_and_missing_language(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        panels: list[dict[str, object]] = []
        stream = StringIO()

        class Syntax:
            def __init__(self, code: str, language: str, **kwargs: object) -> None:
                del code, language, kwargs

        class Panel:
            def __init__(self, value: object, **kwargs: object) -> None:
                del value
                panels.append(kwargs)

        monkeypatch.setattr(mdcat, "Syntax", Syntax)
        monkeypatch.setattr(mdcat, "Panel", Panel)
        mdcat.render_code_blocks(
            [(None, "one"), ("python", "two")],
            Console(file=stream, force_terminal=False, width=200),
        )
        assert [panel["title"] for panel in panels] == [
            "Code Block 1",
            "Code Block 2 (python)",
        ]
        assert "\n\n" in stream.getvalue()


class TestMadcatterRenderModesB:
    def test_render_modes_call_exact_helpers(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "x.md"
        path.write_text("---\ntitle: x\n---\n# H\nbody\n")
        console = Console(file=StringIO(), force_terminal=False, record=True)
        calls: list[tuple[str, object]] = []
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--no-frontmatter", "--toc"],
        )

        def render_toc(headings: list[tuple[int, str]], actual: Console) -> None:
            del actual
            calls.append(("toc", headings))

        monkeypatch.setattr(mdcat, "render_toc", render_toc)
        assert mdcat.render_markdown_file(str(path), console, flags) == "# H\nbody"
        assert calls == [("toc", [(1, "H")])]

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--links"])

        def extract_links(body: str) -> list[str]:
            del body
            return ["u"]

        monkeypatch.setattr(mdcat, "extract_links", extract_links)
        assert (
            mdcat.render_markdown_file(str(path), console, flags)
            == "---\ntitle: x\n---\n# H\nbody\n"
        )
        assert "Links" in console.export_text()

    def test_parse_args_help_and_all_switches(self) -> None:
        parser = argparse.ArgumentParser()
        mdcat._parse_args(parser, [])
        help_text = parser.format_help()
        for option in (
            "--force-color",
            "--ascii",
            "--code-theme",
            "--inline-code-lexer",
            "--hyperlinks",
            "--width",
            "--pad",
            "--justify",
            "--page",
            "--separator",
            "--toc",
            "--links",
            "--check-links",
            "--code-only",
            "--code-lang",
            "--style",
            "--export-html",
            "--export-ansi",
            "--watch",
            "--follow",
            "--follow-lines",
            "--no-frontmatter",
            "--section",
            "--diff",
            "--no-math",
            "--nomath",
        ):
            assert option in help_text
        flags, remaining = mdcat._parse_args(
            argparse.ArgumentParser(),
            [
                "-c",
                "-y",
                "-j",
                "-p",
                "--separator",
                "--toc",
                "--no-frontmatter",
                "--no-math",
            ],
        )
        assert remaining == []
        assert (flags.force_color, flags.hyperlinks, flags.justify, flags.page) == (
            True,
            True,
            True,
            True,
        )
        assert (flags.separator, flags.toc, flags.no_frontmatter, flags.math) == (
            True,
            True,
            True,
            False,
        )

    def test_main_separator_exports_and_ascii(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("a")
        second.write_text("b")
        html = tmp_path / "x.html"
        ansi = tmp_path / "x.ansi"
        bodies = {str(first): "a", str(second): "b"}

        def render_file(path: str, console: Console, flags: object) -> str:
            del console, flags
            return bodies[path]

        exported: list[tuple[str, str]] = []

        def export_html(body: str, path: str) -> None:
            exported.append((body, path))

        def to_ascii(text: str) -> str:
            return "ASCII:" + text

        monkeypatch.setattr(mdcat, "render_markdown_file", render_file)
        monkeypatch.setattr(mdcat, "export_html", export_html)
        monkeypatch.setattr(mdcat, "to_ascii", to_ascii)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mdcat",
                "--separator",
                "--ascii",
                "--export-html",
                str(html),
                "--export-ansi",
                str(ansi),
                str(first),
                str(second),
            ],
        )
        assert mdcat._main() == 0
        assert exported == [("a\n\nb", str(html))]
        ansi_text = ansi.read_text()
        assert "Exported HTML to" in ansi_text
        output = capsys.readouterr().out
        assert output.startswith("ASCII:")
        assert "Exported ANSI to" in output

    def test_main_uses_separator_and_exact_export_messages(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("a")
        second.write_text("b")
        printed: list[object] = []

        class FakeConsole:
            is_terminal = False
            file = StringIO()

            def __init__(self, **kwargs: object) -> None:
                del kwargs

            def print(self, value: object) -> None:
                printed.append(value)

            def export_text(self) -> str:
                return "ansi"

        monkeypatch.setattr(mdcat, "Console", FakeConsole)

        def render_file(path: str, console: Console, flags: object) -> str:
            del console, flags
            return "a" if path == str(first) else "b"

        monkeypatch.setattr(mdcat, "render_markdown_file", render_file)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mdcat",
                "--separator",
                "--export-ansi",
                str(tmp_path / "x"),
                str(first),
                str(second),
            ],
        )
        assert mdcat._main() == 0
        assert isinstance(printed[0], Rule)
        assert printed[0].style == "dim"
        assert any("Exported ANSI to" in str(value) for value in printed)

    def test_follow_handles_missing_unchanged_and_invalid_bytes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--follow-lines", "1"])
        stream = StringIO()
        console = Console(file=stream, force_terminal=False, record=True)
        values = iter([None, b"first\n", b"first\n", b"bad\xff\n", b"bad\xff\n"])
        sleeps: list[float] = []
        rendered: list[str] = []

        def read_file(path: str) -> bytes | None:
            del path
            return next(values)

        def render_line(console: Console, flags: object, line: str) -> None:
            del console, flags
            rendered.append(line)

        monkeypatch.setattr(mdcat, "_read_or_none", read_file)
        monkeypatch.setattr(mdcat, "_render_line", render_line)

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) == 5:
                raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", sleep)
        mdcat.follow_file("x", console, flags, poll=0.125)
        assert sleeps == [0.125, 0.125, 0.125, 0.125, 0.125]
        assert rendered == ["first", "bad�"]

    def test_follow_defaults_preserve_tail_and_reopen_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--no-frontmatter"],
        )
        stream = StringIO()
        console = Console(file=stream, force_terminal=True, width=200)
        values = iter(
            [
                b"---\ntitle: x\n---\na\n\nb\n",
                b"a\n\nb\nc\n",
                b"a\n\nb\nc\n",
            ],
        )
        rendered: list[str] = []
        seen_paths: list[str] = []
        sleeps: list[float] = []

        def read_file(path: str) -> bytes:
            seen_paths.append(path)
            return next(values)

        def render_line(actual: Console, actual_flags: object, line: str) -> None:
            del actual, actual_flags
            rendered.append(line)

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) == 3:
                raise KeyboardInterrupt

        anchor_calls = 0
        find_anchor = mdcat._find_anchor_index

        def find_anchor_checked(
            lines: list[str],
            anchors: collections.deque[bytes],
        ) -> int | None:
            nonlocal anchor_calls
            anchor_calls += 1
            return find_anchor(lines, anchors)

        monkeypatch.setattr(mdcat, "_read_or_none", read_file)
        monkeypatch.setattr(mdcat, "_find_anchor_index", find_anchor_checked)
        monkeypatch.setattr(mdcat, "_render_line", render_line)
        monkeypatch.setattr(time, "sleep", sleep)
        mdcat.follow_file("x", console, flags, anchor_window=2)
        assert rendered == ["a", "b", "c"]
        assert anchor_calls == 1
        assert seen_paths == ["x", "x", "x"]
        assert sleeps == [0.3, 0.3, 0.3]
        assert "reopened" not in stream.getvalue()
        assert "\x1b[2m" in stream.getvalue()

    def test_follow_lines_limit_applies_on_attach_and_reopen(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--follow-lines", "1"],
        )
        values = iter([b"a\nb\n", b"x\ny\nz\n"])
        rendered: list[str] = []
        sleeps = 0

        def read_file(path: str) -> bytes:
            del path
            return next(values)

        def render_line(actual: Console, actual_flags: object, line: str) -> None:
            del actual, actual_flags
            rendered.append(line)

        def sleep(delay: float) -> None:
            del delay
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                raise KeyboardInterrupt

        monkeypatch.setattr(mdcat, "_read_or_none", read_file)
        monkeypatch.setattr(mdcat, "_render_line", render_line)
        monkeypatch.setattr(time, "sleep", sleep)
        mdcat.follow_file(
            "x",
            Console(file=StringIO(), width=200),
            flags,
            anchor_window=1,
        )
        assert rendered == ["b", "z"]

    def test_follow_anchor_window_drops_the_oldest_anchor(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        values = iter(
            [
                ("\n".join(f"line{i}" for i in range(33)) + "\n").encode(),
                b"line0\nnew\n",
            ],
        )
        rendered: list[str] = []
        sleeps = 0

        def read_file(path: str) -> bytes:
            del path
            return next(values)

        def render_line(actual: Console, actual_flags: object, line: str) -> None:
            del actual, actual_flags
            rendered.append(line)

        def sleep(delay: float) -> None:
            del delay
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                raise KeyboardInterrupt

        monkeypatch.setattr(mdcat, "_read_or_none", read_file)
        monkeypatch.setattr(mdcat, "_render_line", render_line)
        monkeypatch.setattr(time, "sleep", sleep)
        mdcat.follow_file("x", Console(file=StringIO(), width=200), flags)
        assert rendered == [*(f"line{i}" for i in range(33)), "line0", "new"]

    def test_watch_skips_same_mtime_and_passes_one_second_poll(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        console = Console(file=StringIO(), force_terminal=False, record=True)
        mtimes = iter([1.0, 1.0, 2.0])
        sleeps: list[float] = []
        rendered: list[str] = []

        def mtime(path: str) -> float:
            del path
            return next(mtimes)

        monkeypatch.setattr(mdcat, "_mtime_or_none", mtime)

        def render(path: str, actual: Console, actual_flags: object) -> str:
            del actual, actual_flags
            rendered.append(path)
            return "body"

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) == 3:
                raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", sleep)
        mdcat.watch_file("x", render, console, flags)
        assert rendered == ["x", "x"]
        assert sleeps == [1.0, 1.0, 1.0]

    def test_render_page_and_regular_console_options(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "x.md"
        path.write_text("body")
        constructed: list[dict[str, object]] = []

        class FakeMarkdown:
            def __init__(self, body: str, **kwargs: object) -> None:
                constructed.append({"body": body, **kwargs})

        class FakeConsole:
            is_terminal = True

            def __init__(
                self,
                *,
                file: StringIO | None = None,
                **kwargs: object,
            ) -> None:
                self.file = file or StringIO()
                constructed.append(kwargs)

            def print(self, value: object) -> None:
                del value
                self.file.write("rendered")

        monkeypatch.setattr(mdcat, "Markdown", FakeMarkdown)
        monkeypatch.setattr(mdcat, "Console", FakeConsole)
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--justify", "--width", "70", "--force-color"],
        )
        output = StringIO()
        outer_console = Console(file=output, force_terminal=True)
        mdcat.render_markdown_file(str(path), outer_console, flags)
        assert constructed[0] == {
            "body": "body",
            "justify": "full",
            "code_theme": "monokai",
            "hyperlinks": True,
            "inline_code_lexer": None,
        }
        assert constructed[1] == {"force_terminal": True, "width": 70}
        assert output.getvalue() == "rendered"

    def test_render_check_links_and_code_only_paths(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "x.md"
        path.write_text("```python\nprint(1)\n```")
        console = Console(file=StringIO(), force_terminal=False, record=True)
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--check-links"])
        checked: list[list[str]] = []

        def extract_links(body: str) -> list[str]:
            del body
            return ["u"]

        def check_links(links: list[str], actual: Console) -> None:
            del actual
            checked.append(links)

        monkeypatch.setattr(mdcat, "extract_links", extract_links)
        monkeypatch.setattr(mdcat, "check_links", check_links)
        mdcat.render_markdown_file(str(path), console, flags)
        assert checked == [["u"]]

        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--code-only", "--code-lang", "python"],
        )
        rendered: list[list[tuple[str | None, str]]] = []

        def render_code_blocks(
            blocks: list[tuple[str | None, str]],
            actual: Console,
        ) -> None:
            del actual
            rendered.append(blocks)

        monkeypatch.setattr(mdcat, "render_code_blocks", render_code_blocks)
        mdcat.render_markdown_file(str(path), console, flags)
        assert rendered == [[("python", "print(1)\n")]]

    def test_main_invalid_path_counts_and_code_lang_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        for args, message in [
            (["--watch"], "--watch requires exactly one file path"),
            (["--watch", "-"], "--watch requires exactly one file path"),
            (["--follow"], "--follow requires exactly one file path"),
            (["--follow", "-"], "--follow requires exactly one file path"),
            (["--diff", "other.md"], "--diff requires exactly one file argument"),
            (["--code-lang", "python", "--toc"], "--code-lang cannot be used"),
        ]:
            monkeypatch.setattr(sys, "argv", ["mdcat", *args])
            with pytest.raises(SystemExit) as exc:
                mdcat._main()
            expected_code = (
                1
                if args[0] in ("--watch", "--follow")
                or (args[0] == "--diff" and len(args) > 1)
                else 2
            )
            assert exc.value.code == expected_code
            captured = capsys.readouterr()
            assert message in captured.err or message in captured.out


class TestOwnedMutationCoverage:
    def test_process_emoji_fences_and_indented_lines_are_protected(self) -> None:
        body = ":rocket:\n```python\n:fire:\n```\n    :heart:\n:wave:"
        assert mdcat.process_emoji(body) == (
            "🚀\n```python\n:fire:\n```\n    :heart:\n👋"
        )

    def test_extract_headings_tracks_fence_boundaries_and_levels(self) -> None:
        body = "# one\n```\n# hidden\n```\n###### six\n####### invalid\n#no"
        assert mdcat.extract_headings(body) == [(1, "one"), (6, "six")]

    def test_filter_section_keeps_children_and_stops_at_parent_level(self) -> None:
        body = "# Intro\na\n## Target\nb\n### Child\nc\n## Next\nd"
        assert mdcat.filter_section(body, "TARGET") == ("## Target\nb\n### Child\nc")

    def test_render_toc_preserves_sibling_parenting(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parents: dict[str, object] = {}

        class Node:
            def add(self, label: str) -> Node:
                parents[label] = self
                return Node()

        class Tree(Node):
            def __init__(self, label: str, **kwargs: object) -> None:
                del label, kwargs

        monkeypatch.setattr(mdcat, "Tree", Tree)
        mdcat.render_toc(
            [(1, "A"), (2, "B"), (1, "C")],
            Console(file=StringIO(), force_terminal=False),
        )
        assert parents["[bold]B[/bold]"] is not parents["[bold]C[/bold]"]

    def test_render_code_blocks_only_separates_after_the_first(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del monkeypatch
        buf = StringIO()
        mdcat.render_code_blocks(
            [(None, "one"), ("python", "two")],
            Console(file=buf, force_terminal=False),
        )
        output = buf.getvalue()
        first = output.index("Code Block 1")
        second = output.index("Code Block 2 (python)")
        assert "\n\n" in output[first:second]

    def test_render_diff_emits_all_line_kinds_with_exact_styles(
        self,
        tmp_path: Path,
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("same\nold\n")
        second.write_text("same\nnew\n")
        buf = StringIO()
        mdcat.render_diff(
            str(first),
            str(second),
            Console(file=buf, force_terminal=True, width=200),
        )
        output = buf.getvalue()
        assert " same" in output
        assert "---" in output
        assert "+++" in output
        assert "@@" in output
        assert "-old" in output
        assert "+new" in output


class TestOwnedMainAndRenderExact:
    def test_main_forwards_exact_watch_follow_and_diff_arguments(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc.md"
        path.write_text("# H\n")
        seen: list[tuple[str, object, object, object]] = []

        def watch(
            path_name: str,
            render: object,
            console: object,
            flags: object,
        ) -> None:
            seen.append(("watch", path_name, render, (console, flags)))

        def follow(path_name: str, console: object, flags: object) -> None:
            seen.append(("follow", path_name, console, flags))

        def diff(file1: str, file2: str, console: object) -> None:
            seen.append(("diff", file1, file2, console))

        monkeypatch.setattr(mdcat, "watch_file", watch)
        monkeypatch.setattr(mdcat, "follow_file", follow)
        monkeypatch.setattr(mdcat, "render_diff", diff)
        for args, expected in (
            (["--watch", str(path)], "watch"),
            (["--follow", str(path)], "follow"),
            (["--diff", "other.md", str(path)], "diff"),
        ):
            monkeypatch.setattr(sys, "argv", ["mdcat", *args])
            assert mdcat._main() == 0
            assert seen[-1][0] == expected
        assert seen[0][1] == str(path)
        assert seen[1][1] == str(path)
        assert seen[2][1:] == (str(path), "other.md", seen[2][3])

    def test_main_applies_style_and_code_language_exactly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc.md"
        path.write_text("body")
        captured: list[argparse.Namespace] = []

        def render(path_name: str, console: Console, flags: object) -> str:
            del path_name, console
            assert isinstance(flags, argparse.Namespace)
            captured.append(flags)
            return "body"

        monkeypatch.setattr(mdcat, "render_markdown_file", render)
        monkeypatch.setattr(sys, "argv", ["mdcat", "--style", "light", str(path)])
        assert mdcat._main() == 0
        flags = captured[-1]
        assert "code_theme='default'" in repr(flags)

        captured.clear()
        monkeypatch.setattr(
            sys,
            "argv",
            ["mdcat", "--code-lang", "python", str(path)],
        )
        assert mdcat._main() == 0
        assert "code_only=True" in repr(captured[-1])

    def test_render_links_check_links_and_empty_code_are_exact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc.md"
        path.write_text("body")
        buf = StringIO()
        console = Console(file=buf, width=200)
        links_seen: list[list[str]] = []
        checked: list[list[str]] = []

        def links(body: str) -> list[str]:
            assert body == "body"
            links_seen.append(["url"])
            return ["url"]

        def check(values: list[str], actual: Console) -> None:
            assert actual is console
            checked.append(values)

        monkeypatch.setattr(mdcat, "extract_links", links)
        monkeypatch.setattr(mdcat, "check_links", check)
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--links"])
        assert mdcat.render_markdown_file(str(path), console, flags) == "body"
        assert links_seen == [["url"]]
        assert "Links" in buf.getvalue()

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--check-links"])
        assert mdcat.render_markdown_file(str(path), console, flags) == "body"
        assert checked == [["url"]]

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--code-only"])
        assert mdcat.render_markdown_file(str(path), console, flags) == "body"
        assert "No code blocks found" in buf.getvalue()

    def test_render_regular_mode_forwards_false_options_and_strips_padding(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc.md"
        path.write_text("body  \n")
        captured: list[dict[str, object]] = []

        class FakeMarkdown:
            def __init__(self, body: str, **kwargs: object) -> None:
                self.body = body
                captured.append({"body": body, **kwargs})

            @override
            def __str__(self) -> str:
                return self.body

        monkeypatch.setattr(mdcat, "Markdown", FakeMarkdown)
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        output = StringIO()
        console = Console(file=output, force_terminal=False, width=200)
        assert mdcat.render_markdown_file(str(path), console, flags) == "body  \n"
        assert captured == [
            {
                "body": "body  \n",
                "justify": "left",
                "code_theme": "monokai",
                "hyperlinks": True,
                "inline_code_lexer": None,
            },
        ]
        assert output.getvalue() == "body\n\n"


class TestOwnedMutationExactB:
    def test_main_reports_unknown_arguments_exactly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["mdcat", "--unknown"])
        with pytest.raises(SystemExit) as exc:
            mdcat._main()
        assert exc.value.code == 2
        assert "unrecognized arguments: --unknown" in capsys.readouterr().err

    def test_main_reports_incompatible_arguments_exactly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cases = [
            (["--page", "--watch"], "--page and --watch cannot be used together"),
            (["--follow", "--watch"], "--follow and --watch are mutually exclusive"),
            (["--page", "--follow"], "--page and --follow cannot be used together"),
            (
                ["--follow", "--toc"],
                "--follow cannot be combined with --toc/--links/--check-links/--code-only",
            ),
        ]
        for args, message in cases:
            monkeypatch.setattr(sys, "argv", ["mdcat", *args])
            with pytest.raises(SystemExit) as exc:
                mdcat._main()
            assert exc.value.code == 2
            assert message in capsys.readouterr().err

    def test_main_diff_forwards_exact_console(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc.md"
        path.write_text("body")
        calls: list[tuple[object, ...]] = []

        def diff(*args: object) -> None:
            calls.append(args)

        monkeypatch.setattr(mdcat, "render_diff", diff)
        monkeypatch.setattr(sys, "argv", ["mdcat", "--diff", "other.md", str(path)])
        assert mdcat._main() == 0
        assert calls[0][0:2] == (str(path), "other.md")
        assert isinstance(calls[0][2], Console)

    def test_watch_uses_exact_time_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        console = Console(file=StringIO(), force_terminal=False, record=True)
        formats: list[str] = []

        def strftime(fmt: str) -> str:
            formats.append(fmt)
            return "12:34:56"

        def mtime(_: str) -> float:
            return 1.0

        def stop_sleep(_: float) -> None:
            raise KeyboardInterrupt

        def render(path: str, console: Console, flags: object) -> str:
            del path, console, flags
            return "body"

        monkeypatch.setattr(mdcat, "_mtime_or_none", mtime)
        monkeypatch.setattr(time, "strftime", strftime)
        monkeypatch.setattr(time, "sleep", stop_sleep)
        mdcat.watch_file("x.md", render, console, flags)
        assert formats == ["%H:%M:%S"]
        assert console.export_text().endswith("Stopped watching\n")

    def test_main_invalid_watch_follow_and_code_lang_messages(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cases = [
            (["--watch"], "--watch requires exactly one file path", 1),
            (["--follow"], "--follow requires exactly one file path", 1),
            (["--code-lang", "python", "--toc"], "--code-lang cannot be used", 2),
        ]
        for args, message, code in cases:
            monkeypatch.setattr(sys, "argv", ["mdcat", *args])
            with pytest.raises(SystemExit) as exc:
                mdcat._main()
            assert exc.value.code == code
            captured = capsys.readouterr()
            assert message in captured.err or message in captured.out

    def test_main_separator_only_between_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("a")
        second.write_text("b")
        separators: list[object] = []
        output = StringIO()

        class Separator:
            style = "dim"

        def make_rule(**kwargs: object) -> Separator:
            separators.append(kwargs)
            return Separator()

        monkeypatch.setattr(mdcat, "Rule", make_rule)

        def make_console(**kwargs: object) -> Console:
            del kwargs
            return Console(file=output, force_terminal=False, record=True)

        def render_file(*args: object) -> str:
            del args
            return "body"

        monkeypatch.setattr(mdcat, "Console", make_console)
        monkeypatch.setattr(mdcat, "render_markdown_file", render_file)
        monkeypatch.setattr(
            sys,
            "argv",
            ["mdcat", "--separator", str(first), str(second)],
        )
        assert mdcat._main() == 0
        assert separators == [{"style": "dim"}]

    def test_main_ascii_uses_empty_end(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(sys, "argv", ["mdcat", "--ascii", str(path)])

        def print_spy(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

        monkeypatch.setattr("builtins.print", print_spy)
        assert mdcat._main() == 0
        assert calls[-1][1] == {"end": ""}

    def test_render_page_options_are_forwarded_exactly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        page_calls: list[dict[str, object]] = []
        paged: list[str] = []

        def make_console(
            *,
            file: StringIO | None = None,
            force_terminal: bool | None = None,
            width: int | None = None,
        ) -> Console:
            page_calls.append(
                {"file": file, "force_terminal": force_terminal, "width": width},
            )
            return Console(
                file=file or StringIO(),
                force_terminal=force_terminal,
                width=width,
            )

        monkeypatch.setattr(mdcat, "Console", make_console)
        monkeypatch.setattr(pydoc, "pager", paged.append)
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--page", "--force-color", "--width", "70"],
        )
        mdcat.render_markdown_file(str(path), Console(file=StringIO()), flags)
        assert page_calls[-1]["force_terminal"] is True
        assert page_calls[-1]["width"] == 70
        assert paged

    def test_render_regular_mode_forwards_terminal_or_force_color(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        calls: list[dict[str, object]] = []

        class FakeMarkdown:
            def __init__(self, body: str, **kwargs: object) -> None:
                del body, kwargs

        def make_console(
            *,
            file: StringIO | None = None,
            force_terminal: bool | None = None,
            width: int | None = None,
        ) -> Console:
            calls.append(
                {"file": file, "force_terminal": force_terminal, "width": width},
            )
            return Console(
                file=file or StringIO(),
                force_terminal=force_terminal,
                width=width,
            )

        monkeypatch.setattr(mdcat, "Markdown", FakeMarkdown)
        monkeypatch.setattr(mdcat, "Console", make_console)
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--force-color", "--width", "70"],
        )
        mdcat.render_markdown_file(str(path), Console(file=StringIO()), flags)
        assert calls[-1]["force_terminal"] is True
        assert calls[-1]["width"] == 70


class TestOwnedFenceParity:
    def test_process_emoji_keeps_text_after_three_fence_delimiters_protected(
        self,
    ) -> None:
        body = "```\n```\n```\n:rocket:\n```"
        assert mdcat.process_emoji(body) == body

    def test_extract_headings_skips_heading_after_three_fence_delimiters(self) -> None:
        body = "```\n```\n```\n# hidden\n```"
        assert mdcat.extract_headings(body) == []


class TestOwnedMutationExactC:
    def test_main_console_kwargs_are_exact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        calls: list[dict[str, object]] = []

        def make_console(
            *,
            file: StringIO | None = None,
            force_terminal: bool | None = None,
            width: int | None = None,
            record: bool = False,
        ) -> Console:
            calls.append(
                {
                    "file": file,
                    "force_terminal": force_terminal,
                    "width": width,
                    "record": record,
                },
            )
            return Console(
                file=file or StringIO(),
                force_terminal=force_terminal,
                width=width,
                record=record,
            )

        def render_file(*args: object) -> str:
            del args
            return "body"

        monkeypatch.setattr(mdcat, "Console", make_console)
        monkeypatch.setattr(mdcat, "render_markdown_file", render_file)
        monkeypatch.setattr(
            sys,
            "argv",
            ["mdcat", "--force-color", "--width", "77", str(path)],
        )
        assert mdcat._main() == 0
        assert calls == [
            {"file": None, "force_terminal": True, "width": 77, "record": True},
        ]

    def test_invalid_mode_messages_have_no_padding(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cases = [
            (["--follow"], "--follow requires exactly one file path"),
            (["--watch"], "--watch requires exactly one file path"),
            (["--code-lang", "python", "--toc"], "--code-lang cannot be used"),
        ]
        for args, message in cases:
            monkeypatch.setattr(sys, "argv", ["mdcat", *args])
            with pytest.raises(SystemExit):
                mdcat._main()
            output = capsys.readouterr()
            assert message in output.err or message in output.out
            assert "XX" not in output.err + output.out

    def test_render_link_panel_and_code_filter_exactly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        panels: list[dict[str, object]] = []

        class Panel:
            def __init__(self, body: str, **kwargs: object) -> None:
                panels.append({"body": body, **kwargs})

        def extract_links(_: str) -> list[str]:
            return ["a", "b"]

        monkeypatch.setattr(mdcat, "Panel", Panel)
        monkeypatch.setattr(mdcat, "extract_links", extract_links)
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--links"])
        mdcat.render_markdown_file(str(path), Console(file=StringIO()), flags)
        assert panels == [{"body": "a\nb", "title": "Links"}]

        seen: list[object] = []

        def extract(body: str, language: str | None) -> list[tuple[str | None, str]]:
            del body
            seen.append(language)
            return []

        monkeypatch.setattr(mdcat, "extract_code_blocks", extract)
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--code-only", "--code-lang", "python"],
        )
        mdcat.render_markdown_file(str(path), Console(file=StringIO()), flags)
        assert seen == ["python"]


class TestOwnedMutationExactD:
    def test_main_ascii_console_contract(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        seen: list[dict[str, object]] = []

        def make_console(
            *,
            file: StringIO | None = None,
            force_terminal: bool | None = None,
            width: int | None = None,
            record: bool = False,
        ) -> Console:
            seen.append(
                {
                    "file": file,
                    "force_terminal": force_terminal,
                    "width": width,
                    "record": record,
                },
            )
            return Console(
                file=file or StringIO(),
                force_terminal=force_terminal,
                width=width,
            )

        def render_file(*args: object) -> str:
            del args
            return "body"

        monkeypatch.setattr(mdcat, "Console", make_console)
        monkeypatch.setattr(mdcat, "render_markdown_file", render_file)
        monkeypatch.setattr(sys, "argv", ["mdcat", "--ascii", str(path)])

        def print_sink(*args: object, **kwargs: object) -> None:
            del args, kwargs

        monkeypatch.setattr("builtins.print", print_sink)
        assert mdcat._main() == 0
        assert seen == [
            {
                "file": seen[0]["file"],
                "force_terminal": False,
                "width": None,
                "record": True,
            },
        ]

    def test_diff_invalid_message_has_no_mutant_padding(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["mdcat", "--diff", "other.md"])
        with pytest.raises(SystemExit) as exc:
            mdcat._main()
        assert exc.value.code == 1
        output = capsys.readouterr()
        assert "Error: --diff requires exactly one file argument" in output.out
        assert "XX" not in output.out


class TestOwnedMutationExactE:
    def test_help_contains_exact_module_description(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["mdcat", "--help"])
        with pytest.raises(SystemExit) as exc:
            mdcat._main()
        assert exc.value.code == 0
        output = capsys.readouterr().out
        doc = mdcat.__doc__
        assert doc is not None
        assert doc.splitlines()[0] in output

    def test_incompatible_messages_are_exact(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cases = [
            (["--page", "--watch"], "--page and --watch cannot be used together"),
            (["--follow", "--watch"], "--follow and --watch are mutually exclusive"),
            (["--page", "--follow"], "--page and --follow cannot be used together"),
        ]
        for args, message in cases:
            monkeypatch.setattr(sys, "argv", ["mdcat", *args])
            with pytest.raises(SystemExit) as exc:
                mdcat._main()
            assert exc.value.code == 2
            assert capsys.readouterr().err.endswith(f"error: {message}\n")

    def test_follow_invalid_path_preserves_case(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["mdcat", "--follow", "a", "b"])
        with pytest.raises(SystemExit) as exc:
            mdcat._main()
        assert exc.value.code == 1
        assert (
            "Error: --follow requires exactly one file path" in capsys.readouterr().out
        )

    def test_follow_receives_exact_flags(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        seen: list[tuple[str, Console, mdcat._Flags]] = []

        def follow(path_name: str, console: Console, flags: mdcat._Flags) -> None:
            seen.append((path_name, console, flags))

        monkeypatch.setattr(mdcat, "follow_file", follow)
        monkeypatch.setattr(sys, "argv", ["mdcat", "--follow", str(path)])
        assert mdcat._main() == 0
        assert seen[0][0] == str(path)
        assert isinstance(seen[0][1], Console)
        assert seen[0][2].follow is True

    def test_export_html_forces_utf8_under_ascii_locale(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def ascii_encoding(*args: object) -> str:
            del args
            return "ascii"

        monkeypatch.setattr("locale.getpreferredencoding", ascii_encoding)
        output = tmp_path / "out.html"
        mdcat.export_html("é", str(output))
        assert "é" in output.read_text(encoding="utf-8")


class TestOwnedMutationExactF:
    def test_follow_error_and_unknown_arguments_are_exact(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["mdcat", "--follow", "--toc"])
        with pytest.raises(SystemExit):
            mdcat._main()
        assert capsys.readouterr().err.endswith(
            "error: --follow cannot be combined with --toc/--links/--check-links/--code-only\n",
        )

        monkeypatch.setattr(sys, "argv", ["mdcat", "--unknown", "other"])
        with pytest.raises(SystemExit):
            mdcat._main()
        assert "unrecognized arguments: --unknown" in capsys.readouterr().err

    def test_watch_forwards_exact_console_render_and_flags(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        seen: list[tuple[str, object, Console, mdcat._Flags]] = []

        def watch(
            path_name: str,
            render: object,
            console: Console,
            flags: mdcat._Flags,
        ) -> None:
            seen.append((path_name, render, console, flags))

        monkeypatch.setattr(mdcat, "watch_file", watch)
        monkeypatch.setattr(sys, "argv", ["mdcat", "--watch", str(path)])
        assert mdcat._main() == 0
        assert seen[0][0] == str(path)
        assert seen[0][1] is mdcat.render_markdown_file
        assert isinstance(seen[0][2], Console)
        assert seen[0][3].watch is True

    def test_ansi_export_requests_utf8(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        ansi = tmp_path / "doc.ansi"

        def make_console(**kwargs: object) -> Console:
            del kwargs
            return Console(file=StringIO(), record=True)

        def render(path_name: str, console: Console, flags: object) -> str:
            del path_name, flags
            console.print("é")
            return "body"

        def ascii_encoding(*args: object) -> str:
            del args
            return "ascii"

        monkeypatch.setattr(mdcat, "Console", make_console)
        monkeypatch.setattr(mdcat, "render_markdown_file", render)
        monkeypatch.setattr("locale.getpreferredencoding", ascii_encoding)
        monkeypatch.setattr(
            sys,
            "argv",
            ["mdcat", "--export-ansi", str(ansi), str(path)],
        )
        assert mdcat._main() == 0
        assert "é" in ansi.read_text(encoding="utf-8")

    def test_follow_forbids_each_display_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for option in ("--links", "--check-links", "--code-only"):
            monkeypatch.setattr(sys, "argv", ["mdcat", "--follow", option])
            with pytest.raises(SystemExit) as exc:
                mdcat._main()
            assert exc.value.code == 2

    def test_diff_requires_one_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["mdcat", "--diff", "other", "a", "b"])
        with pytest.raises(SystemExit) as exc:
            mdcat._main()
        assert exc.value.code == 1

    def test_code_language_forbids_each_display_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for option in ("--links", "--check-links", "--toc"):
            monkeypatch.setattr(sys, "argv", ["mdcat", "--code-lang", "python", option])
            with pytest.raises(SystemExit) as exc:
                mdcat._main()
            assert exc.value.code == 2

    def test_watch_passes_path_and_initial_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        console = Console(file=StringIO(), force_terminal=False, record=True)
        seen: list[str] = []

        def mtime(path: str) -> float:
            seen.append(path)
            raise KeyboardInterrupt

        monkeypatch.setattr(mdcat, "_mtime_or_none", mtime)

        def render(path: str, actual: Console, actual_flags: mdcat._Flags) -> str:
            del path, actual, actual_flags
            return "body"

        mdcat.watch_file("watched.md", render, console, flags)
        assert seen == ["watched.md"]
        assert "Watching watched.md for changes" in console.export_text()

    def test_render_math_receives_flag_and_links_are_exact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "doc"
        path.write_text("body")
        math_flags: list[bool] = []

        def math(body: str, *, enable_math: bool) -> str:
            del body
            math_flags.append(enable_math)
            return "body"

        monkeypatch.setattr(mdcat, "process_math_blocks", math)
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--no-math"])
        mdcat.render_markdown_file(str(path), Console(file=StringIO()), flags)
        assert math_flags == [False]

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--links"])

        def extract_links(_: str) -> list[str]:
            return []

        monkeypatch.setattr(mdcat, "extract_links", extract_links)
        output = StringIO()
        mdcat.render_markdown_file(str(path), Console(file=output), flags)
        assert "No links found" in output.getvalue()
        assert "XX" not in output.getvalue()


class TestOwnedMutationExactG:
    def test_render_diff_passes_exact_styles(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.write_text("same\nold\n")
        second.write_text("same\nnew\n")
        console = Console(file=StringIO(), force_terminal=False)
        calls: list[tuple[str, object]] = []

        def record(text: str, *, style: object) -> None:
            calls.append((text, style))

        monkeypatch.setattr(console, "print", record)
        mdcat.render_diff(str(first), str(second), console)
        assert ("--- " + str(first), "bold cyan") in calls
        assert ("+++ " + str(second), "bold cyan") in calls
        assert any(
            text.startswith("@@") and style == "bold magenta" for text, style in calls
        )
        assert ("-old", "red") in calls
        assert ("+new", "green") in calls
        assert (" same", "dim") in calls

    def test_render_code_blocks_adds_spacing_only_between_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        console = Console(file=StringIO(), force_terminal=False)
        printed: list[object] = []

        def record(value: object = None) -> None:
            printed.append(value)

        monkeypatch.setattr(console, "print", record)
        mdcat.render_code_blocks([(None, "one"), ("python", "two")], console)
        assert printed[1] is None
        assert len(printed) == 3


class TestOwnedMutationExactH:
    def test_open_calls_pin_utf8(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = Path.open
        calls: list[tuple[str, str | None]] = []

        def tracked_open(
            path: Path,
            mode: str = "r",
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> TextIOBase:
            calls.append((mode, encoding))
            result = original(
                path,
                mode=mode,
                encoding=encoding,
                errors=errors,
                newline=newline,
            )
            assert isinstance(result, TextIOBase)
            return result

        monkeypatch.setattr(Path, "open", tracked_open)
        source = tmp_path / "doc"
        source.write_text("body")
        calls.clear()
        output = tmp_path / "out.html"
        mdcat.export_html("é", str(output))
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), [])
        mdcat.render_markdown_file(str(source), Console(file=StringIO()), flags)
        assert calls[:2] == [("w", "utf-8"), ("r", "utf-8")]

    def test_main_exact_error_case_and_unknown_join(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["mdcat", "--watch", "-"])
        with pytest.raises(SystemExit):
            mdcat._main()
        assert (
            "Error: --watch requires exactly one file path" in capsys.readouterr().out
        )

        monkeypatch.setattr(sys, "argv", ["mdcat", "--unknown", "--other"])
        with pytest.raises(SystemExit):
            mdcat._main()
        assert "unrecognized arguments: --unknown --other" in capsys.readouterr().err

    def test_render_page_section_empty_code_and_inline_options(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source = tmp_path / "doc"
        source.write_text("body  \n")
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--page", "--inline-code-lexer", "python"],
        )
        paged: list[str] = []
        monkeypatch.setattr(pydoc, "pager", paged.append)
        mdcat.render_markdown_file(str(source), Console(file=StringIO()), flags)
        assert paged
        assert paged[0].endswith("body\n")

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--section", "Target"])

        def filter_section(body: str, name: str) -> str:
            del body, name
            return "body"

        monkeypatch.setattr(mdcat, "filter_section", filter_section)
        assert (
            mdcat.render_markdown_file(str(source), Console(file=StringIO()), flags)
            == "body"
        )

        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--code-only"])
        output = StringIO()
        mdcat.render_markdown_file(str(source), Console(file=output), flags)
        assert "No code blocks found" in output.getvalue()
        assert "XX" not in output.getvalue()

    def test_page_console_ascii_force_terminal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source = tmp_path / "doc"
        source.write_text("body")
        calls: list[dict[str, object]] = []

        def make_console(
            *,
            file: StringIO | None = None,
            force_terminal: bool | None = None,
            width: int | None = None,
        ) -> Console:
            calls.append({"force_terminal": force_terminal, "width": width})
            return Console(
                file=file or StringIO(),
                force_terminal=force_terminal,
                width=width,
            )

        monkeypatch.setattr(mdcat, "Console", make_console)
        flags, _ = mdcat._parse_args(argparse.ArgumentParser(), ["--page", "--ascii"])

        def pager(_: str) -> None:
            del _

        monkeypatch.setattr(pydoc, "pager", pager)
        mdcat.render_markdown_file(str(source), Console(file=StringIO()), flags)
        assert calls[-1] == {"force_terminal": False, "width": None}

    def test_main_ansi_open_pins_utf8(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = Path.open
        calls: list[tuple[str, str | None]] = []

        def tracked_open(
            path: Path,
            mode: str = "r",
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> TextIOBase:
            calls.append((mode, encoding))
            result = original(
                path,
                mode=mode,
                encoding=encoding,
                errors=errors,
                newline=newline,
            )
            assert isinstance(result, TextIOBase)
            return result

        monkeypatch.setattr(Path, "open", tracked_open)
        source = tmp_path / "doc"
        source.write_text("body")
        ansi = tmp_path / "out.ansi"
        calls.clear()

        def render(path: str, console: Console, flags: object) -> str:
            del path, console, flags
            return "body"

        monkeypatch.setattr(mdcat, "render_markdown_file", render)
        monkeypatch.setattr(
            sys,
            "argv",
            ["mdcat", "--export-ansi", str(ansi), str(source)],
        )
        assert mdcat._main() == 0
        assert calls[-1] == ("w", "utf-8")

    def test_regular_markdown_forwards_inline_lexer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source = tmp_path / "doc"
        source.write_text("body")
        values: list[dict[str, object]] = []

        class FakeMarkdown:
            def __init__(self, body: str, **kwargs: object) -> None:
                values.append({"body": body, **kwargs})

        monkeypatch.setattr(mdcat, "Markdown", FakeMarkdown)
        flags, _ = mdcat._parse_args(
            argparse.ArgumentParser(),
            ["--inline-code-lexer", "python"],
        )
        mdcat.render_markdown_file(str(source), Console(file=StringIO()), flags)
        assert values[0]["inline_code_lexer"] == "python"


if __name__ == "__main__":
    from madcatter.lib.testing.main import test_main

    test_main(__file__)
