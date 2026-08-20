# Changelog

All notable madcatter changes are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

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
