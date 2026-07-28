#!/bin/sh
# ruff: noqa: EXE003, D300 -- Polyglot shell/Python script.
# fmt: off
'''' 2>/dev/null #
exec uv --quiet --project "$(dirname "$0")" run --frozen --no-sync python3 "$0" "$@"
Render Markdown to the console with Rich.

Executable entry point: dispatches to madcatter.mdcat.main, which owns
all rendering and error handling (including the broken-pipe guard). Runs as
both ``./__main__.py`` and ``python -m madcatter``.
'''
# fmt: on

from __future__ import annotations

from madcatter.mdcat import main


if __name__ == "__main__":
    raise SystemExit(main())
# vim: ft=python
