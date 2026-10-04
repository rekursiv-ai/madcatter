# Changelog

All notable madcatter changes are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
