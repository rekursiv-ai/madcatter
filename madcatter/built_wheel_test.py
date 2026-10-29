"""The madcatter wheel, built and imported outside the checkout."""

from __future__ import annotations

import pytest

from madcatter.lib.testing.wheel import built_wheel


pytestmark = pytest.mark.cli_uv


def test_the_wheel_imports_outside_the_checkout() -> None:
    wheel = built_wheel("madcatter", anchor=__file__)

    assert "site-packages" in wheel.run("import madcatter; print(madcatter.__file__)")


if __name__ == "__main__":
    from madcatter.lib.testing.runner import test_main

    test_main(__file__)
