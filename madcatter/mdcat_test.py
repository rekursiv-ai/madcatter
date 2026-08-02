"""Tests for mdcat-specific helpers (emoji shortcodes)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sys

import pytest

from madcatter.mdcat import extract_headings, main, process_emoji


if TYPE_CHECKING:
    from pathlib import Path


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


if __name__ == "__main__":
    from madcatter.lib.testing import test_main

    test_main(__file__)
