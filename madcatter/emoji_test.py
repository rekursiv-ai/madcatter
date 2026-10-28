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


def test_gendered_sequences_join_with_zero_width_joiner() -> None:
    unjoined = {
        name: value
        for name, value in emoji.EMOJI.items()
        if len(core := value.rstrip("\ufe0f")) > 1
        and core[-1] in "♂♀"
        and core[-2] != "\u200d"
    }
    assert unjoined == {}
    assert emoji.resolve("biking_man") == "🚴\u200d♂"


if __name__ == "__main__":
    from madcatter.lib.testing.runner import test_main

    test_main(__file__)
