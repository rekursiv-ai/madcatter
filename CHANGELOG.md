# Changelog

All notable madcatter changes are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.1.7 - 2026-10-31

### Added

- `mdcat -i` (`--in-place`) writes the colored render over each file, at 80
  columns unless `-w` is given. The file carries its source in invisible OSC 8
  codes. Every file is read before any is written.
- `mdcat --unrender` turns mdcat output back into markdown: a file `-i` wrote
  comes back byte for byte while its shown text is unedited; other output is
  read back from what it shows.
- `mdcat` sets the terminal title to the file names.
- `madcatter` runs the same CLI as `mdcat`, so `uvx madcatter` needs no
  `--from`.

### Changed

- Color is on by default, even through pipes. `-c`/`--color` is kept;
  `--no-c`/`--no-color` turns it off.
- `-i` now means `--in-place`. Spell the inline lexer `--inline-code-lexer`;
  `mdcat -i python foo.md` now renders `python` and `foo.md` in place.
- Ordered lists render as `1.`, and a list item's paragraphs stay separated.
- `--export-ansi` writes the render; it wrote an empty file.
- `--diff` and `--follow` read a rendered file as its markdown.
- `--hyperlinks` can be turned off with `--no-hyperlinks`.
- `--page` with `--export-ansi` is an error; the export was empty.
- Style profiles hold only the code theme; the unused `background` is gone.

### Fixed

- `--links` and `--check-links` find links; they found none in any file.
- Math is never read across or inside code: `$5 and \`x\` then $10` no longer
  garbles the code span, and `$$` around a fenced block leaves the block as is.
  Code blocks follow CommonMark, so math in a nested list item converts and
  tab-indented code stays literal.
- `:shortcode:` emoji stay literal inside inline code and indented code.
- `--section` ignores `#` lines inside code blocks.
- Headings, section names, code languages, link URLs, and file paths that
  contain Rich markup such as `[/x]` are shown as written; they crashed or
  restyled the output.
- `--export-html` shows raw HTML in the source as text instead of emitting it.
- An unreadable or unwritable file, a non-UTF-8 stdin, or a failed export
  ends with `mdcat: <path>: <reason>` and exit 1, not a traceback.
- `--watch` keeps watching when the file vanishes mid-read, and reports a
  missing file once instead of every second.
- 84 gendered emoji, such as `biking_man`, join with U+200D and render as one
  glyph.
- `\frac` with a missing part renders it empty; `\frac{}` rendered `%s/%s`.
- Rendering a large file is faster: 10.7 s to under 2 s on a 1.9 MB file.

### Removed

- `-C` and `--force-color`; use `--no-color` and `--color`.
- `madcatter.lib.worker_count` is no longer part of the package. It moved, with
  the pre-commit gates that use it, to `tools/gate/` at the repository root,
  which the wheel does not ship.

## 0.1.6 - 2026-10-21

### Changed

- The wheel no longer ships `madcatter.lib.testing`, whose modules import
  `pytest`, a test-only dependency.

## 0.1.5 - 2026-10-07

### Changed

- Development: the patched typeshed now also types `typing.get_type_hints`
  as `dict[str, object]`, the pre-commit configuration is updated, a
  worker-count helper is vendored as an internal module, and internal LaTeX
  conversion code is simplified without changing its output. Runtime
  dependencies and the supported Python versions (3.12+) are unchanged.

## 0.1.4 - 2026-10-03

### Fixed

- `latex2unicode`, and math rendering in `mdcat`, now convert every
  subscript and superscript in a run of text that ends in `_` or `^`
  right before a braced group. Before, the scripts earlier in that run were
  emitted raw: `$\prod_t q(x_t|e_t) p(e_{t+1}|e_t,x_t)$` rendered as
  `∏_t q(x_t|e_t) p(eₜ₊₁|eₜ,xₜ)` and now renders as
  `∏ₜ q(xₜ|eₜ) p(eₜ₊₁|eₜ,xₜ)`.

### Changed

- The parsed-options parameter of `render_markdown_file`, `watch_file` and
  `follow_file` in `madcatter.mdcat` is now named `flags` (was `args`).
  Callers that pass it by position are unaffected.

- README: the sibling-projects list drops a link that no longer resolves.

- Development: type checking uses a bundled, patched typeshed
  (`packages/rekursiv-ai-typeshed`), which `uv sync` installs as a path
  dependency. The minimum versions of ty and basedpyright are raised, and
  the pre-commit configuration is updated. Runtime dependencies and the
  supported Python versions (3.12+) are unchanged.

## 0.1.3 - 2026-08-19

### Fixed

- A single-line code span written with triple backticks, such as
  ```` ```x = 1``` ````, is no longer mistaken for the opening of a fenced
  code block. CommonMark forbids backticks in a fence info string, so such
  a line is inline code; treating it as a fence left the renderer stuck
  "inside" a block for the rest of the file, which silently suppressed math
  conversion and emoji expansion on every following line and hid every
  following heading from the table of contents.

- An unterminated fenced code block no longer discards the tail of the
  document. Content buffered after the last unclosed fence is now emitted
  instead of being dropped, so a file that ends mid-fence still renders in
  full.

## 0.1.2 - 2026-08-01

### Changed

- README carries a one-line description below the badges; PyPI renders the
  README, so the project page had been showing the previous text.

## 0.1.1 - 2026-08-01

### Changed

- README leads with a Quick Start; the duplicate Install section is folded
  into it, with `uv tool install` for the CLI and pip named as the
  alternative.

- Initial public release of madcatter: a Rich-based Markdown console
  renderer (the `mdcat` CLI) with emoji shortcode expansion, LaTeX-to-Unicode
  math rendering, and Markdown preprocessing helpers.
