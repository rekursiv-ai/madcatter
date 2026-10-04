"""Tests for emoji shortcode resolution."""

from madcatter import emoji


def test_resolve_known_shortcode_with_colons() -> None:
    assert emoji.resolve(":smile:") == "😄"


def test_resolve_known_shortcode_without_colons() -> None:
    assert emoji.resolve("heart") == "❤️"


def test_resolve_strips_only_surrounding_colons() -> None:
    assert emoji.resolve(":::smile:::") == "😄"


def test_resolve_unknown_shortcode_returns_none() -> None:
    assert emoji.resolve(":does_not_exist:") is None


def test_resolve_does_not_strip_non_colon_characters() -> None:
    assert emoji.resolve("XsmileX") is None


if __name__ == "__main__":
    from madcatter.lib.testing.main import test_main

    test_main(__file__)
