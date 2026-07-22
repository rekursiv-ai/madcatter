# madcatter

Render Markdown to the terminal with [Rich](https://github.com/Textualize/rich).

`madcatter` provides the `mdcat` CLI: a Markdown console renderer with
left-justified headings, `:shortcode:` emoji expansion, LaTeX-to-Unicode math
(`$...$` and `$$...$$`), syntax-highlighted code blocks, a table-of-contents
view, link extraction and validation, ASCII/HTML/ANSI export, and
`tail -F`-style follow and watch modes.

## Install

```bash
pip install madcatter
```

## Usage

```bash
mdcat README.md              # render a file
mdcat -                      # render stdin
mdcat --toc README.md        # show the table of contents
mdcat --style dracula doc.md # use a predefined color profile
```

Run `mdcat --help` for the full flag list.

## Library

The preprocessing helpers are importable directly:

```python
from madcatter.markdown import process_math_blocks, strip_frontmatter
from madcatter.latex import latex2unicode
from madcatter.emoji import resolve
```
