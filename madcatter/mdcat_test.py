"""Tests for mdcat-specific helpers (emoji shortcodes)."""

from __future__ import annotations

import pytest

from madcatter.mdcat import process_emoji


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
