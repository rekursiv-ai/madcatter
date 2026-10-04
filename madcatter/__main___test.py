"""Tests for the Madcatter module entry point."""

from __future__ import annotations

import runpy

import pytest

from madcatter import mdcat


def test_module_run_exits_with_main_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_main() -> int:
        return 3

    monkeypatch.setattr(mdcat, "main", fake_main)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("madcatter", run_name="__main__")
    assert exc.value.code == 3


if __name__ == "__main__":
    from madcatter.lib.testing.main import test_main

    test_main(__file__)
